from __future__ import annotations
import json, sys
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from verideploy.architecture.final_topology import validate_topology

def main():
    rel=json.loads((ROOT/'config/release/version.json').read_text())['version']
    topo=json.loads((ROOT/'config/architecture/production-topology.json').read_text())
    findings=list(validate_topology(ROOT).findings)
    if topo['release'] != rel: findings.append('topology release mismatch')
    chart=yaml.safe_load((ROOT/'infrastructure/helm/verideploy/Chart.yaml').read_text())
    if chart.get('version') != rel or str(chart.get('appVersion')) != rel: findings.append('Helm chart/app version mismatch')
    prod=yaml.safe_load((ROOT/'infrastructure/helm/verideploy/values-production.yaml').read_text())
    for name,cfg in prod.get('images',{}).items():
        if str(cfg.get('tag')) != rel: findings.append(f'production image tag mismatch: {name}')
    if str(prod.get('canary',{}).get('gateway',{}).get('imageTag')) != rel: findings.append('canary image tag mismatch')
    compose=yaml.safe_load((ROOT/'docker-compose.yml').read_text())
    required={'web','gateway','ai-service','release-risk-worker','ingestion-worker','investigation-worker','postgres','redis','kafka','minio','keycloak','otel-collector','prometheus','grafana','loki','tempo'}
    missing=sorted(required-set(compose.get('services',{})))
    if missing: findings.append('compose missing services: '+','.join(missing))
    helm=yaml.safe_load((ROOT/'infrastructure/helm/verideploy/values.yaml').read_text())
    if set(helm.get('workloads',{})) != {'web','gateway','ai-service','worker'}: findings.append('Helm workload set drift')
    for p in topo['diagram_sources']:
        if not (ROOT/p).exists(): findings.append('missing diagram source: '+p)
    report={'release':rel,'status':'PASS' if not findings else 'FAIL','node_count':len(topo['layers']),'flow_count':len(topo['flows']),'findings':findings,'production_workloads':topo['production_workloads'],'security_invariants':len(topo['security_invariants'])}
    out=ROOT/'evals/reports/final-production-architecture.json'; out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    raise SystemExit(0 if not findings else 1)
if __name__=='__main__': main()
