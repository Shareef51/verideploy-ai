import json
from pathlib import Path
import yaml

from verideploy.platform.reliability import DependencyState, PlatformReliabilityModel, PlatformState

ROOT=Path(__file__).resolve().parents[2]
POLICY=json.loads((ROOT/'config/platform/checkpoint.json').read_text())


def model():
    return PlatformReliabilityModel(critical=POLICY['critical_dependencies'], optional=POLICY['optional_dependencies'])


def test_smoke_all_foundational_dependencies_ready():
    snapshot=model().snapshot()
    assert snapshot.state is PlatformState.READY
    assert snapshot.ready
    assert set(snapshot.as_checks()) == set(POLICY['critical_dependencies']) | set(POLICY['optional_dependencies'])


def test_every_critical_dependency_failure_fails_readiness_and_recovers():
    m=model()
    for dependency in POLICY['critical_dependencies']:
        m.set_dependency(dependency, DependencyState.FAILED)
        assert m.snapshot().state is PlatformState.NOT_READY
        restart=m.restart('ai-service')
        assert not restart.recovered
        m.set_dependency(dependency, DependencyState.HEALTHY)
        assert m.snapshot().state is PlatformState.READY


def test_observability_failure_is_degraded_not_platform_outage():
    m=model(); m.set_dependency('otel_collector', DependencyState.FAILED)
    assert m.snapshot().state is PlatformState.DEGRADED
    assert not m.snapshot().ready
    m.set_dependency('otel_collector', DependencyState.HEALTHY)
    assert m.snapshot().state is PlatformState.READY


def test_restart_increments_generation_and_converges_when_dependencies_healthy():
    m=model()
    first=m.restart('gateway'); second=m.restart('gateway')
    assert first.recovered and second.recovered
    assert (first.before_generation, first.after_generation)==(0,1)
    assert (second.before_generation, second.after_generation)==(1,2)


def test_local_compose_has_production_parity_dependencies_and_ready_healthchecks():
    compose=yaml.safe_load((ROOT/'docker-compose.yml').read_text())
    services=compose['services']
    for name in POLICY['local_parity']['required_services']:
        assert name in services
    for name in ('postgres','redis','kafka','minio','keycloak'):
        assert 'healthcheck' in services[name]
    assert '/api/v1/health/ready' in json.dumps(services['gateway']['healthcheck'])
    assert '/health/ready' in json.dumps(services['ai-service']['healthcheck'])
