from __future__ import annotations

import io
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from PIL import Image, PngImagePlugin
from pydantic import ValidationError

from verideploy.llm.contracts import AIProviderName, AIResult, AIUsage
from verideploy.llm.responses import AIResponseStatus
from verideploy.multimodal.image_intelligence import (
    EvidenceLocator,
    ImageAnalysisResult,
    ImageAnalysisType,
    ImageDetail,
    ImageIntelligenceService,
    ImagePreparationPolicy,
    SecureImagePreparer,
    VisualObservation,
)


def png_bytes(*, width: int = 1200, height: int = 800, metadata: bool = False) -> bytes:
    image = Image.new("RGB", (width, height), (240, 245, 250))
    out = io.BytesIO()
    info = PngImagePlugin.PngInfo()
    if metadata:
        info.add_text("Comment", "secret-metadata-must-not-survive")
    image.save(out, format="PNG", pnginfo=info)
    return out.getvalue()


class EchoVisualGateway:
    def __init__(self, *, wrong_image_id: bool = False):
        self.request = None
        self.wrong_image_id = wrong_image_id

    async def execute(self, request):
        self.request = request
        image_id = str(uuid4()) if self.wrong_image_id else request.metadata["image_id"]
        payload = {
            "analysis_type": request.metadata["analysis_type"],
            "image_id": image_id,
            "summary": "Observed a synthetic operational screen.",
            "observations": [
                {
                    "observation_id": "obs-1",
                    "image_id": image_id,
                    "statement": "A rectangular dashboard panel is visible.",
                    "confidence": 0.98,
                    "locator": {"x_min": 0.1, "y_min": 0.1, "x_max": 0.9, "y_max": 0.9},
                }
            ],
            "inferences": [
                {
                    "inference_id": "inf-1",
                    "statement": "The screen is likely an operations dashboard.",
                    "confidence": 0.75,
                    "based_on_observation_ids": ["obs-1"],
                }
            ],
            "limitations": ["Synthetic fixture contains no readable metric values."],
        }
        return AIResult(
            request_id=request.request_id,
            provider=AIProviderName.TEST,
            model="test-model",
            output_text=json.dumps(payload),
            response_status=AIResponseStatus.COMPLETED,
            usage=AIUsage(input_tokens=1, output_tokens=1, total_tokens=2),
            latency_ms=1,
            attempts=1,
        )


def preparer(**overrides) -> SecureImagePreparer:
    return SecureImagePreparer(ImagePreparationPolicy(**overrides))


def test_secure_preparer_sanitizes_metadata_and_records_provenance() -> None:
    tenant = uuid4()
    raw = png_bytes(metadata=True)
    prepared = preparer().prepare(
        tenant_id=tenant,
        source_object_ref="s3://bucket/object.png",
        source_type="uploaded_image",
        raw_bytes=raw,
        analysis_type=ImageAnalysisType.DASHBOARD,
    )
    assert prepared.provenance.tenant_id == tenant
    assert prepared.provenance.mime_type == "image/png"
    assert prepared.provenance.original_sha256 != prepared.provenance.prepared_sha256
    assert prepared.provenance.detail is ImageDetail.AUTO
    with Image.open(io.BytesIO(prepared.bytes_data)) as image:
        assert "Comment" not in image.info


def test_dense_dashboard_selects_high_detail_by_default() -> None:
    prepared = preparer().prepare(
        tenant_id=uuid4(),
        source_object_ref="object",
        source_type="synthetic_fixture",
        raw_bytes=png_bytes(width=2000, height=1200),
        analysis_type=ImageAnalysisType.DASHBOARD,
    )
    assert prepared.provenance.detail is ImageDetail.HIGH


def test_original_detail_requires_explicit_policy_enablement() -> None:
    with pytest.raises(ValueError, match="original image detail is disabled"):
        preparer().prepare(
            tenant_id=uuid4(),
            source_object_ref="object",
            source_type="synthetic_fixture",
            raw_bytes=png_bytes(),
            analysis_type=ImageAnalysisType.ARCHITECTURE,
            requested_detail=ImageDetail.ORIGINAL,
        )


def test_secure_preparer_rejects_non_image_content() -> None:
    with pytest.raises(ValueError, match="not a supported decodable image"):
        preparer().prepare(
            tenant_id=uuid4(),
            source_object_ref="object",
            source_type="uploaded_image",
            raw_bytes=b"this is not an image",
            analysis_type=ImageAnalysisType.ERROR_SCREEN,
        )


def test_normalized_locator_rejects_inverted_bounds() -> None:
    with pytest.raises(ValidationError):
        EvidenceLocator(x_min=0.9, y_min=0.1, x_max=0.2, y_max=0.8)


def test_numeric_observation_requires_uncertainty() -> None:
    with pytest.raises(ValidationError, match="numeric visual observations require"):
        VisualObservation(
            observation_id="obs-1",
            image_id=uuid4(),
            statement="Chart appears to show 91.",
            confidence=0.5,
            numeric_value=91,
        )


def test_analysis_rejects_inference_without_observation_support() -> None:
    image_id = uuid4()
    with pytest.raises(ValidationError, match="unknown observations"):
        ImageAnalysisResult.model_validate(
            {
                "analysis_type": "dashboard",
                "image_id": str(image_id),
                "summary": "summary",
                "observations": [],
                "inferences": [
                    {
                        "inference_id": "i1",
                        "statement": "Anomaly caused the incident",
                        "confidence": 0.6,
                        "based_on_observation_ids": ["missing"],
                    }
                ],
                "limitations": [],
            }
        )


@pytest.mark.asyncio
async def test_service_builds_sanitized_data_url_and_untrusted_image_prompt() -> None:
    gateway = EchoVisualGateway()
    service = ImageIntelligenceService(gateway, preparer())
    provenance, result = await service.analyze(
        tenant_id=uuid4(),
        correlation_id="corr-image",
        source_object_ref="s3://evidence/fixture.png",
        source_type="synthetic_fixture",
        raw_bytes=png_bytes(),
        analysis_type=ImageAnalysisType.ERROR_SCREEN,
    )
    assert result.image_id == provenance.image_id
    request = gateway.request
    assert request is not None
    message = request.input[0]
    assert "UNTRUSTED visual evidence" in message.content[0].text
    assert message.content[1].image_url.startswith("data:image/png;base64,")
    assert message.content[1].detail == "high"


@pytest.mark.asyncio
async def test_service_rejects_provider_image_id_forgery() -> None:
    service = ImageIntelligenceService(EchoVisualGateway(wrong_image_id=True), preparer())
    with pytest.raises(ValueError, match="does not match provenance"):
        await service.analyze(
            tenant_id=uuid4(),
            correlation_id="corr-image",
            source_object_ref="object",
            source_type="synthetic_fixture",
            raw_bytes=png_bytes(),
            analysis_type=ImageAnalysisType.DASHBOARD,
        )
