from pathlib import Path
import pytest
from verideploy.security import AuthorizationContext, SecurityPolicy, SecurityPolicyError, SsrfDefense, architecture_scan, authorize, generate_pkce_pair, validate_encryption_posture, validate_secret_reference
ROOT=Path(__file__).parents[2]
POLICY=SecurityPolicy.load(ROOT/"config/security/policy.json")

def test_pkce_s256_is_high_entropy_and_stable_shape():
    verifier,challenge=generate_pkce_pair(); assert len(verifier)>=43 and len(challenge)==43 and verifier!=challenge

def test_rbac_abac_and_tenant_are_default_deny():
    c=AuthorizationContext("u","tenant-a",frozenset({"developer"}),{"environment":"prod"})
    assert authorize(POLICY,c,action="incident.create",resource_tenant_id="tenant-a",required_attributes={"environment":"prod"})
    assert not authorize(POLICY,c,action="incident.create",resource_tenant_id="tenant-b")
    assert not authorize(POLICY,c,action="approval.decide",resource_tenant_id="tenant-a")
    assert not authorize(POLICY,c,action="incident.create",resource_tenant_id="tenant-a",required_attributes={"environment":"dev"})

def test_ssrf_denies_unapproved_networks_and_hosts():
    d=SsrfDefense(POLICY.raw["ssrf"]["allowed_hosts"],POLICY.raw["ssrf"]["allowed_schemes"])
    assert d.validate("https://api.github.com/repos/openai/openai-python")
    for url in ("http://169.254.169.254/latest/meta-data","https://127.0.0.1/admin","https://evil.example/x"):
        with pytest.raises(SecurityPolicyError):d.validate(url)

def test_production_secret_and_encryption_posture_fail_closed():
    validate_secret_reference("aws-sm://verideploy/prod/openai",production=True,allowed_schemes=POLICY.raw["secrets"]["allowed_reference_schemes"])
    with pytest.raises(SecurityPolicyError):validate_secret_reference("plaintext-secret",production=True,allowed_schemes=POLICY.raw["secrets"]["allowed_reference_schemes"])
    validate_encryption_posture(production=True,kms_key_ref="aws-kms://alias/verideploy",database_tls=True,object_sse=True)
    with pytest.raises(SecurityPolicyError):validate_encryption_posture(production=True,kms_key_ref=None,database_tls=True,object_sse=True)

def test_architecture_scan_has_no_unresolved_critical_findings():
    findings=architecture_scan(ROOT);assert [f for f in findings if f.severity=="critical"]==[]
