from datetime import UTC, datetime, timedelta
from pathlib import Path

from verideploy.evaluation.models import CaseResult, EvaluationScore, ReproducibilityMetadata, RunManifest
from verideploy.evaluation.regression_gates import OverrideApproval, QualityBudget, RegressionPolicy, attribute_change, detect_flaky_cases, evaluate_regression_gate
from verideploy.evaluation.storage import EvaluationStore


def manifest(run_id: str, aggregate: float, *, model: str = "gpt-a", prompt: str = "1", retriever: str = "dense", failed: int = 0) -> RunManifest:
    return RunManifest(
        run_id=run_id, dataset_id="verideploy-500", dataset_version="1.0.0", dataset_sha256="a"*64,
        evaluator_names=["quality"], runner_name="test", total_cases=100,
        passed_cases=100-failed, failed_cases=failed, aggregate_score=aggregate,
        started_at=datetime(2026,8,19,6,0,tzinfo=UTC), completed_at=datetime(2026,8,19,6,1,tzinfo=UTC), status="completed",
        reproducibility=ReproducibilityMetadata(python_version="3.12", platform="test", git_commit="abc", git_dirty=False, seed=60, dependency_fingerprint="fp", environment="ci"),
        metadata={"experiment":{"model":model,"prompt_id":"release","prompt_version":prompt,"retriever":retriever}},
    )


def results(value: float, count: int = 100, *, jitter: float = 0.0) -> list[CaseResult]:
    rows=[]
    for i in range(count):
        score=max(0.0,min(1.0,value + (jitter if i % 2 else -jitter)))
        rows.append(CaseResult(case_id=f"c{i:03d}", category="retrieval", output={}, scores=[EvaluationScore(evaluator="quality",score=score,passed=score>=.8)], passed=score>=.8, latency_ms=1.0))
    return rows


def policy() -> RegressionPolicy:
    return RegressionPolicy(min_paired_cases=20, budgets=[QualityBudget(metric="quality", blocking_drop=.02, warning_drop=.01, min_score=.90)])


def test_gate_blocks_material_statistical_regression() -> None:
    decision=evaluate_regression_gate(baseline=manifest("b",.96), baseline_results=results(.96,100), candidate=manifest("c",.92), candidate_results=results(.92,100), policy=policy())
    assert decision.status == "block"
    assert not decision.releasable
    assert any(v.code in {"aggregate_regression","metric_regression","statistical_regression"} for v in decision.violations)


def test_change_attribution_records_model_prompt_retriever() -> None:
    a=manifest("a",.95)
    b=manifest("b",.96,model="gpt-b",prompt="2",retriever="fused")
    attr=attribute_change(a,b)
    assert attr.changed_dimensions == ["model","prompt","retriever"]


def test_flaky_cases_are_excluded_from_blocking() -> None:
    h1=results(.95,2); h2=results(.95,2)
    h1[0].scores[0].score=.20; h2[0].scores[0].score=.99
    flaky=detect_flaky_cases([h1,h2], threshold=.01)
    assert flaky and flaky[0].case_id == "c000"


def test_valid_override_makes_blocked_candidate_releasable() -> None:
    override=OverrideApproval(override_id="ovr-1",candidate_run_id="c",policy_id=policy().policy_id,approver="release-manager",reason="approved incident mitigation",ticket="CHG-60",expires_at=datetime.now(UTC)+timedelta(hours=1))
    decision=evaluate_regression_gate(baseline=manifest("b",.96),baseline_results=results(.96),candidate=manifest("c",.91),candidate_results=results(.91),policy=policy(),override=override)
    assert decision.status == "override" and decision.releasable
    assert not decision.baseline_promotable


def test_store_persists_baseline_and_override(tmp_path: Path) -> None:
    store=EvaluationStore(tmp_path/"eval.db")
    run=manifest("candidate",.96)
    store.save_run(run,results(.96))
    store.promote_baseline(dataset_id=run.dataset_id,environment="production",run_id=run.run_id,promoted_by="ci",reason="gate passed")
    assert store.get_baseline(dataset_id=run.dataset_id,environment="production").run_id == "candidate"
    approval=OverrideApproval(override_id="ovr",candidate_run_id="candidate",policy_id=policy().policy_id,approver="lead",reason="documented",ticket="REL-60")
    store.save_override(approval)
    assert store.get_active_override("candidate",policy().policy_id).override_id == "ovr"
