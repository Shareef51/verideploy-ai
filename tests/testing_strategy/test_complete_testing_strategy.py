from pathlib import Path
from verideploy.testing.strategy import load_strategy,validate_suite_inventory,coverage_gate,critical_mutation_probes,shard_for
ROOT=Path(__file__).resolve().parents[2]

def test_all_required_suites_have_inventory():
    s=load_strategy(ROOT); assert validate_suite_inventory(ROOT,s)==[]

def test_coverage_policy_threshold():
    s=load_strategy(ROOT); assert coverage_gate(87.0,s["coverage"]["global_min_percent"]).passed

def test_all_critical_mutations_are_killed():
    results=critical_mutation_probes(); assert len(results)>=4; assert all(x.killed for x in results), results

def test_ci_sharding_is_stable():
    assert shard_for("tests/rag/test_x.py::test_y",4)==shard_for("tests/rag/test_x.py::test_y",4)

def test_playwright_fixture_exists():
    assert (ROOT/"apps/web/tests/e2e/shell.spec.ts").exists()
