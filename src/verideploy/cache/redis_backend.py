from __future__ import annotations

from typing import Any


class RedisCacheBackend:
    """Redis implementation using atomic SET NX locks and Lua compare-delete unlock."""

    def __init__(self, redis_url: str) -> None:
        try:
            from redis.asyncio import Redis
        except ImportError as exc:  # pragma: no cover - packaging guard
            raise RuntimeError("redis package is required for RedisCacheBackend") from exc
        self._redis: Any = Redis.from_url(redis_url, decode_responses=False)

    async def get(self, key: str) -> bytes | None:
        return await self._redis.get(key)

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> None:
        await self._redis.set(key, value, ex=ttl_seconds)

    async def delete(self, key: str) -> None:
        await self._redis.delete(key)

    async def acquire_lock(self, key: str, token: str, ttl_seconds: int) -> bool:
        return bool(await self._redis.set(key, token.encode(), nx=True, ex=ttl_seconds))

    async def release_lock(self, key: str, token: str) -> None:
        script = """
        if redis.call('GET', KEYS[1]) == ARGV[1] then
          return redis.call('DEL', KEYS[1])
        end
        return 0
        """
        await self._redis.eval(script, 1, key, token.encode())

    async def add_tag_member(self, tag_key: str, cache_key: str, ttl_seconds: int) -> None:
        pipe = self._redis.pipeline(transaction=True)
        pipe.sadd(tag_key, cache_key)
        pipe.expire(tag_key, ttl_seconds)
        await pipe.execute()

    async def tag_members(self, tag_key: str) -> set[str]:
        values = await self._redis.smembers(tag_key)
        return {value.decode() if isinstance(value, bytes) else str(value) for value in values}

    async def delete_tag(self, tag_key: str) -> None:
        await self._redis.delete(tag_key)
