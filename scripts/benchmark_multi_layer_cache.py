from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from verideploy.cache import CacheContext, CacheLayer, MemoryCacheBackend, MultiLayerCache, load_cache_policy


async def run() -> dict[str, object]:
    backend = MemoryCacheBackend()
    cache = MultiLayerCache(
        backend,
        load_cache_policy(),
        encryption_secret="ci-cache-encryption-secret-32-bytes-minimum",
    )
    a = CacheContext("tenant-a", "ci", "retrieval", "viewer")
    b = CacheContext("tenant-b", "ci", "retrieval", "viewer")
    calls = 0

    async def loader() -> dict[str, str]:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.02)
        return {"evidence": "synthetic"}

    results = await asyncio.gather(
        *(cache.get_or_load(CacheLayer.RETRIEVAL, a, "incident-query", loader, tags=("incident:64",)) for _ in range(40))
    )
    isolated = (await cache.get(CacheLayer.RETRIEVAL, b, "incident-query")).status == "miss"
    invalidated = await cache.invalidate(CacheLayer.RETRIEVAL, a, tag="incident:64")

    session = CacheContext("tenant-a", "ci", "session", "user:")
    await cache.set(CacheLayer.SESSION, session, "session", {"access": "sensitive-marker"})
    raw = await backend.get(cache.cache_key(CacheLayer.SESSION, session, "session"))
    encrypted = bool(raw and raw.startswith(b"gcm1:") and b"sensitive-marker" not in raw)

    gate = calls == 1 and isolated and invalidated == 1 and encrypted and len(results) == 40
    return {
        "gate": "PASS" if gate else "FAIL",
        "concurrent_callers": len(results),
        "origin_loader_calls": calls,
        "stampede_coalesced": calls == 1,
        "tenant_isolation": isolated,
        "tag_invalidation_count": invalidated,
        "sensitive_layer_encrypted": encrypted,
        "layers": [layer.value for layer in CacheLayer],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default="evals/reports/multi-layer-cache.json")
    args = parser.parse_args()
    report = asyncio.run(run())
    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["gate"] == "PASS" else 1)


if __name__ == "__main__":
    main()
