from fastapi.testclient import TestClient
from services.ai.main import app

def test_liveness() -> None:
    with TestClient(app) as client:
        r=client.get("/health/live")
    assert r.status_code==200
    assert r.json()["status"]=="ok"
    assert r.headers["x-correlation-id"]

def test_readiness() -> None:
    with TestClient(app) as client:
        r=client.get("/health/ready")
    assert r.status_code==200
    assert r.json()["status"]=="ready"
