# Knowledge Distillation and Deployment of a Command Parser on a Local Cloud

Draft of the report (export to `report/report.pdf`, at most 8 pages).
Every `TBD` must be filled from a file in `results/`. Measured values and assumptions are kept separate.

## Architecture

```
 laptop                                   k3d cluster "kd" (single node)
 ------                                   -------------------------------------------------
 Ollama phi3.5  <-- host.k3d.internal --  pipeline: Job teacher-labelling (2 pods, shard 0/1)
                                                  |  write datasets/teacher/shard-i.jsonl
 clean.py, train.py  -- localhost:8333 -->  data: SeaweedFS (S3)  buckets: datasets, models
                                                  ^  download models/vN/ at start-up
 Locust  -- localhost:8080 --> Traefik --> app: Service parser --> Deployment parser (1-2 pods, HPA)
```

## Task 1: Object storage and parallel teacher labelling

**Setup.** Cluster from `cluster/k3d.yaml`; SeaweedFS (`k8s/data/seaweedfs.yaml`) runs master,
volume, filer and S3 gateway in one pod with a 5 GiB local-path volume. Buckets `datasets`
and `models` are created by `scripts/bootstrap_s3.py`. S3 keys are random per machine,
kept in the git-ignored `.env` and given to pods through Secrets.

**Teacher.** phi3.5 in Ollama on the laptop, `temperature 0`, `seed 42`, `format: json`
(constrained decoding; the reply text is stored unedited). Prompt: `prompts/teacher_prompt.txt`.

**Sharding.** The workers are one Kubernetes Indexed Job with `completions: 2` and
`parallelism: 2`. Kubernetes gives each pod a completion index (0, 1), which the manifest
passes in as `SHARD_INDEX`; `SHARD_COUNT` is 2. A worker keeps the commands whose line
number `n` (from 0) satisfies `n % SHARD_COUNT == SHARD_INDEX`. Because every `n` has exactly
one remainder, every command lands in exactly one shard, with no coordination between the
workers and no shared state; each worker writes only its own object
(`datasets/teacher/shard-<i>.jsonl`), so there are no write conflicts. Modulo instead of
contiguous blocks keeps the shards the same size and mixes easy and hard commands. Labelling
on a CPU takes hours, so each worker re-uploads its object every 25 records and skips ids
already present when it restarts; a pod failure therefore costs at most 25 teacher calls.
The bottleneck is the single Ollama instance, so more than two workers would not help much.

**Cleaning counts** (`results/clean_counts.json`):

| input | (a) invalid JSON | (b) wrong keys | (c) bad intent | (d) bad slot | duplicates | kept |
|---|---|---|---|---|---|---|
| 3000 | 0 | 2 | 12 | 169 | 47 | 2770 |

Checks run in the order (a) to (d); duplicates are counted among records that passed (a)-(d),
keeping the smallest id. `train.sha256`: `df78cd9a3131674eda3ee25319548902dca552510d5d7b6a7a46dda9b77318b4`
(re-running `clean.py` offline on `results/teacher/` gives the same hash). Both workers finished
1,500 records each in 116 minutes (about 0.22 replies/s per worker).

## Task 2: Training the student

Pythia-70M, full fine-tuning on CPU, first 1,500 records of `train.jsonl`. Example format
`Command: <text>\nJSON: <teacher JSON>` + EOS; loss only on the JSON tokens. Hyper-parameters
and library versions in `training/config.yaml`. v2 = one more epoch (`training/config_v2.yaml`).

Loss per epoch (`training/loss.csv`): 0.685, 0.404, 0.197, 0.128, 0.088, 0.059, 0.039, 0.022,
0.010, 0.003 (about 135 s per epoch on CPU). v2 (`training/loss_v2.csv`) ends at 0.0015 after 11 epochs.

Validation set, 100 commands (`results/*_validation.json`, scored with `tools/score.py`), all in %:

| model | json_validity | intent | date | time | place | full_frame |
|---|---|---|---|---|---|---|
| teacher phi3.5 | 99 | 86 | 76 | 84 | 91 | 50 |
| Pythia-70M untrained | 0 | 0 | 0 | 0 | 0 | 0 |
| student v1 | 98 | 82 | 79 | 85 | 84 | 44 |

Release asset `model-v1.tar.gz` SHA-256 = `models/v1/model.sha256` =
`2745c105d4355c022fdd29ac7ddc006e1502126761b33da88eb29c713031e4c4`
(v2: `cb3fb317a022883d27f2299537e25d0ee482350deccd3b9d09a0680ccb87891f`).

**Sequence-level vs logit-based distillation.**
(a) Sequence-level distillation trains the student with ordinary cross-entropy on the
*text the teacher generated*: the teacher's decoded output is used as the target sequence,
exactly like a human label (Kim and Rush, 2016).
(b) Logit-based (token-level) distillation trains the student to match the teacher's full
*probability distribution over the vocabulary at every position*, usually with a KL-divergence
loss on temperature-softened logits, so the student also learns which wrong tokens the teacher
found plausible.
(c) It is not possible here because the teacher and student do not share a tokenizer or
vocabulary (Phi-3.5 uses a 32k Llama-style vocabulary, Pythia a 50k GPT-NeoX one), so their
distributions are over different token sets and cannot be compared position by position; in
addition, Ollama only returns the generated text, not per-token logits over the vocabulary.
(d) Limitation: the student only ever sees the teacher's single greedy answer, including its
mistakes. Wherever phi3.5 is wrong (for example labelling a "remind me" request inconsistently,
or copying a longer phrase than the slot rules allow) the student learns the error as truth, and
the cleaning step only removes structurally invalid replies, not semantically wrong ones. The
student's accuracy is therefore capped by the teacher's: full-frame 44% for the student against
50% for phi3.5 on the same 100 commands.

## Task 3: Inference service

FastAPI (`service/app.py`), endpoints `/parse`, `/healthz`, `/readyz`; headers
`X-Model-Version` and `X-Served-By`; every output validated against `data/schema.json`
(500 `{"error": "invalid_model_output"}` otherwise; `FAULT_INJECT=1` forces it).
Image: `python:3.13.1-slim` + CPU-only PyTorch, all versions pinned, no weights. Size: TBD.
50 sequential requests at 1 CPU / 1 GiB: TBD OK, peak memory TBD (`results/mem_test.txt`).

## Task 4: Kubernetes deployment, scaling and reliability

Requests 500m / 512Mi, limits 1 CPU / 1 GiB; readiness `/readyz`, liveness `/healthz`;
`maxUnavailable 0`, `maxSurge 1`, `preStop sleep 5`. HPA 1-2 replicas at 70% CPU of the request.

| test | result | evidence |
|---|---|---|
| HPA 1 -> 2 -> 1 | TBD | `results/hpa_test.txt` |
| rolling update v1 -> v2, failures | TBD % | `results/rollout_stats.csv` |
| X-Model-Version after undo | TBD | `results/rollout_test.txt` |
| recovery: replicas restored, failures | TBD | `results/recovery_test.txt` |
| cold start (3 runs), median | TBD s | `results/cold_start.txt` |
| load balancing per replica | TBD / TBD | `results/loadbalance_headers.json` |

**Limitations.** One laptop, one k3s node: replicas share one CPU and one failure domain, so
this shows recovery from a pod failure, not fault tolerance across machines. metrics-server
samples every ~15 s and the HPA acts on that, so short bursts are missed; both replicas also
compete for the same physical cores, so a second replica adds less capacity than on two machines.

## Task 5: Subnetting and NACL

See `network/subnets.md` (table, working and explanation). `nacl_sim.py --check` on the
sample packets: 6/6.

## Task 6: Reproducibility and CI/CD

`make up` from a fresh clone (clone, cd, make up). CI stages: lint, unit tests, evaluation
of the Release asset, quality gate; gitleaks. Passing run with `model-v1`:
https://github.com/pardhu1502/cloud-kd/actions/runs/42490095335. Failed gate run with the
untrained model (`model_tag=bad`, JSON validity 0% < 95%):
https://github.com/pardhu1502/cloud-kd/actions/runs/42490284576.

## Task 7: Performance, cost and review

**Measured** (standard Locust run, `results/loadtest_*`): p50 TBD ms, p95 TBD ms,
throughput TBD req/s, error rate TBD %, per-pod CPU/memory TBD (`results/loadtest_top.txt`),
cold start TBD s.

**Cost** (rate card: 3.50 INR per vCPU-hour, 0.45 INR per GiB-hour; billed on limits):

- one replica = 1 vCPU x 3.50 + 1 GiB x 0.45 = 3.95 INR/hour
- running replicas during the test = TBD (n), so hourly cost = n x 3.95 = TBD INR/hour
- requests served per hour = throughput x 3,600 = TBD
- cost per 1,000 requests = hourly cost / requests per hour x 1,000 = TBD INR

**SLO.** 99% of `/parse` requests return HTTP 200 within 30 s, measured over one standard
load-test run (2 minutes). Error budget = 1% of the requests in that run = TBD requests;
used TBD failed requests = TBD % of the budget.

| Component | Evidence (measured) | Limitation | Improvement |
|---|---|---|---|
| Data and storage | 2,770 of 3,000 replies kept | single SeaweedFS pod, no replication | replicated volumes / erasure coding |
| Model quality | full-frame 44 % vs teacher 50 % | 70M model, teacher errors copied | larger student or logit KD with a shared tokenizer |
| Latency and throughput | p95 TBD ms at TBD req/s | one request at a time per pod, CPU only | batching, quantised model, ONNX Runtime |
| Resource utilisation | TBD m CPU, TBD Mi per pod | CPU-bound, memory mostly idle | lower memory limit, more CPU per pod |
| Reliability and recovery | cold start TBD s, TBD % errors on pod loss | single node | multi-node cluster, PodDisruptionBudget |
| Security and cost | TBD INR / 1,000 requests | plain HTTP, one S3 identity for everything | TLS on the Ingress, per-namespace read-only keys |

## References

Kim and Rush (2016); Chen et al. (2020); Bastianelli et al. (2020); Pythia-70M model card; k3d, SeaweedFS, Kubernetes documentation.
