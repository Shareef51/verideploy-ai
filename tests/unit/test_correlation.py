from uuid import uuid4
from fastapi.testclient import TestClient
from services.ai.main import app

def test_preserves_valid_correlation_id() -> None:
    value=str(uuid4())
    with TestClient(app) as client: r=client.get("/health/live",headers={"x-correlation-id":value})
    assert r.headers["x-correlation-id"]==value

def test_replaces_invalid_correlation_id() -> None:
    with TestClient(app) as client: r=client.get("/health/live",headers={"x-correlation-id":"not-a-uuid"})
    assert r.headers["x-correlation-id"]!="not-a-uuid"
