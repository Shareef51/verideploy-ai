from uuid import uuid4
import pytest
from pydantic import ValidationError
from verideploy.multimodal.schemas import IngestionCommand


def base(): return dict(job_id=uuid4(),tenant_id=uuid4(),requested_by=uuid4(),correlation_id=uuid4(),idempotency_key="safe-key-123",modality="video",original_filename="incident.mp4",detected_mime_type="video/mp4",size_bytes=100,sha256="c"*64,bucket="verideploy-evidence",object_key="tenants/t/incident.mp4")

def test_filename_path_is_rejected():
    data=base(); data["original_filename"]="../../secret.txt"
    with pytest.raises(ValidationError): IngestionCommand(**data)

def test_invalid_hash_is_rejected():
    data=base(); data["sha256"]="not-a-hash"
    with pytest.raises(ValidationError): IngestionCommand(**data)
