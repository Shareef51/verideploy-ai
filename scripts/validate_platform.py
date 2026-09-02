#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re
from pathlib import Path
import yaml
from verideploy.platform.reliability import DependencyState, PlatformReliabilityModel, PlatformState, required_compose_services

ROOT=Path(__file__).resolve().parents[1]
POLICY_PATH=ROOT/'config/platform/checkpoint.json'
REPORT=ROOT/'evals/reports/platform-integration-reliability.json'


def load() -> tuple[dict, dict]:
    policy=json.loads(POLICY_PATH.read_text())
    compose=yaml.safe_load((ROOT/policy['local_parity']['compose_file']).read_text())
    return policy,compose


def validate_static(policy:dict, compose:dict)->list[str]:
    errors=[]
    services=compose.get('services',{})
    for name in required_compose_services(policy):
        if name not in services: errors.append(f'missing compose service: {name}')
    # Foundational stateful services must have health checks so dependants can converge.
    for name in ('postgres','redis','kafka','minio','keycloak'):
        if name in services and 'healthcheck' not in services[name]: errors.append(f'missing healthcheck: {name}')
    for name in ('gateway','ai-service'):
        hc=services.get(name,{}).get('healthcheck',{})
        text=json.dumps(hc)
        if '/health/ready' not in text: errors.append(f'{name} healthcheck must use readiness endpoint')
    # Observability is required for parity, but failures are intentionally degraded not fatal.
    for name in ('otel-collector','prometheus','grafana','loki','tempo'):
        if name not in services: errors.append(f'missing observability service: {name}')
    gateway_health=(ROOT/'apps/gateway/src/health/health.controller.ts').read_text()
    release=json.loads((ROOT/'config/release/version.json').read_text())['version']
    if release not in gateway_health: errors.append('gateway health version drift')
    if 'configuration' not in gateway_health: errors.append('gateway readiness configuration check missing')
    prom=(ROOT/'infrastructure/observability/prometheus.yml').read_text()
    if 'verideploy' not in prom.lower(): errors.append('prometheus config lacks VeriDeploy targets')
    return errors


def simulate(policy:dict)->dict:
    model=PlatformReliabilityModel(critical=policy['critical_dependencies'], optional=policy['optional_dependencies'])
    baseline=model.snapshot()
    critical={}
    for dep in policy['critical_dependencies']:
        model.set_dependency(dep,DependencyState.FAILED)
        down=model.snapshot()
        restart=model.restart('ai-service')
        model.set_dependency(dep,DependencyState.HEALTHY)
        restored=model.snapshot()
        critical[dep]={
            'fails_closed': down.state==PlatformState.NOT_READY,
            'restart_does_not_mask_failure': restart.state==PlatformState.NOT_READY and not restart.recovered,
            'recovers_after_restore': restored.state==PlatformState.READY,
        }
    optional={}
    for dep in policy['optional_dependencies']:
        model.set_dependency(dep,DependencyState.FAILED)
        degraded=model.snapshot()
        model.set_dependency(dep,DependencyState.HEALTHY)
        optional[dep]={
            'degrades_not_fails': degraded.state==PlatformState.DEGRADED,
            'recovers_after_restore': model.snapshot().state==PlatformState.READY,
        }
    return {'baseline_ready':baseline.state==PlatformState.READY,'critical':critical,'optional':optional}


def main()->int:
    parser=argparse.ArgumentParser(); parser.add_argument('--report',default=str(REPORT)); args=parser.parse_args()
    policy,compose=load(); errors=validate_static(policy,compose); sim=simulate(policy)
    sim_pass=sim['baseline_ready'] and all(all(v.values()) for v in sim['critical'].values()) and all(all(v.values()) for v in sim['optional'].values())
    gate=not errors and sim_pass
    report={'gate':'pass' if gate else 'fail','errors':errors,'simulation':sim,'compose_services':sorted(compose.get('services',{}))}
    out=Path(args.report); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'gate':report['gate'],'errors':errors,'critical_failures_tested':len(sim['critical']),'optional_failures_tested':len(sim['optional'])}))
    return 0 if gate else 1
if __name__=='__main__': raise SystemExit(main())
