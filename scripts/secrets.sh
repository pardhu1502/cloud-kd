#!/usr/bin/env bash
# Create (once) random S3 keys in the git-ignored .env file, then put them in
# Kubernetes Secrets. Nothing secret is ever written to the repository.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  python - <<'EOF' > .env
import secrets
print(f"AWS_ACCESS_KEY_ID=kd{secrets.token_hex(8)}")
print(f"AWS_SECRET_ACCESS_KEY={secrets.token_urlsafe(32)}")
EOF
  echo "wrote new keys to .env"
fi
set -a; . ./.env; set +a

for ns in data pipeline app; do
  kubectl create namespace "$ns" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
done

s3_config=$(printf '{"identities":[{"name":"admin","credentials":[{"accessKey":"%s","secretKey":"%s"}],"actions":["Admin","Read","Write","List","Tagging"]}]}' \
  "$AWS_ACCESS_KEY_ID" "$AWS_SECRET_ACCESS_KEY")
kubectl -n data create secret generic seaweedfs-s3-config --from-literal=s3.json="$s3_config" \
  --dry-run=client -o yaml | kubectl apply -f -

for ns in pipeline app; do
  kubectl -n "$ns" create secret generic s3-credentials \
    --from-literal=AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
    --from-literal=AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
    --dry-run=client -o yaml | kubectl apply -f -
done
