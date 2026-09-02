#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT/infrastructure/terraform"
terraform fmt -check -recursive
terraform init
terraform validate
terraform plan -out=verideploy-0.86.0.tfplan
