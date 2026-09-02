from verideploy.config import Settings
from verideploy.observability.telemetry import _safe_attributes, inject_kafka_headers

def test_sensitive_span_attributes_are_dropped():
    out=_safe_attributes({"tenant_id":"t1","authorization":"Bearer secret","prompt":"private","latency_ms":12})
    assert out=={"tenant_id":"t1","latency_ms":12}

def test_disabled_otel_is_valid_configuration():
    s=Settings(app_env="test", ai_provider="test", otel_enabled=False, database_url="sqlite+pysqlite:///:memory:")
    assert s.otel_enabled is False

def test_kafka_header_injection_preserves_existing_headers():
    headers=inject_kafka_headers([("schema-version",b"1.0")])
    assert ("schema-version",b"1.0") in headers
