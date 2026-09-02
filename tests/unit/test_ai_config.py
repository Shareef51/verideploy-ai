from pydantic import ValidationError
import pytest
from verideploy.config import Settings


def test_production_rejects_process_local_ai_controls() -> None:
    with pytest.raises(ValidationError):
        Settings(
            app_env="production",
            app_secret_key="x" * 40,
            ai_control_backend="memory",
            openai_api_key="test",
        openai_fast_model="fast-model",
        openai_standard_model="standard-model",
        openai_reasoning_model="reasoning-model",
        )


def test_production_accepts_distributed_ai_controls() -> None:
    settings = Settings(
        app_env="production",
        app_secret_key="x" * 40,
        ai_control_backend="redis",
        openai_api_key="test",
        openai_fast_model="fast-model",
        openai_standard_model="standard-model",
        openai_reasoning_model="reasoning-model",
    )
    assert settings.ai_control_backend == "redis"
