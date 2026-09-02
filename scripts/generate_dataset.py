from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from verideploy.evaluation.datasets import build_dataset_manifest
from verideploy.evaluation.quality import EXPECTED_COUNTS, assert_dataset_quality

SERVICES = ("checkout-api", "payment-worker", "order-service", "catalog-api", "identity-api", "notification-worker", "inventory-api", "gateway")
CAUSES = ("db_pool_exhaustion", "retry_storm", "cache_stampede", "bad_index_plan", "downstream_timeout", "memory_pressure", "queue_backlog", "dns_resolution")
REGIONS = ("us-east-1", "us-west-2", "eu-west-1", "ap-south-1")
SCENARIOS = ("easy","medium","difficult","no_answer","conflicting_evidence","stale_runbook","wrong_service","wrong_environment","malformed_logs","partial_github_outage","openai_timeout","irrelevant_documents","rag_prompt_injection","duplicate_evidence","multi_hop_rca","cross_tenant_leakage","restart_resume")

def source(source_id: str, source_type: str, locator: str, rationale: str) -> dict[str, Any]:
    return {"source_id": source_id, "source_type": source_type, "required": True, "locator": locator, "rationale": rationale}

def base(case_id: str, category: str, user_input: dict[str, Any], ground_truth: dict[str, Any], sources: list[dict[str, Any]], difficulty: str) -> dict[str, Any]:
    scenario=SCENARIOS[(int(case_id.rsplit("-",1)[-1])-1)%len(SCENARIOS)]
    user_input={**user_input,"evaluation_scenario":scenario}
    return {
        "case_id": case_id,
        "category": category,
        "input": user_input,
        "expected": {"quality_contract": "v1", "must_use_ground_truth": True, "must_cite_required_sources": True},
        "ground_truth": ground_truth,
        "source_requirements": sources,
        "metadata": {"split": "evaluation", "synthetic": True, "difficulty": difficulty, "scenario":scenario, "dataset_family": "verideploy-500", "schema_version": "1.1"},
    }

def retrieval(i: int) -> dict[str, Any]:
    service, region = SERVICES[i % len(SERVICES)], REGIONS[i % len(REGIONS)]
    rel = [f"runbook-{service}-{i:03d}", f"incident-note-{i:03d}"]
    return base(f"retrieval-{i:03d}", "retrieval", {"query": f"Find the recovery guidance and prior incident for {service} saturation scenario R{i:03d} in {region}.", "tenant_id": "synthetic-nexuspay", "top_k": 5}, {"relevant_source_ids": rel, "must_retrieve_at_k": 5}, [source(rel[0], "runbook", f"runbooks/{service}.md#scenario-r{i:03d}", "primary remediation procedure"), source(rel[1], "incident", f"incidents/INC-R{i:03d}.json", "historical analogue")], "medium" if i % 3 else "hard")

def rca(i: int) -> dict[str, Any]:
    service, cause = SERVICES[i % len(SERVICES)], CAUSES[i % len(CAUSES)]
    ids = [f"trace-rca-{i:03d}", f"metric-rca-{i:03d}", f"deploy-rca-{i:03d}"]
    return base(f"rca-{i:03d}", "rca", {"question": f"Determine the root cause of synthetic incident RCA-{i:03d}: {service} p99 latency rose immediately after release v52.{i}.0 while dependency health changed.", "incident_id": f"INC-RCA-{i:03d}"}, {"root_cause_code": cause, "supporting_source_ids": ids, "prohibited_alternatives": [CAUSES[(i + 1) % len(CAUSES)], CAUSES[(i + 2) % len(CAUSES)]]}, [source(ids[0], "trace", f"traces/RCA-{i:03d}.json", "request path evidence"), source(ids[1], "metric", f"metrics/RCA-{i:03d}.json", "time-correlated saturation signal"), source(ids[2], "deployment", f"deployments/v52.{i}.0.json", "change correlation")], "hard")

def release_risk(i: int) -> dict[str, Any]:
    risk = (i * 17) % 101
    if risk >= 70: decision, band = "hold", "high"
    elif risk >= 40: decision, band = "review", "medium"
    else: decision, band = "approve", "low"
    ids = [f"diff-risk-{i:03d}", f"ci-risk-{i:03d}"]
    return base(f"release-risk-{i:03d}", "release_risk", {"release_id": f"v52-risk-{i:03d}", "question": f"Should synthetic release v52-risk-{i:03d} deploy after migration and CI evidence are reviewed?", "risk_inputs": {"migration_touch": i % 2 == 0, "failed_checks": i % 4, "change_size": 20 + i}}, {"decision": decision, "risk_band": band, "supporting_source_ids": ids}, [source(ids[0], "code_diff", f"releases/v52-risk-{i:03d}/diff.json", "change surface"), source(ids[1], "ci_run", f"ci/v52-risk-{i:03d}.json", "verification status")], "medium")

def visual(i: int) -> dict[str, Any]:
    image = f"image-visual-{i:03d}"
    metric = "p99_latency_ms" if i % 2 == 0 else "error_rate_pct"
    value = 500 + i * 7 if metric == "p99_latency_ms" else round(1.0 + i * 0.13, 2)
    return base(f"visual-{i:03d}", "visual", {"task": f"Inspect dashboard screenshot VIS-{i:03d} and report the highlighted anomaly without inventing unreadable values.", "image_ref": image}, {"observations": [{"metric": metric, "value": value, "unit": "ms" if metric.endswith("ms") else "percent"}], "supporting_source_ids": [image], "numeric_tolerance": 0.05}, [source(image, "image", f"images/grafana/VIS-{i:03d}.png", "pixel-grounded dashboard evidence")], "hard")

def document_qa(i: int) -> dict[str, Any]:
    doc = f"doc-qa-{i:03d}"
    answer = f"Rollback is authorized after two consecutive failed health gates for policy DQ-{i:03d}."
    return base(f"document-qa-{i:03d}", "document_qa", {"question": f"Under synthetic deployment policy DQ-{i:03d}, when is rollback authorized?", "document_scope": doc}, {"answer": answer, "supporting_source_ids": [doc], "required_citation_spans": [f"policy-DQ-{i:03d}-section-4.2"]}, [source(doc, "pdf", f"policies/deployment-policy-{i:03d}.pdf#page=4", "authoritative policy text")], "medium")

def hallucination(i: int) -> dict[str, Any]:
    log = f"log-hall-{i:03d}"
    verdict = "insufficient_evidence" if i % 2 == 0 else "supported"
    allowed = [f"The {SERVICES[i % len(SERVICES)]} emitted timeout evidence in case H{i:03d}."]
    forbidden = [f"A database corruption definitely occurred in H{i:03d}.", f"Customer data loss was confirmed in H{i:03d}."]
    return base(f"hallucination-{i:03d}", "hallucination", {"prompt": f"Assess what can safely be claimed about synthetic incident H{i:03d} using only the supplied evidence.", "evidence_scope": [log]}, {"verdict": verdict, "allowed_claims": allowed, "forbidden_claims": forbidden, "supporting_source_ids": [log]}, [source(log, "log", f"logs/H{i:03d}.jsonl", "bounded observed evidence")], "hard")

def citation(i: int) -> dict[str, Any]:
    ids = [f"cite-a-{i:03d}", f"cite-b-{i:03d}"]
    claims = [{"claim_id": f"C{i:03d}-1", "text": f"Release C{i:03d} changed connection-pool settings.", "source_ids": [ids[0]]}, {"claim_id": f"C{i:03d}-2", "text": f"Latency increased after that deployment window.", "source_ids": [ids[1]]}]
    return base(f"citation-{i:03d}", "citation", {"task": f"Produce a two-claim evidence summary for synthetic case C{i:03d} with complete source attribution."}, {"claims": claims, "required_source_ids": ids, "minimum_coverage": 1.0}, [source(ids[0], "deployment", f"deployments/C{i:03d}.json", "supports configuration-change claim"), source(ids[1], "metric", f"metrics/C{i:03d}.json", "supports latency claim")], "hard")

BUILDERS = {"retrieval": retrieval, "rca": rca, "release_risk": release_risk, "visual": visual, "document_qa": document_qa, "hallucination": hallucination, "citation": citation}

def generate(path: Path) -> None:
    cases: list[dict[str, Any]] = []
    for category, count in EXPECTED_COUNTS.items():
        builder = BUILDERS[category]
        cases.extend(builder(i) for i in range(1, count + 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(case, sort_keys=True, separators=(",", ":")) + "\n" for case in cases), encoding="utf-8")

def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and validate the deterministic VeriDeploy 500-case evaluation dataset")
    parser.add_argument("--output", type=Path, default=Path("evals/datasets/verideploy-500/v1.jsonl"))
    parser.add_argument("--manifest", type=Path, default=Path("evals/datasets/verideploy-500/manifest.json"))
    args = parser.parse_args()
    generate(args.output)
    report = assert_dataset_quality(args.output)
    manifest = build_dataset_manifest(path=args.output, dataset_id="verideploy-500", version="1.0.0", description="Deterministic 500-case production evaluation corpus")
    data = manifest.model_dump(mode="json")
    # created_at is informational; reproducibility is anchored to content_sha256 and deterministic source generation.
    data["generated_by"] = "scripts/generate_dataset.py"
    data["quality_gate"] = report.as_dict()
    data["validated_at"] = datetime.now(UTC).isoformat()
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report.passed, "cases": report.case_count, "categories": report.category_counts, "sha256": manifest.content_sha256}, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
