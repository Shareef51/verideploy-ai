from __future__ import annotations

import base64
import io
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image

from services.ai.image_intelligence import get_image_intelligence_service
from services.ai.main import app
from verideploy.multimodal.image_intelligence import (
    DashboardAnalysisResult,
    ImageAnalysisType,
    ImageDetail,
    ImageProvenance,
)


def image_b64() -> str:
    out = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(out, format="PNG")
    return base64.b64encode(out.getvalue()).decode("ascii")


class FakeImageService:
    async def analyze(self, **kwargs):
        tenant = kwargs["tenant_id"]
        image_id = uuid4()
        provenance = ImageProvenance(
            image_id=image_id,
            tenant_id=tenant,
            source_type=kwargs["source_type"],
            source_object_ref=kwargs["source_object_ref"],
            original_sha256="a" * 64,
            prepared_sha256="b" * 64,
            mime_type="image/png",
            width=64,
            height=64,
            detail=ImageDetail.HIGH,
        )
        analysis = DashboardAnalysisResult(
            analysis_type=kwargs["analysis_type"],
            image_id=image_id,
            summary="Validated result",
            observations=[],
            inferences=[],
            limitations=[],
        )
        return provenance, analysis


def payload(tenant):
    return {
        "tenant_id": str(tenant),
        "correlation_id": "corr-9",
        "source_object_ref": "s3://bucket/key.png",
        "source_type": "uploaded_image",
        "analysis_type": "dashboard",
        "image_base64": image_b64(),
    }


def test_image_analysis_api_requires_trusted_service() -> None:
    tenant = uuid4()
    app.dependency_overrides[get_image_intelligence_service] = lambda: FakeImageService()
    try:
        response = TestClient(app).post("/internal/v1/ai/images/analyze", json=payload(tenant))
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_image_analysis_api_enforces_tenant_header() -> None:
    tenant = uuid4()
    app.dependency_overrides[get_image_intelligence_service] = lambda: FakeImageService()
    try:
        response = TestClient(app).post(
            "/internal/v1/ai/images/analyze",
            json=payload(tenant),
            headers={
                "x-internal-service": "verideploy-multimodal-worker",
                "x-tenant-id": str(uuid4()),
            },
        )
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_image_analysis_api_returns_provenance_and_analysis() -> None:
    tenant = uuid4()
    app.dependency_overrides[get_image_intelligence_service] = lambda: FakeImageService()
    try:
        response = TestClient(app).post(
            "/internal/v1/ai/images/analyze",
            json=payload(tenant),
            headers={
                "x-internal-service": "verideploy-multimodal-worker",
                "x-tenant-id": str(tenant),
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["analysis"]["analysis_type"] == ImageAnalysisType.DASHBOARD.value
        assert body["analysis"]["image_id"] == body["provenance"]["image_id"]
    finally:
        app.dependency_overrides.clear()
