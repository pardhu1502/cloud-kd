#!/usr/bin/env bash
# Task 4 experiments. Each one writes its own log to results/.
#   scripts/k8s_tests.sh rollout    v1 -> v2 under load, then rollout undo
#   scripts/k8s_tests.sh recovery   delete one pod under load
#   scripts/k8s_tests.sh hpa        1 -> 2 replicas under load, and back down
#   scripts/k8s_tests.sh lb         standard load test with exactly two Ready replicas
set -uo pipefail
cd "$(dirname "$0")/.."
mkdir -p results
K="kubectl -n app"
PARSE_BODY='{"text":"what is the weather in london"}'

ts() { date -u +%T; }
replicas() { $K get deploy parser -o jsonpath='{.status.readyReplicas}/{.spec.replicas}'; }
pin_two() { $K patch hpa parser -p '{"spec":{"minReplicas":2}}' >/dev/null; $K rollout status deploy/parser --timeout=300s; }
unpin() { $K patch hpa parser -p '{"spec":{"minReplicas":1}}' >/dev/null; }
wait_ready() { # wait until $1 replicas are Ready
  until [ "$($K get deploy parser -o jsonpath='{.status.readyReplicas}')" = "$1" ]; do sleep 2; done
}

rollout() {
  pin_two
  scripts/load.sh rollout 5m > /dev/null & load=$!
  sleep 30
  echo "$(ts) set MODEL_VERSION=v2 MODEL_URI=s3://models/v2/"
  $K set env deploy/parser MODEL_VERSION=v2 MODEL_URI=s3://models/v2/
  $K rollout status deploy/parser --timeout=300s
  curl -s -D - -o /dev/null -X POST localhost:8080/parse -H 'Content-Type: application/json' -d "$PARSE_BODY" | grep -i x-model-version
  sleep 30
  echo "$(ts) rollout undo"
  $K rollout undo deploy/parser
  $K rollout status deploy/parser --timeout=300s
  wait $load
  echo "$(ts) after rollback:"
  curl -s -D - -o /dev/null -X POST localhost:8080/parse -H 'Content-Type: application/json' -d "$PARSE_BODY" | grep -i x-model-version
  $K rollout history deploy/parser
  tail -n 3 results/rollout_stats.csv; cat results/rollout_headers.json
  unpin
}

recovery() {
  pin_two
  scripts/load.sh recovery 3m > /dev/null & load=$!
  sleep 30
  pod=$($K get pod -l app=parser -o jsonpath='{.items[0].metadata.name}')
  echo "$(ts) replicas $(replicas); deleting $pod"
  $K delete pod "$pod" --wait=false
  for _ in $(seq 1 60); do
    echo "$(ts) ready/desired $(replicas)"
    sleep 3
    [ "$(replicas)" = "2/2" ] && [ -z "$($K get pod "$pod" --ignore-not-found -o name)" ] && break
  done
  $K get pods -l app=parser -o wide
  wait $load
  tail -n 3 results/recovery_stats.csv
  unpin
}

hpa() {
  unpin
  echo "$(ts) waiting for the HPA to settle at 1 replica"
  wait_ready 1
  ( while true; do echo "$(ts) $($K get hpa parser --no-headers) ready=$(replicas)"; sleep 10; done ) & watch=$!
  scripts/load.sh hpa 4m > /dev/null
  echo "$(ts) load finished, watching scale-down"
  sleep 240
  kill $watch
  $K describe hpa parser | tail -n 15
}

lb() {
  pin_two
  wait_ready 2
  $K get pods -l app=parser
  scripts/load.sh loadbalance 2m > /dev/null
  cat results/loadbalance_headers.json
  tail -n 3 results/loadbalance_stats.csv
  unpin
}

case "${1:-}" in
  rollout|recovery|hpa|lb) "$1" 2>&1 | tee "results/${1}_test.txt" ;;
  *) echo "usage: $0 rollout|recovery|hpa|lb"; exit 1 ;;
esac
