#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$script_dir/.." && pwd)
secret_file=${K8S_SECRETS_FILE:-"$repo_root/.k8s-secrets"}
output_file=${1:-"$repo_root/k8s/sealed-secret.yaml"}
namespace=${K8S_NAMESPACE:-litellm-pgvector}
secret_name=${K8S_SECRET_NAME:-litellm-pgvector-secrets}

for command_name in kubectl kubeseal; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Required command not found: $command_name" >&2
    exit 1
  fi
done

if [[ ! -f "$secret_file" ]]; then
  echo "Secret input file not found: $secret_file" >&2
  exit 1
fi

for required_key in LITELLM_API_KEY LITELLM_VECTOR_STORE_REGISTRY_API_KEY S3_ACCESS_KEY S3_SECRET_KEY; do
  if ! grep -q "^${required_key}=" "$secret_file"; then
    echo "Missing $required_key in $secret_file" >&2
    exit 1
  fi
done

if grep -Eq '^(LITELLM_API_KEY|LITELLM_VECTOR_STORE_REGISTRY_API_KEY|S3_ACCESS_KEY|S3_SECRET_KEY)=REPLACE_ME' "$secret_file"; then
  echo "Replace the placeholder values in $secret_file before sealing." >&2
  exit 1
fi

output_dir=$(dirname -- "$output_file")
mkdir -p -- "$output_dir"
temp_file=$(mktemp "$output_dir/.sealed-secret.XXXXXX")
trap 'rm -f -- "$temp_file"' EXIT

kubectl create secret generic "$secret_name" \
  --namespace "$namespace" \
  --from-env-file="$secret_file" \
  --dry-run=client \
  --output yaml |
  kubeseal --format yaml --scope strict >"$temp_file"

mv -- "$temp_file" "$output_file"
trap - EXIT
printf 'SealedSecret written to %s\n' "$output_file"
