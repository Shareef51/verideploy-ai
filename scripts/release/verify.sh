#!/usr/bin/env bash
set -euo pipefail
NS="${VERIDEPLOY_NAMESPACE:-verideploy}"
kubectl -n "$NS" rollout status deploy/verideploy-web --timeout=10m
kubectl -n "$NS" rollout status deploy/verideploy-gateway --timeout=10m
kubectl -n "$NS" rollout status deploy/verideploy-ai-service --timeout=10m
kubectl -n "$NS" rollout status deploy/verideploy-worker --timeout=10m
kubectl -n "$NS" get svc,pods
kubectl -n "$NS" get externalsecret verideploy-runtime-production
