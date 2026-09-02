from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from verideploy.llm.contracts import AIRequest
from verideploy.llm.openai_provider import OpenAIProvider
from verideploy.llm.responses import AIInputImage, AIInputText, AIMessageInput


class FakeResponses:
    def __init__(self):
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            id="resp-image-1",
            status="completed",
            output_text="{}",
            output=[],
            usage=SimpleNamespace(input_tokens=10, output_tokens=2, total_tokens=12),
        )


class FakeClient:
    def __init__(self):
        self.responses = FakeResponses()


@pytest.mark.asyncio
async def test_openai_responses_adapter_maps_image_content_and_detail() -> None:
    client = FakeClient()
    provider = OpenAIProvider(api_key="test-only", timeout_seconds=1, client=client)
    request = AIRequest(
        tenant_id=uuid4(),
        correlation_id="corr-image",
        operation="image_dashboard_analysis",
        model="configured-model",
        input=[
            AIMessageInput(
                role="user",
                content=[
                    AIInputText(text="Analyze this image"),
                    AIInputImage(image_url="data:image/png;base64,AA==", detail="high"),
                ],
            )
        ],
    )
    await provider.execute(request)
    content = client.responses.calls[0]["input"][0]["content"]
    assert content[0] == {"type": "input_text", "text": "Analyze this image"}
    assert content[1]["type"] == "input_image"
    assert content[1]["image_url"] == "data:image/png;base64,AA=="
    assert content[1]["detail"] == "high"
