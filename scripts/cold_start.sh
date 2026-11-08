#!/usr/bin/env bash
# Cold start: delete all parser pods, wait until the replacements are Ready, and
# measure creation -> Ready for each new pod. Three runs, then the median.
# Output: results/cold_start.txt and results/cold_start_logs_run<N>.txt
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p results
out=results/cold_start.txt
: > "$out"
times=()

to_epoch() { python -c "import sys,datetime;print(datetime.datetime.fromisoformat(sys.argv[1].replace('Z','+00:00')).timestamp())" "$1"; }

for run in 1 2 3; do
  echo "run $run: deleting pods" | tee -a "$out"
  kubectl -n app delete pod -l app=parser --wait=true >/dev/null
  sleep 2
  kubectl -n app wait --for=condition=Ready pod -l app=parser --timeout=300s >/dev/null
  for pod in $(kubectl -n app get pod -l app=parser -o jsonpath='{.items[*].metadata.name}'); do
    created=$(kubectl -n app get pod "$pod" -o jsonpath='{.metadata.creationTimestamp}')
    ready=$(kubectl -n app get pod "$pod" -o jsonpath='{.status.conditions[?(@.type=="Ready")].lastTransitionTime}')
    secs=$(python -c "print(round($(to_epoch "$ready") - $(to_epoch "$created")))")
    echo "  $pod created $created ready $ready -> ${secs}s" | tee -a "$out"
    times+=("$secs")
    kubectl -n app logs "$pod" > "results/cold_start_logs_run${run}_${pod}.txt"
    grep -h "downloaded model" "results/cold_start_logs_run${run}_${pod}.txt" | sed 's/^/    /' | tee -a "$out"
  done
done

python - "${times[@]}" <<'EOF' | tee -a "$out"
import statistics, sys
t = [float(x) for x in sys.argv[1:]]
print(f"all times (s): {t}")
print(f"median creation -> Ready: {statistics.median(t)} s")
EOF
