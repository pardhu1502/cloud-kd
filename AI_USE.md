# AI use

## Tools

- **Claude Code** (Anthropic, Claude Opus model), used in the terminal.

## What it was used for

- Reading the assignment handout and turning the seven tasks into a repository layout.
- First drafts of the code: the labelling worker and `clean.py`, the training loop,
  the FastAPI service, the Dockerfiles, the Kubernetes manifests, the Makefile, the
  experiment scripts and the GitHub Actions workflow.
- First drafts of the subnet table, the NACL and the explanations in `network/subnets.md`.

## How the output was checked

- **Unit tests** (`make test`): cleaning rules (a)-(e) and the count invariant, shard
  coverage (every line in exactly one shard), the service endpoints, headers,
  `FAULT_INJECT` and schema validation (with a stubbed model), the subnet plan and the NACL.
- **Kit tools**: `nacl_sim.py --check` on the sample packets (6/6) and `score.py` on all predictions.
- **Subnets** recomputed by hand and again with Python's `ipaddress` in `tests/test_network.py`.
- **Smoke runs**: training, saving, prediction and scoring were run end to end on a tiny
  dataset before the real run; the release archive was rebuilt twice to confirm the
  SHA-256 does not change.
- A wrong assumption caught by the tests: an outbound packet to port 8000 on a non-app host
  is allowed by the reply rule (8000 is inside the ephemeral range), which is how a
  stateless NACL behaves, so the test was corrected rather than the rule.
- All numbers in the report come from files in `results/`; none were written by the AI.

<!-- update this file with anything else you used AI for, and how you checked it -->
