from pathlib import Path
from verideploy.career.interview_evidence import build_report, load_config, resolve_metrics, validate

ROOT=Path(__file__).resolve().parents[2]

def test_all_metric_sources_resolve_to_repository_evidence():
    metrics=resolve_metrics(ROOT)
    assert len(metrics) >= 20
    assert all(m["qualifier"] for m in metrics.values())


def test_resume_claims_have_no_unmeasured_numeric_literals():
    assert validate(ROOT) == []


def test_generates_recruiter_ready_resume_and_star_evidence():
    report=build_report(ROOT)
    assert report["gate"] == "pass"
    assert len(report["resume_bullets"]) >= 5
    assert len(report["star_stories"]) >= 4
    assert len(report["recruiter_questions"]) >= 10


def test_cost_latency_claims_are_explicitly_qualified():
    cfg=load_config(ROOT)
    qualifiers={m["id"]:m["qualifier"] for m in cfg["metrics"]}
    assert "not production network latency" in qualifiers["rag_cold_p95_ms"]
    assert "estimated" in qualifiers["demo_estimated_cost_usd"]
    assert "not an incurred production charge" in qualifiers["demo_estimated_cost_usd"]


def test_preserves_evidence_backed_skill_claims():
    report=build_report(ROOT)
    text="\n".join(x["text"] for x in report["resume_bullets"])
    assert "14 AI-engineering skill claims" in text
    assert "code plus verification evidence" in text
