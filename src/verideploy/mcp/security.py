from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from .errors import MCPInjectionDenied, MCPTenantViolation

_INJECTION_PATTERNS = [
    re.compile(r"\bignore\s+(all\s+)?previous\s+instructions\b", re.I),
    re.compile(r"\breveal\s+(the\s+)?(system prompt|api key|secret|credentials?)\b", re.I),
    re.compile(r"\b(disable|bypass)\s+(security|authorization|guardrails?)\b", re.I),
    re.compile(r"\bexecute\s+(this\s+)?tool\s+without\s+(approval|authorization)\b", re.I),
]
_SECRET_KEYS = {"authorization", "token", "access_token", "api_key", "secret", "password", "cookie"}


def reject_injected_arguments(value: Any) -> None:
    if isinstance(value, str):
        if any(pattern.search(value) for pattern in _INJECTION_PATTERNS):
            raise MCPInjectionDenied("instruction-like content in MCP arguments")
    elif isinstance(value, dict):
        for item in value.values():
            reject_injected_arguments(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            reject_injected_arguments(item)


def enforce_tenant_scope(arguments: dict[str, Any], tenant_id: UUID) -> dict[str, Any]:
    scoped = dict(arguments)
    supplied = scoped.get("tenant_id")
    if supplied is not None and str(supplied) != str(tenant_id):
        raise MCPTenantViolation("MCP argument tenant does not match trusted caller tenant")
    scoped["tenant_id"] = str(tenant_id)
    return scoped


def sanitize_output(value: Any) -> Any:
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() in _SECRET_KEYS:
                clean[key] = "[REDACTED]"
            else:
                clean[key] = sanitize_output(item)
        return clean
    if isinstance(value, list):
        return [sanitize_output(item) for item in value]
    if isinstance(value, str):
        return value[:20_000]
    return value
