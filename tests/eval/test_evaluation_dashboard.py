from datetime import UTC, datetime, timedelta
from pathlib import Path

from verideploy.evaluation.dashboard import GatePolicy, build_case_drilldown, build_trends, compare_runs
from verideploy.evaluation.models import CaseResult, EvaluationScore, ReproducibilityMetadata, RunManifest
from verideploy.evaluation.storage import EvaluationStore


def run(run_id: str, score: float, minute: int, *, model: str, prompt: str, retriever: str) -> RunManifest:
    return RunManifest(
        run_id=run_id,
        dataset_id="verideploy-500",
        dataset_version="1.0.0",
        dataset_sha256="a" * 64,
        evaluator_names=["quality", "safety"],
        runner_name="test",
        total_cases=2,
        passed_cases=2,
        failed_cases=0,
        aggregate_score=score,
        started_at=datetime(2026, 8, 19, 8, minute, tzinfo=UTC),
        completed_at=datetime(2026, 8, 19, 8, minute, tzinfo=UTC) + timedelta(seconds=2),
        status="completed",
        reproducibility=ReproducibilityMetadata(
            python_version="3.12", platform="test", git_commit="abc", git_dirty=False, seed=59,
            dependency_fingerprint="fp", environment="test"
        ),
        metadata={"experiment": {"model": model, "prompt_id": "release-risk", "prompt_version": prompt, "retriever": retriever}},
    )


def result(case_id: str, category: str, value: float, *, trace: str | None = None) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        category=category,
        output={"trace_id": trace} if trace else {},
        scores=[EvaluationScore(evaluator="quality", score=value, passed=value >= 0.8)],
        passed=value >= 0.8,
        latency_ms=10.0,
    )


def test_compare_runs_tracks_experiment_dimensions_and_gate() -> None:
    baseline=run("base", .94, 1, model="gpt-a", prompt="1", retriever="dense")
    candidate=run("cand", .96, 2, model="gpt-b", prompt="2", retriever="fused")
    comparison=compare_runs(
        baseline=baseline, baseline_results=[result("c1", "retrieval", .90)],
        candidate=candidate, candidate_results=[result("c1", "retrieval", .97)]
    )
    assert comparison.release_gate.passed
    assert comparison.candidate.model == "gpt-b"
    assert comparison.candidate.retriever == "fused"
    assert comparison.metric_deltas[0].delta > 0


def test_release_gate_blocks_material_regression() -> None:
    baseline=run("base", .96, 1, model="a", prompt="1", retriever="dense")
    candidate=run("cand", .90, 2, model="b", prompt="2", retriever="fused")
    comparison=compare_runs(
        baseline=baseline, baseline_results=[result("c1", "rag", .96)],
        candidate=candidate, candidate_results=[result("c1", "rag", .80)],
        policy=GatePolicy(max_aggregate_drop=.01, max_metric_drop=.02, min_candidate_score=.90),
    )
    assert not comparison.release_gate.passed
    assert comparison.release_gate.blocking_reasons


def test_case_drilldown_preserves_trace_link() -> None:
    rows=build_case_drilldown([result("case-1", "safety", .99, trace="trace-123")])
    assert rows[0].trace_id == "trace-123"
    assert rows[0].trace_url == "/agent-execution?trace_id=trace-123"


def test_historical_trends_are_chronological() -> None:
    older=run("older", .90, 1, model="a", prompt="1", retriever="dense")
    newer=run("newer", .95, 2, model="b", prompt="2", retriever="fused")
    trends=build_trends([newer, older])
    assert [p.run_id for p in trends] == ["older", "newer"]
    assert trends[-1].aggregate_score == .95


def test_store_lists_runs_and_case_results(tmp_path: Path) -> None:
    store=EvaluationStore(tmp_path / "eval.db")
    manifest=run("stored", .95, 1, model="a", prompt="1", retriever="dense")
    results=[result("c1", "retrieval", .95)]
    store.save_run(manifest, results)
    assert store.list_runs(dataset_id="verideploy-500")[0].run_id == "stored"
    assert store.get_case_results("stored")[0].case_id == "c1"
