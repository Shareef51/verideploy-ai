from pathlib import Path
import json
from verideploy.recruiter.package import validate_recruiter_package
ROOT=Path(__file__).resolve().parents[2]

def test_gate_passes():
    r=validate_recruiter_package(ROOT); assert r['gate']=='pass', r['findings']; assert r['screenshots']==3

def test_root_readme_is_current_and_dual_audience():
    t=(ROOT/'README.md').read_text(); assert '0.86.0' in t
    for s in ['What VeriDeploy AI Does','Measured Engineering Evidence','Known Limitations','Interview Walkthrough','Repository Guide']: assert f'## {s}' in t
    assert 'more than an llm wrapper' in t.lower()

def test_canonical_architecture_diagrams_are_linked():
    t=(ROOT/'README.md').read_text(); assert 'docs/architecture/topology.mmd' in t and 'docs/architecture/data-flow.mmd' in t

def test_screenshot_metadata_is_truthful_and_source_backed():
    cfg=json.loads((ROOT/'config/recruiter/package.json').read_text())
    for item in cfg['screenshots']:
        meta=json.loads((ROOT/item['metadata']).read_text()); assert meta['capture_kind']=='source_derived_static_capture'; assert meta['live_runtime_screenshot'] is False
        assert meta['derived_from'] and all((ROOT/p).exists() for p in meta['derived_from'])

def test_recruiter_package_carries_setup_security_eval_and_limitations():
    for p in ['docs/recruiter/setup-and-demo.md','docs/recruiter/security-evaluation.md','docs/recruiter/benchmark-evidence.md','docs/recruiter/limitations.md','docs/recruiter/demo-video-script.md','docs/recruiter/interview-walkthrough.md']: assert (ROOT/p).stat().st_size>300
