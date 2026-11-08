# cloud-kd

Cloud Computing (CS3081) mini project: sequence-level knowledge distillation of a
command parser from **phi3.5** (teacher, 3.8B, Ollama) into **Pythia-70M** (student),
served on a local **k3d** Kubernetes cluster with **SeaweedFS** object storage.

- Name: Palli Pardha Saradhi Charan
- Roll no: 230103009
- Repository: https://github.com/pardhu1502/cloud-kd
- Model releases: https://github.com/pardhu1502/cloud-kd/releases
  ([model-v1](https://github.com/pardhu1502/cloud-kd/releases/tag/model-v1),
  [model-v2](https://github.com/pardhu1502/cloud-kd/releases/tag/model-v2))

```
"set an alarm for seven thirty am tomorrow"
  -> {"intent": "alarm_set", "date": "tomorrow", "time": "seven thirty am", "place": null}
```

## Layout

| Path | What |
|---|---|
| `cluster/k3d.yaml` | k3d cluster (1 server, localhost:8080 -> Traefik, localhost:8333 -> SeaweedFS S3) |
| `k8s/data/` | SeaweedFS in namespace `data` |
| `k8s/pipeline/` | Indexed Job with two labelling workers in namespace `pipeline` |
| `k8s/app/` | Deployment, Service, Ingress, HPA in namespace `app` |
| `prompts/teacher_prompt.txt` | the teacher prompt |
| `worker/worker.py`, `worker/clean.py` | sharded teacher labelling, dataset cleaning |
| `training/` | `config.yaml` (v1), `config_v2.yaml` (v2), `train.py`, `loss.csv` |
| `service/` | FastAPI inference service + Dockerfile |
| `eval/` | prediction scripts for the teacher and HF models |
| `kd/` | shared code (S3 client, prompt format, teacher call) |
| `scripts/` | secrets, buckets, model packaging, load / cold-start / k8s experiments |
| `network/` | `subnets.md`, `nacl.json` |
| `data/`, `tools/` | the student kit (commands, validation set, schema, rate card, score.py, nacl_sim.py, locustfile.py) |
| `data/v1/` | cleaned teacher dataset (`train.jsonl`, `train.sha256`) |
| `results/` | evidence: score reports, Locust output, logs |
| `report/` | report source |

## Requirements

Docker, [k3d](https://k3d.io) v5, kubectl, Python 3.12+, GNU make and bash
(on Windows: Git Bash, plus `winget install GnuWin32.Make` or `choco install make`).
Ollama with `ollama pull phi3.5` for the labelling step only.

No credentials are stored in the repository: `scripts/secrets.sh` generates random S3
keys into the git-ignored `.env` and loads them into Kubernetes Secrets.

## Build, deploy, tear down

```bash
git clone https://github.com/pardhu1502/cloud-kd && cd cloud-kd
make up          # venv, cluster, secrets, SeaweedFS, buckets, images, models from the Release, deploy
make down        # delete the cluster
```

`make up` downloads `model-v1` and `model-v2` from the GitHub Release into `s3://models/`
if they are not there yet. The service image never contains weights.

Try it:

```bash
curl -i -X POST localhost:8080/parse -H 'Content-Type: application/json' \
     -d '{"text": "what is the weather in london"}'
```

## Full pipeline

### Task 1: storage and teacher labelling

```bash
make venv cluster secrets storage buckets           # cluster + SeaweedFS + datasets/models buckets
# teacher on the laptop, reachable from pods as host.k3d.internal:
OLLAMA_HOST=0.0.0.0 OLLAMA_NUM_PARALLEL=2 ollama serve &
ollama pull phi3.5
docker build -f worker/Dockerfile -t kd-worker:latest . && k3d image import kd-worker:latest -c kd
make label          # 2 workers, SHARD_INDEX 0 and 1, write s3://datasets/teacher/shard-<i>.jsonl
make label-logs     # progress; a restarted worker resumes from its checkpoint
make clean-data     # -> s3://datasets/v1/train.jsonl + train.sha256, data/v1/, results/clean_counts.json
make export-shards  # copy the raw shards to results/teacher/ so clean.py can be re-run offline
python worker/clean.py --local-dir results/teacher --no-upload   # must reproduce data/v1/train.sha256
```

### Task 2: student

```bash
make train SUBSET=50                          # smoke run
make train                                    # v1 (training/config.yaml), loss -> training/loss.csv
make train CONFIG=training/config_v2.yaml     # v2, one more epoch
make publish-model VERSION=v1                 # s3://models/v1/ + model.sha256, artifacts/release/model-v1.tar.gz
make publish-model VERSION=v2
make bad-model                                # untrained Pythia-70M as artifacts/release/model-bad.tar.gz
make eval                                     # teacher, untrained Pythia, student v1 -> results/*.json
```

Create the GitHub Releases `model-v1`, `model-v2`, `model-bad` and upload
`artifacts/release/model-<v>.tar.gz` and `model-<v>.sha256` to each.

### Task 3: container under limits

```bash
make images
make mem-test       # 50 sequential requests at --cpus 1 --memory 1g -> results/mem_test.txt
docker images kd-parser
```

### Task 4: Kubernetes

```bash
make deploy
make hpa-test        # 1 -> 2 replicas under load and back -> results/hpa_test.txt
make rollout-test    # v1 -> v2 under load, rollout undo -> results/rollout_test.txt
make recovery-test   # delete a pod under load -> results/recovery_test.txt
make cold-start      # 3 runs, median creation -> Ready -> results/cold_start.txt
make lb-test         # two Ready replicas, requests per replica -> results/loadbalance_headers.json
```

### Task 5: network

```bash
python tools/nacl_sim.py network/nacl.json network/packets_sample.jsonl --check
```

### Task 6 / 7: tests, CI, load test

```bash
make lint test
make loadtest        # standard Locust command through the Ingress + kubectl top -> results/loadtest_*
```

CI (`.github/workflows/ci.yml`): lint -> unit tests -> evaluation of the Release asset
-> quality gate (`score.py --min-validity 95`), plus gitleaks. Run it manually with
`model_tag=bad` to see the gate fail.

## Data licence

Commands are from SLURP (Bastianelli et al., EMNLP 2020), CC BY 4.0.
Pythia-70M is Apache 2.0.
