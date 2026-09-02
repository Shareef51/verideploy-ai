#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
command -v pnpm >/dev/null
command -v uv >/dev/null
command -v docker >/dev/null
pnpm install --lockfile-only
uv lock --python 3.12
python scripts/release/resolve_base_image_digests.py
PYTHONPATH=. python scripts/validate_supply_chain.py --release --report evals/reports/supply-chain-release.json
