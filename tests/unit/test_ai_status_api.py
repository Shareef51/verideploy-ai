from fastapi.testclient import TestClient

from services.ai.main import app


def test_ai_status_is_private() -> None:
    with TestClient(app) as client:
        response = client.get("/internal/v1/ai/status")
    assert response.status_code == 401


def test_ai_status_is_sanitized() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/internal/v1/ai/status",
            headers={"x-internal-service": "verideploy-gateway"},
        )
    assert response.status_code == 200
    body = response.json()
    assert "api_key" not in body
    assert "secret" not in str(body).lower()
    assert body["provider"] in {"openai", "test"}
