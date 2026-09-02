import json
from pathlib import Path
import yaml
from verideploy.architecture.final_topology import load_topology, validate_topology
ROOT=Path(__file__).resolve().parents[2]

def test_topology_has_complete_required_technology_boundary():
    r=validate_topology(ROOT); assert r.passed, r.findings; assert r.node_count >= 15; assert r.flow_count >= 18

def test_browser_never_bypasses_nestjs_public_boundary():
    t=load_topology(ROOT); assert not any(f['from']=='client' and f['to']=='ai' for f in t['flows']); assert [n['id'] for n in t['layers'] if n.get('public')] == ['client','gateway']

def test_helm_release_and_image_tags_match_release():
    v=json.loads((ROOT/'config/release/version.json').read_text())['version']; c=yaml.safe_load((ROOT/'infrastructure/helm/verideploy/Chart.yaml').read_text()); p=yaml.safe_load((ROOT/'infrastructure/helm/verideploy/values-production.yaml').read_text()); assert c['version']==v and str(c['appVersion'])==v; assert all(str(x['tag'])==v for x in p['images'].values()); assert str(p['canary']['gateway']['imageTag'])==v

def test_local_parity_contains_critical_platform_dependencies():
    c=yaml.safe_load((ROOT/'docker-compose.yml').read_text())['services']; required={'web','gateway','ai-service','postgres','redis','kafka','minio','keycloak','otel-collector','prometheus','grafana','loki','tempo'}; assert required <= set(c)

def test_diagrams_are_generated_from_canonical_topology_model():
    t=load_topology(ROOT); assert len(t['diagram_sources'])==3; assert all((ROOT/p).exists() for p in t['diagram_sources']); doc=(ROOT/'docs/architecture/final-production-technology-architecture.md').read_text(); assert 'Next.js' in doc and 'NestJS' in doc and 'LangGraph' in doc and 'OpenAI' in doc and 'PostgreSQL/pgvector' in doc
