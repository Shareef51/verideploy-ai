from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from verideploy.config import get_settings

from .core import CachePolicy, MemoryCacheBackend, MultiLayerCache
from .redis_backend import RedisCacheBackend


@lru_cache(maxsize=1)
def load_cache_policy(path: str = "config/cache/policy.json") -> CachePolicy:
    return CachePolicy.from_mapping(json.loads(Path(path).read_text(encoding="utf-8")))


def build_cache() -> MultiLayerCache:
    settings = get_settings()
    backend = RedisCacheBackend(settings.redis_url) if settings.cache_backend == "redis" else MemoryCacheBackend()
    secret = (
        settings.cache_encryption_secret.get_secret_value()
        if settings.cache_encryption_secret
        else settings.app_secret_key.get_secret_value()
    )
    return MultiLayerCache(backend, load_cache_policy(settings.cache_policy_path), encryption_secret=secret)
