from __future__ import annotations
from functools import lru_cache
from verideploy.config import get_settings
from verideploy.integrations.factory import EngineeringIntegrations, create_engineering_integrations

@lru_cache
def get_engineering_integrations() -> EngineeringIntegrations:
    return create_engineering_integrations(get_settings())
