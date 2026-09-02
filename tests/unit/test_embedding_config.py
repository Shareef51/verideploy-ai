from verideploy.config import Settings
from verideploy.rag.embeddings.factory import build_embedding_registry


def test_embedding_registry_uses_typed_configuration():
    settings = Settings(app_env="test", openai_embedding_model="embed-a", openai_embedding_dimensions=1536)
    spec = build_embedding_registry(settings).resolve("embed-a")
    assert spec.dimensions == 1536
    assert spec.registry_version == 1
