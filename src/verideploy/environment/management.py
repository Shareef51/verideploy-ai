from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

_SECRET_REF = re.compile(r"^secret://(?P<scheme>[a-z0-9-]+)/(?P<name>[A-Za-z0-9_.:/-]+)(?:#(?P<version>[A-Za-z0-9_.-]+))?$")

@dataclass(frozen=True)
class SecretReference:
    scheme: str
    name: str
    version: str | None = None

    @classmethod
    def parse(cls, value: str) -> "SecretReference":
        match = _SECRET_REF.fullmatch(value.strip())
        if not match:
            raise ValueError("invalid external secret reference")
        return cls(match.group("scheme"), match.group("name"), match.group("version"))

class SecretProvider(Protocol):
    def resolve(self, reference: SecretReference) -> str: ...

class SecretResolver:
    def __init__(self, providers: Mapping[str, SecretProvider], allowed_schemes: set[str]):
        self._providers = dict(providers); self._allowed = set(allowed_schemes)
    def resolve(self, raw: str) -> str:
        ref = SecretReference.parse(raw)
        if ref.scheme not in self._allowed: raise ValueError(f"secret scheme not allowed: {ref.scheme}")
        provider = self._providers.get(ref.scheme)
        if provider is None: raise ValueError(f"secret provider unavailable: {ref.scheme}")
        value = provider.resolve(ref)
        if not value: raise ValueError("external secret resolved to empty value")
        return value

@dataclass(frozen=True)
class EnvironmentPolicy:
    version: str
    environments: tuple[str, ...]
    public_variables: frozenset[str]
    secret_variables: frozenset[str]
    external_secret_schemes: frozenset[str]
    required: Mapping[str, tuple[str, ...]]
    redact_keys: frozenset[str]

    @classmethod
    def load(cls, path: str | Path = "config/environments/manifest.json") -> "EnvironmentPolicy":
        raw=json.loads(Path(path).read_text())
        return cls(raw["version"], tuple(raw["environments"]), frozenset(raw["publicVariables"]), frozenset(raw["secretVariables"]), frozenset(raw["externalSecretSchemes"]), {k:tuple(v) for k,v in raw["required"].items()}, frozenset(k.lower() for k in raw["logging"]["redactKeys"]))

def apply_environment_overlay(base: Mapping[str,str], *, env: str, config_dir: str|Path="config/environments") -> dict[str,str]:
    path=Path(config_dir)/f"{env}.json"
    if not path.exists(): raise ValueError(f"unknown environment overlay: {env}")
    overlay=json.loads(path.read_text())
    return {**dict(base), **{str(k):str(v) for k,v in overlay.items()}}

def validate_environment(values: Mapping[str,str], policy: EnvironmentPolicy, *, env: str) -> list[str]:
    if env not in policy.environments: return [f"unsupported environment: {env}"]
    errors=[]
    for name in policy.required.get(env,()):
        if not str(values.get(name,"")).strip(): errors.append(f"missing required configuration: {name}")
    for name in policy.secret_variables:
        val=str(values.get(name,"")).strip()
        if val.startswith("secret://"):
            try:
                ref=SecretReference.parse(val)
                if ref.scheme not in policy.external_secret_schemes: errors.append(f"unsupported secret provider for {name}: {ref.scheme}")
            except ValueError: errors.append(f"invalid external secret reference: {name}")
        if env in {"staging","production"} and val and not val.startswith("secret://") and name not in {"APP_SECRET_KEY"}:
            errors.append(f"{name} must use an external secret reference in {env}")
    for name in policy.secret_variables:
        if name.startswith("NEXT_PUBLIC_"): errors.append(f"secret variable cannot be public: {name}")
    return errors

def redact_secrets(value: Any, policy: EnvironmentPolicy) -> Any:
    if isinstance(value, dict):
        out={}
        for k,v in value.items():
            key=str(k).lower().replace("-","_")
            sensitive = str(k) in policy.secret_variables or any(token.replace("-","_") in key for token in policy.redact_keys)
            out[k]="[REDACTED]" if sensitive and v not in (None,"") else redact_secrets(v,policy)
        return out
    if isinstance(value,list): return [redact_secrets(v,policy) for v in value]
    if isinstance(value,tuple): return tuple(redact_secrets(v,policy) for v in value)
    return value

class EnvironmentVariableSecretProvider:
    """Test/local adapter. Production deployments should inject a cloud/Kubernetes adapter."""
    def resolve(self, reference: SecretReference) -> str:
        key="VERIDEPLOY_SECRET_"+re.sub(r"[^A-Za-z0-9]","_",reference.name).upper()
        return os.environ.get(key,"")
