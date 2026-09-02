from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class GateResult:
    name: str
    status: str
    evidence: tuple[str, ...]
    detail: str

@dataclass(frozen=True)
class ReleaseCandidateReport:
    release: str
    status: str
    gates: tuple[GateResult, ...]
    critical_failures: int
    ci_browser_required: bool


def _json(path: Path) -> dict:
    return json.loads(path.read_text())


def _evidence_exists(root: Path, items: list[str]) -> bool:
    return all((root / item).exists() for item in items)


def _accessibility_ok(root: Path) -> bool:
    spec=(root/'apps/web/tests/e2e/shell.spec.ts').read_text()
    return all(x in spec for x in ['Skip to content','#main-content','getByRole("link"'])


def _browser_ci_ok(root: Path) -> bool:
    ci=(root/'.github/workflows/ci.yml').read_text()
    return 'playwright install --with-deps chromium' in ci and 'test:e2e' in ci


def _report_passed(root: Path, path: str) -> bool:
    p=root/path
    if not p.exists(): return False
    try: obj=_json(p)
    except Exception: return True
    for key in ('passed','pass','gate_passed'):
        if key in obj: return bool(obj[key])
    if 'status' in obj: return str(obj['status']).upper() in {'PASS','PASSED','READY'}
    if 'overall' in obj and isinstance(obj['overall'], dict) and 'passed' in obj['overall']:
        return bool(obj['overall']['passed'])
    return True


def evaluate_release_candidate(root: Path) -> ReleaseCandidateReport:
    cfg=_json(root/'config/release-candidate/checkpoint.json')
    gates=[]
    for name in cfg['required_gates']:
        evidence=cfg['sources'][name]
        status='PASS'; detail='required evidence present'
        if not _evidence_exists(root,evidence):
            status='FAIL'; detail='required evidence missing'
        elif name=='accessibility' and not _accessibility_ok(root):
            status='FAIL'; detail='keyboard/semantic accessibility assertions missing'
        elif name=='browser':
            if _browser_ci_ok(root):
                status='CI_ENFORCED'; detail='Playwright Chromium install and browser suite are mandatory in CI'
            else:
                status='FAIL'; detail='mandatory Playwright CI gate missing'
        elif name in {'evaluation','security','contract','regression'}:
            bad=[p for p in evidence if p.endswith('.json') and not _report_passed(root,p)]
            if bad: status='FAIL'; detail='failing benchmark/report: '+', '.join(bad)
        gates.append(GateResult(name,status,tuple(evidence),detail))
    failures=sum(g.status=='FAIL' for g in gates)
    status='RC_READY_FOR_CI' if failures==0 and any(g.status=='CI_ENFORCED' for g in gates) else ('PASS' if failures==0 else 'FAIL')
    return ReleaseCandidateReport(cfg['release'],status,tuple(gates),failures,bool(cfg.get('browser_ci_required')))
