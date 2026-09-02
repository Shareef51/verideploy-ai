from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, TypeVar

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

T = TypeVar("T")


class CacheLayer(StrEnum):
    INTEGRATION = "integration"
    RETRIEVAL = "retrieval"
    MODEL_OUTPUT = "model_output"
    PERMISSION = "permission"
    SESSION = "session"


@dataclass(frozen=True)
class LayerPolicy:
    ttl_seconds: int
    stale_seconds: int
    encrypt: bool
    model_safe_only: bool = False


@dataclass(frozen=True)
class CachePolicy:
    version: str
    key_version: str
    lock_ttl_seconds: int
    lock_wait_seconds: float
    layers: Mapping[CacheLayer, LayerPolicy]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "CachePolicy":
        layers = {
            CacheLayer(name): LayerPolicy(
                ttl_seconds=int(cfg["ttl_seconds"]),
                stale_seconds=int(cfg["stale_seconds"]),
                encrypt=bool(cfg["encrypt"]),
                model_safe_only=bool(cfg.get("model_safe_only", False)),
            )
            for name, cfg in raw["layers"].items()
        }
        return cls(
            version=str(raw["version"]),
            key_version=str(raw.get("key_version", "v1")),
            lock_ttl_seconds=int(raw.get("lock_ttl_seconds", 15)),
            lock_wait_seconds=float(raw.get("lock_wait_seconds", 2.0)),
            layers=layers,
        )


@dataclass(frozen=True)
class CacheContext:
    tenant_id: str
    environment: str
    namespace: str
    scope_fingerprint: str = "global"


@dataclass(frozen=True)
class CacheResult:
    value: Any | None
    status: str
    age_seconds: float | None = None


@dataclass(frozen=True)
class CacheEntry:
    value: Any
    created_at: float
    fresh_until: float
    stale_until: float
    tags: tuple[str, ...]
    encrypted: bool


class CacheBackend(Protocol):
    async def get(self, key: str) -> bytes | None: ...
    async def set(self, key: str, value: bytes, ttl_seconds: int) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def acquire_lock(self, key: str, token: str, ttl_seconds: int) -> bool: ...
    async def release_lock(self, key: str, token: str) -> None: ...
    async def add_tag_member(self, tag_key: str, cache_key: str, ttl_seconds: int) -> None: ...
    async def tag_members(self, tag_key: str) -> set[str]: ...
    async def delete_tag(self, tag_key: str) -> None: ...


class MemoryCacheBackend:
    """Deterministic backend for tests and local execution; semantics mirror Redis TTL/locks."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[bytes, float]] = {}
        self._locks: dict[str, tuple[str, float]] = {}
        self._tags: dict[str, tuple[set[str], float]] = {}
        self._mutex = asyncio.Lock()

    async def get(self, key: str) -> bytes | None:
        async with self._mutex:
            item = self._data.get(key)
            if item is None:
                return None
            value, expires = item
            if expires <= time.monotonic():
                self._data.pop(key, None)
                return None
            return value

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> None:
        async with self._mutex:
            self._data[key] = (value, time.monotonic() + ttl_seconds)

    async def delete(self, key: str) -> None:
        async with self._mutex:
            self._data.pop(key, None)

    async def acquire_lock(self, key: str, token: str, ttl_seconds: int) -> bool:
        async with self._mutex:
            now = time.monotonic()
            current = self._locks.get(key)
            if current and current[1] > now:
                return False
            self._locks[key] = (token, now + ttl_seconds)
            return True

    async def release_lock(self, key: str, token: str) -> None:
        async with self._mutex:
            current = self._locks.get(key)
            if current and current[0] == token:
                self._locks.pop(key, None)

    async def add_tag_member(self, tag_key: str, cache_key: str, ttl_seconds: int) -> None:
        async with self._mutex:
            members, _ = self._tags.get(tag_key, (set(), 0.0))
            members.add(cache_key)
            self._tags[tag_key] = (members, time.monotonic() + ttl_seconds)

    async def tag_members(self, tag_key: str) -> set[str]:
        async with self._mutex:
            item = self._tags.get(tag_key)
            if item is None:
                return set()
            members, expires = item
            if expires <= time.monotonic():
                self._tags.pop(tag_key, None)
                return set()
            return set(members)

    async def delete_tag(self, tag_key: str) -> None:
        async with self._mutex:
            self._tags.pop(tag_key, None)


class CacheCipher:
    """AES-256-GCM envelope encryption with tenant/layer AAD binding."""

    def __init__(self, secret: str) -> None:
        if len(secret.encode()) < 32:
            raise ValueError("cache encryption secret must be at least 32 bytes")
        self._master = hashlib.sha256(secret.encode()).digest()

    def _key(self, tenant_id: str) -> bytes:
        return hashlib.sha256(self._master + tenant_id.encode()).digest()

    def encrypt(self, plaintext: bytes, *, aad: bytes, tenant_id: str) -> bytes:
        nonce = os.urandom(12)
        ciphertext = AESGCM(self._key(tenant_id)).encrypt(nonce, plaintext, aad)
        return b"gcm1:" + base64.urlsafe_b64encode(nonce + ciphertext)

    def decrypt(self, envelope: bytes, *, aad: bytes, tenant_id: str) -> bytes:
        if not envelope.startswith(b"gcm1:"):
            raise ValueError("unsupported cache encryption envelope")
        raw = base64.urlsafe_b64decode(envelope[5:])
        return AESGCM(self._key(tenant_id)).decrypt(raw[:12], raw[12:], aad)


class MultiLayerCache:
    def __init__(self, backend: CacheBackend, policy: CachePolicy, *, encryption_secret: str | None = None) -> None:
        self._backend = backend
        self._policy = policy
        self._cipher = CacheCipher(encryption_secret) if encryption_secret else None

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()[:24]

    def cache_key(self, layer: CacheLayer, ctx: CacheContext, logical_key: str) -> str:
        return ":".join(
            (
                "vd",
                "cache",
                self._policy.key_version,
                ctx.environment,
                layer.value,
                self._digest(ctx.tenant_id),
                self._digest(ctx.namespace),
                self._digest(ctx.scope_fingerprint),
                self._digest(logical_key),
            )
        )

    def _tag_key(self, layer: CacheLayer, ctx: CacheContext, tag: str) -> str:
        return f"vd:cache-tag:{self._policy.key_version}:{ctx.environment}:{layer.value}:{self._digest(ctx.tenant_id)}:{self._digest(tag)}"

    def _aad(self, layer: CacheLayer, ctx: CacheContext) -> bytes:
        return f"{self._policy.version}|{layer.value}|{ctx.environment}|{ctx.tenant_id}|{ctx.scope_fingerprint}".encode()

    def _serialize(self, entry: CacheEntry, layer: CacheLayer, ctx: CacheContext) -> bytes:
        raw = json.dumps(
            {
                "value": entry.value,
                "created_at": entry.created_at,
                "fresh_until": entry.fresh_until,
                "stale_until": entry.stale_until,
                "tags": list(entry.tags),
                "encrypted": entry.encrypted,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        if entry.encrypted:
            if self._cipher is None:
                raise RuntimeError("cache encryption policy requires CACHE_ENCRYPTION_SECRET")
            return self._cipher.encrypt(raw, aad=self._aad(layer, ctx), tenant_id=ctx.tenant_id)
        return raw

    def _deserialize(self, payload: bytes, layer: CacheLayer, ctx: CacheContext) -> CacheEntry:
        encrypted = payload.startswith(b"gcm1:")
        if encrypted:
            if self._cipher is None:
                raise RuntimeError("encrypted cache value cannot be read without cache cipher")
            payload = self._cipher.decrypt(payload, aad=self._aad(layer, ctx), tenant_id=ctx.tenant_id)
        raw = json.loads(payload)
        return CacheEntry(
            value=raw["value"],
            created_at=float(raw["created_at"]),
            fresh_until=float(raw["fresh_until"]),
            stale_until=float(raw["stale_until"]),
            tags=tuple(raw.get("tags", [])),
            encrypted=bool(raw.get("encrypted", encrypted)),
        )

    async def get(self, layer: CacheLayer, ctx: CacheContext, logical_key: str) -> CacheResult:
        payload = await self._backend.get(self.cache_key(layer, ctx, logical_key))
        if payload is None:
            return CacheResult(None, "miss")
        entry = self._deserialize(payload, layer, ctx)
        now = time.time()
        age = max(0.0, now - entry.created_at)
        if now <= entry.fresh_until:
            return CacheResult(entry.value, "fresh", age)
        if now <= entry.stale_until:
            return CacheResult(entry.value, "stale", age)
        await self._backend.delete(self.cache_key(layer, ctx, logical_key))
        return CacheResult(None, "expired", age)

    async def set(
        self,
        layer: CacheLayer,
        ctx: CacheContext,
        logical_key: str,
        value: Any,
        *,
        tags: tuple[str, ...] = (),
        model_safe: bool = False,
    ) -> None:
        layer_policy = self._policy.layers[layer]
        if layer_policy.model_safe_only and not model_safe:
            raise ValueError("model output must be explicitly marked safe before caching")
        if layer_policy.encrypt and self._cipher is None:
            raise RuntimeError("cache layer requires encryption but CACHE_ENCRYPTION_SECRET is unavailable")
        now = time.time()
        entry = CacheEntry(
            value=value,
            created_at=now,
            fresh_until=now + layer_policy.ttl_seconds,
            stale_until=now + layer_policy.ttl_seconds + layer_policy.stale_seconds,
            tags=tags,
            encrypted=layer_policy.encrypt,
        )
        ttl = layer_policy.ttl_seconds + layer_policy.stale_seconds + 1
        cache_key = self.cache_key(layer, ctx, logical_key)
        await self._backend.set(cache_key, self._serialize(entry, layer, ctx), ttl)
        for tag in tags:
            await self._backend.add_tag_member(self._tag_key(layer, ctx, tag), cache_key, ttl)

    async def invalidate(self, layer: CacheLayer, ctx: CacheContext, *, tag: str) -> int:
        tag_key = self._tag_key(layer, ctx, tag)
        members = await self._backend.tag_members(tag_key)
        for member in members:
            await self._backend.delete(member)
        await self._backend.delete_tag(tag_key)
        return len(members)

    async def get_or_load(
        self,
        layer: CacheLayer,
        ctx: CacheContext,
        logical_key: str,
        loader: Callable[[], Awaitable[T]],
        *,
        tags: tuple[str, ...] = (),
        model_safe: bool = False,
    ) -> CacheResult:
        current = await self.get(layer, ctx, logical_key)
        if current.status == "fresh":
            return current

        cache_key = self.cache_key(layer, ctx, logical_key)
        lock_key = f"{cache_key}:lock"
        token = os.urandom(16).hex()
        locked = await self._backend.acquire_lock(lock_key, token, self._policy.lock_ttl_seconds)
        if not locked:
            if current.status == "stale":
                return current
            deadline = time.monotonic() + self._policy.lock_wait_seconds
            while time.monotonic() < deadline:
                await asyncio.sleep(0.01)
                candidate = await self.get(layer, ctx, logical_key)
                if candidate.status in {"fresh", "stale"}:
                    return CacheResult(candidate.value, "coalesced", candidate.age_seconds)
            raise TimeoutError("cache stampede lock wait exceeded")

        try:
            # Recheck after acquiring lock because another worker may have just populated it.
            recheck = await self.get(layer, ctx, logical_key)
            if recheck.status == "fresh":
                return recheck
            value = await loader()
            await self.set(layer, ctx, logical_key, value, tags=tags, model_safe=model_safe)
            return CacheResult(value, "loaded", 0.0)
        except Exception:
            if current.status == "stale":
                return CacheResult(current.value, "stale_fallback", current.age_seconds)
            raise
        finally:
            await self._backend.release_lock(lock_key, token)
