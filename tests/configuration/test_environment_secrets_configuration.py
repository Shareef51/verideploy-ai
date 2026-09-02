import json
from pathlib import Path
import pytest
from verideploy.environment.management import EnvironmentPolicy, SecretReference, apply_environment_overlay, redact_secrets, validate_environment

ROOT=Path(__file__).resolve().parents[2]
POLICY=EnvironmentPolicy.load(ROOT/"config/environments/manifest.json")

def test_environment_overlays_are_typed_and_known():
    for env in POLICY.environments:
        values=apply_environment_overlay({},env=env,config_dir=ROOT/"config/environments")
        assert values["APP_ENV"]==env

def test_production_fails_fast_on_missing_configuration_and_plaintext_secret():
    errors=validate_environment({"APP_ENV":"production","OPENAI_API_KEY":"plaintext-key"},POLICY,env="production")
    assert any("missing required configuration" in e for e in errors)
    assert any("OPENAI_API_KEY must use an external secret reference" in e for e in errors)

def test_secret_reference_and_log_redaction():
    ref=SecretReference.parse("secret://aws-sm/verideploy/production/openai#v7")
    assert ref.scheme=="aws-sm" and ref.version=="v7"
    data=redact_secrets({"OPENAI_API_KEY":"secret://aws-sm/x","nested":{"authorization":"Bearer abc","safe":"ok"}},POLICY)
    assert data["OPENAI_API_KEY"]=="[REDACTED]" and data["nested"]["authorization"]=="[REDACTED]" and data["nested"]["safe"]=="ok"

def test_no_secret_variable_is_declared_public():
    assert not POLICY.public_variables.intersection(POLICY.secret_variables)
    assert all(name.startswith("NEXT_PUBLIC_") for name in POLICY.public_variables)

def test_repository_has_no_secret_access_in_client_modules():
    forbidden=set(POLICY.secret_variables)
    violations=[]
    for path in (ROOT/"apps/web").rglob("*.ts*"):
        rel=path.relative_to(ROOT).as_posix()
        if "/tests/" in f"/{rel}/" or rel.endswith("lib/config/server.ts") or rel.endswith("lib/auth/session.ts") or rel.endswith("lib/auth/oidc.ts") or "/app/api/" in f"/{rel}":
            continue
        text=path.read_text(errors="ignore")
        for name in forbidden:
            if f"process.env.{name}" in text or f'process.env["{name}"]' in text or f"process.env['{name}']" in text:
                violations.append((rel,name))
    assert violations==[]


def test_helm_separates_nonsecret_config_from_runtime_secret():
    template=(ROOT/"infrastructure/helm/verideploy/templates/workloads.yaml").read_text()
    assert "configMapRef: {name: verideploy-runtime-config}" in template
    assert "secretRef: {name:" in template
    external=(ROOT/"infrastructure/helm/verideploy/templates/external-secret.yaml").read_text()
    assert "ExternalSecret" in external and "runtimeSecretName" in external
