# results

Evidence produced by the make targets. Nothing here is edited by hand.

| File | Made by |
|---|---|
| `teacher/shard-*.jsonl` | `make export-shards` (raw teacher replies) |
| `clean_counts.json` | `make clean-data` |
| `teacher_validation_predictions.jsonl`, `teacher_validation.json` | `make eval-teacher` |
| `pythia_base_validation_predictions.jsonl`, `pythia_base_validation.json` | `make eval-base` |
| `student_v1_validation_predictions.jsonl`, `student_v1_validation.json` | `make eval-student` |
| `mem_test.txt` | `make mem-test` |
| `hpa_test.txt`, `hpa_*` | `make hpa-test` |
| `rollout_test.txt`, `rollout_*` | `make rollout-test` |
| `recovery_test.txt`, `recovery_*` | `make recovery-test` |
| `cold_start.txt`, `cold_start_logs_*` | `make cold-start` |
| `loadbalance_*` | `make lb-test` |
| `loadtest_stats.csv`, `loadtest_headers.json`, `loadtest_locust.txt`, `loadtest_top.txt` | `make loadtest` |
