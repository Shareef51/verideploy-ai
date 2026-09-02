from dataclasses import dataclass
from verideploy.config import Settings, get_settings

@dataclass(frozen=True)
class RuntimeDependencies:
    settings: Settings

def get_runtime_dependencies() -> RuntimeDependencies:
    return RuntimeDependencies(settings=get_settings())
