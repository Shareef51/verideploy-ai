#!/usr/bin/env bash
set -euo pipefail
if [[ "${VERIDEPLOY_RELEASE_APPROVED:-}" != "yes" ]]; then
  echo "Refusing production apply: set VERIDEPLOY_RELEASE_APPROVED=yes after human approval." >&2; exit 2
fi
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT/infrastructure/terraform"
terraform apply verideploy-0.86.0.tfplan
"$ROOT/scripts/release/verify.sh"
