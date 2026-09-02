from pathlib import Path
from verideploy.architecture.integrity import validate_architecture
ROOT=Path(__file__).resolve().parents[2]
def test_gate_passes(): assert validate_architecture(ROOT)["valid"]
def test_no_demo_reviewer_runtime_fallback():
    text=(ROOT/"apps/gateway/src/approvals/approvals.service.ts").read_text(); assert "demo-reviewer" not in text and "GATEWAY_APPROVAL_REVIEWER" not in text
def test_approval_uses_authenticated_identity():
    text=(ROOT/"apps/gateway/src/approvals/approvals.controller.ts").read_text(); assert 'x-user-id' in text and 'x-auth-roles' in text
def test_no_legacy_duplicate_services_namespace(): assert not (ROOT/"src/verideploy/services").exists()
def test_every_registered_component_has_purpose_and_adr():
    import json
    p=json.loads((ROOT/"config/architecture/scope-integrity.json").read_text()); assert all(x["purpose"] and x["adr"] for x in p["components"])
