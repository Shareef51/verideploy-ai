from pathlib import Path
import json
from verideploy.career.mapping import REQUIRED_SKILLS, build_report, load_mapping, validate_mapping

ROOT=Path(__file__).resolve().parents[2]

def test_all_required_ai_engineering_skills_are_mapped():
    data=load_mapping(ROOT)
    assert {c["skill_id"] for c in data["claims"]} == REQUIRED_SKILLS

def test_every_claim_has_code_and_verification_evidence():
    data=load_mapping(ROOT)
    for claim in data["claims"]:
        ev=claim["evidence"]
        assert ev.get("code")
        assert ev.get("tests") or ev.get("reports") or ev.get("traces")

def test_every_evidence_path_exists_and_is_nonempty():
    assert validate_mapping(ROOT) == []

def test_report_is_release_gate_pass():
    report=build_report(ROOT)
    assert report["gate"] == "pass"
    assert report["skill_claims"] == 14
    assert report["skills_with_code_evidence"] == 14
    assert report["skills_with_verification_evidence"] == 14

def test_mapping_does_not_claim_local_execution_for_optional_langgraph_runtime():
    data=load_mapping(ROOT)
    claim=next(c for c in data["claims"] if c["skill_id"]=="langgraph")
    assert claim["status"] == "implemented_runtime_optional_locally"
