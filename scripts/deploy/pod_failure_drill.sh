#!/usr/bin/env bash
set -euo pipefail
NAMESPACE="${VERIDEPLOY_NAMESPACE:-verideploy}"
COMPONENT="${1:-gateway}"
MIN_AVAILABLE="${VERIDEPLOY_MIN_AVAILABLE:-2}"
DEPLOYMENT="verideploy-${COMPONENT}"
SELECTOR="app.kubernetes.io/name=verideploy,app.kubernetes.io/component=${COMPONENT},verideploy.ai/track=stable"
POD="$(kubectl -n "$NAMESPACE" get pod -l "$SELECTOR" -o jsonpath='{.items[0].metadata.name}')"
test -n "$POD" || { echo "no stable pod found for ${COMPONENT}" >&2; exit 2; }
echo "Deleting ${POD} to simulate an involuntary pod failure"
kubectl -n "$NAMESPACE" delete pod "$POD" --wait=false
kubectl -n "$NAMESPACE" rollout status deployment/"$DEPLOYMENT" --timeout=180s
AVAILABLE="$(kubectl -n "$NAMESPACE" get deployment "$DEPLOYMENT" -o jsonpath='{.status.availableReplicas}')"
AVAILABLE="${AVAILABLE:-0}"
if (( AVAILABLE < MIN_AVAILABLE )); then
  echo "failure drill breached minimum availability: ${AVAILABLE} < ${MIN_AVAILABLE}" >&2
  exit 1
fi
echo "failure drill passed: ${AVAILABLE} available replicas"
