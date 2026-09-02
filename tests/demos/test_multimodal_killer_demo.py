import json
from pathlib import Path
from verideploy.demos.multimodal import MultimodalDemoManifest, validate_multimodal_demo
ROOT=Path(__file__).resolve().parents[2]
def manifest(): return MultimodalDemoManifest.load(ROOT)
def test_all_seven_multimodal_evidence_sources_are_synthetic_and_cited():
 m=manifest(); assert m.synthetic and len(m.evidence)==7 and len(m.expected.required_citations)==7; assert {x.modality for x in m.evidence}>={"document","image","video"}; assert set(m.expected.required_citations)=={x.citation_id for x in m.evidence}
def test_assets_and_signatures_validate():
 r=validate_multimodal_demo(ROOT); assert r["gate"]=="pass" and r["issues"]==[]
def test_gateway_uses_real_ingestion_investigation_and_approval_boundaries():
 t=(ROOT/'apps/gateway/src/demos/demos.service.ts').read_text(); assert 'runMultimodalKiller' in t and '.ingestion.accept(' in t and '.investigations.create(' in t and '.approvals.create(' in t; assert 'dry_run:true' in t and 'execution_disabled:true' in t
def test_ui_explains_graph_latency_cost_citations_and_review_gate():
 t=(ROOT/'apps/web/components/demos/multimodal-killer-demo.tsx').read_text();
 for token in ['SYNTHETIC DATA ONLY','Root cause:','Critic:','Latency budget:','Estimated demo LLM cost:','Citations:','Review gate:']: assert token in t
 assert '/internal/v1' not in t and ':8000' not in t
def test_no_consequential_action_can_execute_without_human_review():
 m=manifest(); assert m.expected.review_status=='pending' and m.expected.decision=='ROLLBACK_REQUIRES_HUMAN_APPROVAL'; assert 'human_review_gate' in m.graph
