#!/usr/bin/env bash
set -euo pipefail
ACTION="${1:-status}"
NAMESPACE="${VERIDEPLOY_NAMESPACE:-verideploy}"
RELEASE="${VERIDEPLOY_RELEASE:-verideploy}"
CHART="${VERIDEPLOY_CHART:-infrastructure/helm/verideploy}"
VALUES="${VERIDEPLOY_VALUES:-infrastructure/helm/verideploy/values-production.yaml}"
CANARY_TAG="${VERIDEPLOY_CANARY_TAG:-}"
case "$ACTION" in
  deploy)
    test -n "$CANARY_TAG" || { echo "VERIDEPLOY_CANARY_TAG is required" >&2; exit 2; }
    helm upgrade --install "$RELEASE" "$CHART" -n "$NAMESPACE" --create-namespace -f "$VALUES"       --set canary.enabled=true --set-string canary.gateway.imageTag="$CANARY_TAG" --wait --atomic
    ;;
  promote)
    test -n "$CANARY_TAG" || { echo "VERIDEPLOY_CANARY_TAG is required" >&2; exit 2; }
    helm upgrade "$RELEASE" "$CHART" -n "$NAMESPACE" -f "$VALUES"       --set-string images.gateway.tag="$CANARY_TAG" --set canary.enabled=false --wait --atomic
    ;;
  rollback)
    helm rollback "$RELEASE" 0 -n "$NAMESPACE" --wait
    ;;
  status) helm status "$RELEASE" -n "$NAMESPACE" ;;
  *) echo "usage: $0 {deploy|promote|rollback|status}" >&2; exit 2 ;;
esac
