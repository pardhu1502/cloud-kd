#!/usr/bin/env bash
# Task 3: run the service container with 1 CPU and 1 GiB, send 50 requests one after
# another, and record the peak memory from docker stats.
# Needs the cluster up (SeaweedFS reachable on localhost:8333) and .env present.
# Output: results/mem_test.txt
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
mkdir -p results
out=results/mem_test.txt
name=kd-parser-memtest

docker rm -f "$name" >/dev/null 2>&1 || true
docker run -d --name "$name" --cpus 1 --memory 1g -p 8000:8000 \
  -e MODEL_URI=s3://models/v1/ -e MODEL_VERSION=v1 -e MAX_NEW_TOKENS=64 -e FAULT_INJECT=0 \
  -e S3_ENDPOINT=http://host.docker.internal:8333 \
  -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY \
  kd-parser:latest >/dev/null

echo "waiting for /readyz"
until [ "$(curl -s -o /dev/null -w '%{http_code}' localhost:8000/readyz)" = "200" ]; do sleep 2; done

stats=$(mktemp)
( while docker inspect "$name" >/dev/null 2>&1; do
    docker stats --no-stream --format '{{.MemUsage}}' "$name" >> "$stats" 2>/dev/null || break
  done ) &
sampler=$!

ok=0; fail=0
python -c "import json;[print(json.loads(l)['text']) for l in open('data/validation.jsonl') if l.strip()]" | head -50 > /tmp/kd_texts.txt
while IFS= read -r text; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' \
    -d "$(python -c 'import json,sys;print(json.dumps({"text":sys.argv[1]}))' "$text")" localhost:8000/parse)
  if [ "$code" = "200" ]; then ok=$((ok+1)); else fail=$((fail+1)); fi
done < /tmp/kd_texts.txt

kill "$sampler" 2>/dev/null || true
{
  echo "date: $(date -u +%FT%TZ)"
  echo "limits: --cpus 1 --memory 1g"
  echo "requests: 50 sequential, HTTP 200: $ok, other: $fail"
  echo "OOMKilled: $(docker inspect -f '{{.State.OOMKilled}}' "$name")"
  echo "docker stats samples (MemUsage / limit):"
  sort -u "$stats" | sed 's/^/  /'
  echo "peak: $(python - "$stats" <<'EOF'
import re, sys
units = {'B': 1, 'KiB': 1024, 'MiB': 1024**2, 'GiB': 1024**3}
peak = 0
for line in open(sys.argv[1]):
    m = re.match(r'\s*([\d.]+)(B|KiB|MiB|GiB)', line)
    if m:
        peak = max(peak, float(m.group(1)) * units[m.group(2)])
print(f"{peak / 1024**2:.1f} MiB")
EOF
)"
} | tee "$out"
docker rm -f "$name" >/dev/null
