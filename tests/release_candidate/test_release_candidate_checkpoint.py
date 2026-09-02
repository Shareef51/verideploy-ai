from pathlib import Path
from verideploy.release_candidate.checkpoint import evaluate_release_candidate
ROOT=Path(__file__).resolve().parents[2]
def test_all_required_gates_are_accounted_for():
 r=evaluate_release_candidate(ROOT); assert {g.name for g in r.gates}=={'evaluation','security','load','chaos','accessibility','browser','contract','regression'}
def test_release_candidate_has_no_critical_failures():
 r=evaluate_release_candidate(ROOT); assert r.critical_failures==0
def test_browser_is_fail_closed_into_ci():
 g=next(g for g in evaluate_release_candidate(ROOT).gates if g.name=='browser'); assert g.status=='CI_ENFORCED'
def test_accessibility_gate_requires_keyboard_semantics():
 g=next(g for g in evaluate_release_candidate(ROOT).gates if g.name=='accessibility'); assert g.status=='PASS'
def test_release_candidate_status_is_not_false_local_browser_pass():
 assert evaluate_release_candidate(ROOT).status=='RC_READY_FOR_CI'
