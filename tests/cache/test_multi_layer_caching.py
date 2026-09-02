from __future__ import annotations

import asyncio

import pytest

import verideploy.cache.core as cache_core
from verideploy.cache import CacheContext, CacheLayer, CachePolicy, MemoryCacheBackend, MultiLayerCache


SECRET = "cache-encryption-secret-32-bytes-minimum"


def policy(*, ttl: int = 60, stale: int = 60) -> CachePolicy:
    raw = {
        "version": "test-v1",
        "key_version": "v1",
        "lock_ttl_seconds": 2,
        "lock_wait_seconds": 1.0,
        "layers": {
            layer.value: {
                "ttl_seconds": ttl,
                "stale_seconds": 0 if layer in {CacheLayer.PERMISSION, CacheLayer.SESSION} else stale,
                "encrypt": layer in {CacheLayer.MODEL_OUTPUT, CacheLayer.PERMISSION, CacheLayer.SESSION},
                "model_safe_only": layer is CacheLayer.MODEL_OUTPUT,
            }
            for layer in CacheLayer
        },
    }
    return CachePolicy.from_mapping(raw)


@pytest.mark.asyncio
async def test_cache_keys_and_values_are_tenant_and_scope_isolated() -> None:
    backend = MemoryCacheBackend()
    cache = MultiLayerCache(backend, policy(), encryption_secret=SECRET)
    a = CacheContext("tenant-a", "test", "retrieval", "role:viewer")
    b = CacheContext("tenant-b", "test", "retrieval", "role:viewer")
    narrow = CacheContext("tenant-a", "test", "retrieval", "role:viewer|team:payments")
    await cache.set(CacheLayer.RETRIEVAL, a, "same-query", {"docs": ["a"]})
    assert (await cache.get(CacheLayer.RETRIEVAL, a, "same-query")).value == {"docs": ["a"]}
    assert (await cache.get(CacheLayer.RETRIEVAL, b, "same-query")).status == "miss"
    assert (await cache.get(CacheLayer.RETRIEVAL, narrow, "same-query")).status == "miss"
    assert cache.cache_key(CacheLayer.RETRIEVAL, a, "same-query") != cache.cache_key(CacheLayer.RETRIEVAL, b, "same-query")


@pytest.mark.asyncio
async def test_sensitive_layers_encrypt_and_model_outputs_require_safe_marker() -> None:
    backend = MemoryCacheBackend()
    cache = MultiLayerCache(backend, policy(), encryption_secret=SECRET)
    ctx = CacheContext("tenant-a", "test", "session", "user:42")
    with pytest.raises(ValueError, match="marked safe"):
        await cache.set(CacheLayer.MODEL_OUTPUT, ctx, "answer", {"text": "ok"})
    await cache.set(CacheLayer.SESSION, ctx, "session-1", {"token": "secret-visible-only-after-decrypt"})
    raw = await backend.get(cache.cache_key(CacheLayer.SESSION, ctx, "session-1"))
    assert raw is not None and raw.startswith(b"gcm1:")
    assert b"secret-visible-only-after-decrypt" not in raw
    assert (await cache.get(CacheLayer.SESSION, ctx, "session-1")).value["token"] == "secret-visible-only-after-decrypt"


@pytest.mark.asyncio
async def test_tag_invalidation_is_tenant_scoped() -> None:
    backend = MemoryCacheBackend()
    cache = MultiLayerCache(backend, policy(), encryption_secret=SECRET)
    a = CacheContext("tenant-a", "test", "github")
    b = CacheContext("tenant-b", "test", "github")
    await cache.set(CacheLayer.INTEGRATION, a, "repo", {"sha": "a"}, tags=("repo:checkout",))
    await cache.set(CacheLayer.INTEGRATION, b, "repo", {"sha": "b"}, tags=("repo:checkout",))
    assert await cache.invalidate(CacheLayer.INTEGRATION, a, tag="repo:checkout") == 1
    assert (await cache.get(CacheLayer.INTEGRATION, a, "repo")).status == "miss"
    assert (await cache.get(CacheLayer.INTEGRATION, b, "repo")).value == {"sha": "b"}


@pytest.mark.asyncio
async def test_concurrent_misses_are_coalesced_to_one_loader_call() -> None:
    backend = MemoryCacheBackend()
    cache = MultiLayerCache(backend, policy(), encryption_secret=SECRET)
    ctx = CacheContext("tenant-a", "test", "retrieval", "scope")
    calls = 0

    async def loader() -> dict[str, int]:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.04)
        return {"origin_calls": calls}

    results = await asyncio.gather(
        *(cache.get_or_load(CacheLayer.RETRIEVAL, ctx, "q", loader) for _ in range(25))
    )
    assert calls == 1
    assert all(result.value == {"origin_calls": 1} for result in results)
    assert {result.status for result in results} <= {"loaded", "coalesced", "fresh"}


@pytest.mark.asyncio
async def test_stale_value_is_served_during_lock_and_on_loader_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = MemoryCacheBackend()
    cache = MultiLayerCache(backend, policy(ttl=10, stale=30), encryption_secret=SECRET)
    ctx = CacheContext("tenant-a", "test", "integration")
    fake_now = 1_000.0
    monkeypatch.setattr(cache_core.time, "time", lambda: fake_now)
    await cache.set(CacheLayer.INTEGRATION, ctx, "github:pr", {"sha": "old"})
    fake_now = 1_015.0
    stale = await cache.get(CacheLayer.INTEGRATION, ctx, "github:pr")
    assert stale.status == "stale"

    lock_key = cache.cache_key(CacheLayer.INTEGRATION, ctx, "github:pr") + ":lock"
    assert await backend.acquire_lock(lock_key, "other-worker", 2)
    reused = await cache.get_or_load(
        CacheLayer.INTEGRATION,
        ctx,
        "github:pr",
        lambda: asyncio.sleep(0, result={"sha": "new"}),
    )
    assert reused.status == "stale"
    await backend.release_lock(lock_key, "other-worker")

    async def failing_loader() -> dict[str, str]:
        raise RuntimeError("origin unavailable")

    fallback = await cache.get_or_load(CacheLayer.INTEGRATION, ctx, "github:pr", failing_loader)
    assert fallback.status == "stale_fallback"
    assert fallback.value == {"sha": "old"}
