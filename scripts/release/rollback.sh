#!/usr/bin/env bash
set -euo pipefail
REVISION="${1:-}"
if [[ -z "$REVISION" ]]; then echo "usage: $0 <helm-revision>" >&2; exit 2; fi
if [[ "${VERIDEPLOY_ROLLBACK_APPROVED:-}" != "yes" ]]; then
  echo "Refusing rollback: set VERIDEPLOY_ROLLBACK_APPROVED=yes after human approval." >&2; exit 2
fi
helm -n "${VERIDEPLOY_NAMESPACE:-verideploy}" rollback verideploy "$REVISION" --wait --timeout 15m
"$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/verify.sh"
