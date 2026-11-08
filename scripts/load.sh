#!/usr/bin/env bash
# Standard load test through the Ingress, plus `kubectl top pods` every 10 s.
#   scripts/load.sh NAME RUNTIME      e.g. scripts/load.sh loadtest 2m
# Writes results/NAME_stats.csv (Locust), results/NAME_headers.json, results/NAME_locust.txt, results/NAME_top.txt
set -uo pipefail
cd "$(dirname "$0")/.."
name=${1:-loadtest}
runtime=${2:-2m}
PY=${PY:-python}
mkdir -p results

( while true; do echo "--- $(date -u +%T)"; kubectl top pods -n app --no-headers 2>&1; sleep 10; done ) > "results/${name}_top.txt" &
top=$!
trap 'kill $top 2>/dev/null' EXIT

LOADTEST_HEADERS_OUT="results/${name}_headers.json" "$PY" -m locust -f tools/locustfile.py --headless \
  --users 4 --spawn-rate 4 --run-time "$runtime" --host http://localhost:8080 --csv "results/${name}" \
  2>&1 | tee "results/${name}_locust.txt"
exit 0  # locust exits 1 when any request failed; the numbers are what matter
