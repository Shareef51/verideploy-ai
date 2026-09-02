from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import secrets
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal
from urllib.parse import urlparse


class SecurityPolicyError(ValueError):
    pass


@dataclass(frozen=True)
class SecurityPolicy:
    raw: dict[str, Any]
    sha256: str

    @classmethod
    def load(cls, path: str | Path) -> "SecurityPolicy":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        cls._validate(payload)
        return cls(payload, hashlib.sha256(canonical).hexdigest())

    @staticmethod
    def _validate(p: dict[str, Any]) -> None:
        if p.get("authorization", {}).get("default_effect") != "deny":
            raise SecurityPolicyError("authorization must default deny")
        if not p.get("oidc", {}).get("pkce_required"):
            raise SecurityPolicyError("OIDC PKCE must be required")
        if "RS256" not in p.get("oidc", {}).get("allowed_algorithms", []):
            raise SecurityPolicyError("RS256 must be an allowed OIDC algorithm")
        if p.get("dependencies", {}).get("critical_vulnerabilities_allowed") != 0:
            raise SecurityPolicyError("critical dependency vulnerabilities must block")
        if p.get("transport", {}).get("production_plain_http_allowed"):
            raise SecurityPolicyError("plain HTTP cannot be allowed in production")


def generate_pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


@dataclass(frozen=True)
class AuthorizationContext:
    subject: str
    tenant_id: str
    roles: frozenset[str]
    attributes: dict[str, str]


def authorize(
    policy: SecurityPolicy,
    context: AuthorizationContext,
    *,
    action: str,
    resource_tenant_id: str,
    required_attributes: dict[str, str] | None = None,
) -> bool:
    if context.tenant_id != resource_tenant_id:
        return False
    role_map = policy.raw["authorization"]["roles"]
    permitted = any(action in role_map.get(role, []) for role in context.roles)
    if not permitted:
        return False
    return all(context.attributes.get(k) == v for k, v in (required_attributes or {}).items())


class SsrfDefense:
    def __init__(self, allowed_hosts: Iterable[str], allowed_schemes: Iterable[str] = ("https",)) -> None:
        self.allowed_hosts = {h.lower().rstrip(".") for h in allowed_hosts}
        self.allowed_schemes = set(allowed_schemes)

    @staticmethod
    def _forbidden_ip(value: str) -> bool:
        ip = ipaddress.ip_address(value)
        return any((ip.is_private, ip.is_loopback, ip.is_link_local, ip.is_multicast, ip.is_reserved, ip.is_unspecified))

    def validate(self, url: str, *, resolve_dns: bool = False) -> str:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme not in self.allowed_schemes:
            raise SecurityPolicyError("SSRF_BLOCKED_SCHEME")
        if not host or host not in self.allowed_hosts:
            raise SecurityPolicyError("SSRF_BLOCKED_HOST")
        try:
            if self._forbidden_ip(host):
                raise SecurityPolicyError("SSRF_BLOCKED_NETWORK")
        except ValueError:
            pass
        if resolve_dns:
            infos = socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
            for info in infos:
                if self._forbidden_ip(info[4][0]):
                    raise SecurityPolicyError("SSRF_BLOCKED_DNS_TARGET")
        if parsed.username or parsed.password:
            raise SecurityPolicyError("SSRF_BLOCKED_USERINFO")
        return url


def validate_secret_reference(reference: str, *, production: bool, allowed_schemes: Iterable[str]) -> None:
    if not production:
        return
    if not any(reference.startswith(prefix) for prefix in allowed_schemes):
        raise SecurityPolicyError("production secrets must use an external secret-manager reference")


def validate_encryption_posture(*, production: bool, kms_key_ref: str | None, database_tls: bool, object_sse: bool) -> None:
    if production and (not kms_key_ref or not database_tls or not object_sse):
        raise SecurityPolicyError("production encryption posture is incomplete")


@dataclass(frozen=True)
class SecurityFinding:
    control_id: str
    severity: Literal["low", "medium", "high", "critical"]
    message: str


def architecture_scan(root: str | Path) -> list[SecurityFinding]:
    root = Path(root)
    findings: list[SecurityFinding] = []
    policy = SecurityPolicy.load(root / "config/security/policy.json")
    if not policy.sha256:
        findings.append(SecurityFinding("SEC-POL-001", "critical", "security policy is not fingerprinted"))
    network = root / "infrastructure/kubernetes/network-policy.yaml"
    if not network.exists():
        findings.append(SecurityFinding("SEC-NET-001", "critical", "Kubernetes network policy missing"))
    threat = (root / "docs/security/threat-model.md").read_text(encoding="utf-8")
    for token in ("OIDC", "SSRF", "tenant", "service identity", "supply chain"):
        if token.lower() not in threat.lower():
            findings.append(SecurityFinding("SEC-TM-001", "high", f"threat model missing {token}"))
    security_module = (root / "apps/gateway/src/security/security.module.ts").read_text(encoding="utf-8")
    app_module = (root / "apps/gateway/src/app.module.ts").read_text(encoding="utf-8")
    if "SecurityHeadersMiddleware" not in security_module or "AuthContextMiddleware" not in security_module or "SecurityModule" not in app_module:
        findings.append(SecurityFinding("SEC-API-001", "critical", "gateway security middleware is not enabled"))
    ci = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    if "security_scan.py" not in ci:
        findings.append(SecurityFinding("SEC-SUP-001", "high", "security scan is not enforced in CI"))
    package=json.loads((root / "package.json").read_text(encoding="utf-8"))
    for section in ("dependencies", "devDependencies"):
        for name, version in package.get(section, {}).items():
            if not str(version) or str(version)[0] in "^~*><":
                findings.append(SecurityFinding("SEC-DEP-001", "high", f"root Node dependency is not exactly pinned: {name}"))
    pyproject=(root / "pyproject.toml").read_text(encoding="utf-8")
    if 'dependencies = [' not in pyproject or '<' not in pyproject:
        findings.append(SecurityFinding("SEC-DEP-002", "high", "Python dependencies are not bounded"))
    return findings
