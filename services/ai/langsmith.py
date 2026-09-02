from __future__ import annotations

from functools import lru_cache

from verideploy.config import get_settings
from verideploy.langsmith_integration import LangSmithDatasetHook, build_langsmith_observer


@lru_cache
def get_langsmith_observer():
    return build_langsmith_observer(get_settings())


@lru_cache
def get_langsmith_dataset_hook() -> LangSmithDatasetHook:
    settings = get_settings()
    observer = get_langsmith_observer()
    client = getattr(observer, "client", None)
    return LangSmithDatasetHook(
        client=client,
        enabled=settings.langsmith_dataset_export_enabled,
        environment=settings.app_env,
        dataset_prefix=settings.langsmith_dataset_prefix,
    )
