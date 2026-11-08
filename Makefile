# Fresh clone:  git clone https://github.com/pardhu1502/cloud-kd && cd cloud-kd && make up
# Needs: docker, k3d, kubectl, python 3.12+, bash (Git Bash on Windows).
SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c

CLUSTER  := kd
SYS_PY   ?= python
# the project venv once it exists (Windows or Linux layout), else the system python
PY        = $(firstword $(wildcard .venv/Scripts/python.exe .venv/bin/python) $(SYS_PY))
ENV      := set -a; if [ -f .env ]; then . ./.env; fi; set +a; export S3_ENDPOINT=$${S3_ENDPOINT:-http://localhost:8333};
CONFIG   ?= training/config.yaml
SUBSET   ?=
VERSION  ?= v1
RUNTIME  ?= 2m

.PHONY: up down venv cluster secrets storage buckets images seed-models deploy \
        label label-logs clean-data export-shards train publish-model bad-model \
        eval eval-teacher eval-base eval-student test lint loadtest mem-test cold-start \
        rollout-test recovery-test hpa-test lb-test

## ---- whole system ----
up: venv cluster secrets storage buckets images seed-models deploy
	@echo
	@echo "up. try: curl -s -X POST localhost:8080/parse -H 'Content-Type: application/json' -d '{\"text\": \"what is the weather in london\"}'"

down:
	k3d cluster delete $(CLUSTER)

.venv:
	$(SYS_PY) -m venv --system-site-packages .venv

venv: .venv
	$(PY) -m pip install -q -r requirements-dev.txt

cluster:
	k3d cluster list $(CLUSTER) >/dev/null 2>&1 || k3d cluster create --config cluster/k3d.yaml

secrets:
	bash scripts/secrets.sh

storage:
	kubectl apply -f k8s/data/seaweedfs.yaml
	kubectl -n data rollout status deploy/seaweedfs --timeout=300s

buckets:
	$(ENV) $(PY) scripts/bootstrap_s3.py

images:
	docker build -f service/Dockerfile -t kd-parser:latest .
	docker build -f worker/Dockerfile -t kd-worker:latest .
	k3d image import kd-parser:latest kd-worker:latest -c $(CLUSTER)

# model weights live in the GitHub Release, never in git or in the image
seed-models:
	$(ENV) $(PY) scripts/models.py seed --versions v1 v2

deploy:
	kubectl apply -f k8s/app/
	kubectl -n app rollout status deploy/parser --timeout=600s

## ---- Task 1: teacher labelling ----
label:
	kubectl -n pipeline delete job teacher-labelling --ignore-not-found
	kubectl apply -f k8s/pipeline/worker-job.yaml

label-logs:
	kubectl -n pipeline logs -l app=teacher-worker -f --prefix --max-log-requests 4

clean-data:
	$(ENV) $(PY) worker/clean.py

export-shards:
	$(ENV) $(PY) scripts/bootstrap_s3.py --get s3://datasets/teacher/ results/teacher

## ---- Task 2: student ----
train:
	$(PY) training/train.py --config $(CONFIG) $(if $(SUBSET),--subset $(SUBSET))

publish-model:
	$(ENV) $(PY) scripts/models.py publish --version $(VERSION)

bad-model:
	$(PY) scripts/models.py base --dest artifacts/models/pythia-base
	$(PY) scripts/models.py package --version bad --src artifacts/models/pythia-base

eval: eval-teacher eval-base eval-student

eval-teacher:
	$(PY) eval/predict_teacher.py --out results/teacher_validation_predictions.jsonl
	$(PY) tools/score.py results/teacher_validation_predictions.jsonl data/validation.jsonl --out results/teacher_validation.json

eval-base:
	$(PY) eval/predict_hf.py --model EleutherAI/pythia-70m --out results/pythia_base_validation_predictions.jsonl
	$(PY) tools/score.py results/pythia_base_validation_predictions.jsonl data/validation.jsonl --out results/pythia_base_validation.json

eval-student:
	$(PY) eval/predict_hf.py --model artifacts/models/$(VERSION) --out results/student_$(VERSION)_validation_predictions.jsonl
	$(PY) tools/score.py results/student_$(VERSION)_validation_predictions.jsonl data/validation.jsonl --out results/student_$(VERSION)_validation.json

## ---- checks ----
test:
	$(PY) -m pytest -q

lint:
	$(PY) -m ruff check .

## ---- Tasks 3, 4, 7: experiments (results go to results/) ----
loadtest:
	PY=$(PY) bash scripts/load.sh loadtest $(RUNTIME)

mem-test:
	bash scripts/mem_test.sh

cold-start:
	bash scripts/cold_start.sh

rollout-test:
	PY=$(PY) bash scripts/k8s_tests.sh rollout

recovery-test:
	PY=$(PY) bash scripts/k8s_tests.sh recovery

hpa-test:
	PY=$(PY) bash scripts/k8s_tests.sh hpa

lb-test:
	PY=$(PY) bash scripts/k8s_tests.sh lb
