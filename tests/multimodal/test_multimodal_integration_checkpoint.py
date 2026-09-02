from pathlib import Path
from verideploy.multimodal.checkpoint.integration import deterministic_fixtures, fuse, load_policy, process_fixture, redact, run_checkpoint

ROOT = Path(__file__).resolve().parents[2]

def test_all_modalities_and_large_boundaries_pass():
    p=load_policy(ROOT); results=[process_fixture(x, tenant_id="t", policy=p) for x in deterministic_fixtures()]
    assert {r.modality for r in results} == {"image","pdf","audio","video"}
    assert all(r.status == "READY" for r in results)
    assert fuse(results, policy=p)["status"] == "READY"

def test_partial_failures_remain_bounded_and_traceable():
    p=load_policy(ROOT); results=[process_fixture(x, tenant_id="t", policy=p) for x in deterministic_fixtures(partial=True)]
    f=fuse(results, policy=p)
    assert f["status"] == "PARTIAL" and f["traceability"] == 1.0
    assert set(f["degraded"]) == {"ev-pdf-large","ev-video-large"}

def test_redaction_precedes_persistence_digest():
    p=load_policy(ROOT); r=process_fixture(deterministic_fixtures()[0], tenant_id="t", policy=p)
    assert "@" not in r.redacted_text and "sk-demo-secret" not in r.redacted_text
    assert r.storage_key and r.sha256 and r.sha256 in __import__('hashlib').sha256(r.redacted_text.encode()).hexdigest()

def test_hard_limit_degrades_without_unbounded_work():
    p=load_policy(ROOT); x=deterministic_fixtures()[0]
    x=type(x)(x.evidence_id,x.modality,41,x.text)
    r=process_fixture(x, tenant_id="t", policy=p)
    assert r.status == "DEGRADED" and r.timeline_events == 0 and r.degradation_reason == "bounded_limit_exceeded"

def test_checkpoint_gate_passes():
    report=run_checkpoint(ROOT)
    assert report["passed"] is True
    assert report["clean"]["timeline_events"] <= 1000
