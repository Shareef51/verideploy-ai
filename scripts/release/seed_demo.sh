#!/usr/bin/env bash
set -euo pipefail
BASE="${VERIDEPLOY_GATEWAY_URL:-http://localhost:4000}"
TENANT="${VERIDEPLOY_TENANT_ID:-synthetic-demo}"
USER="${VERIDEPLOY_USER_ID:-recruiter-demo}"
curl --fail-with-body -sS -X POST "$BASE/api/v1/demos/multimodal-killer/run" \
  -H "content-type: application/json" -H "x-tenant-id: $TENANT" -H "x-user-id: $USER" \
  -H "x-correlation-id: release-demo-seed" -d '{}'
printf '\nSynthetic multimodal demo queued through the public gateway.\n'
