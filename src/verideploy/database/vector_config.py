from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field, model_validator


class HnswConfig(BaseModel):
    m: int = Field(ge=2, le=100)
    ef_construction: int = Field(ge=4, le=1000)


class VectorIndexConfig(BaseModel):
    index_version: str
    embedding_model: str
    dimensions: int = Field(gt=0)
    distance: str
    index_type: str
    hnsw: HnswConfig
    migration_revision: str

    @model_validator(mode="after")
    def validate(self) -> "VectorIndexConfig":
        if self.distance != "cosine":
            raise ValueError("configuration supports cosine distance only")
        if self.index_type != "hnsw":
            raise ValueError("configuration requires an HNSW index")
        return self


def load_vector_index_config(path: str | Path) -> VectorIndexConfig:
    return VectorIndexConfig.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def validate_embedding_settings(*, config: VectorIndexConfig, model: str, dimensions: int) -> None:
    if config.embedding_model != model or config.dimensions != dimensions:
        raise ValueError(
            "Embedding configuration does not match the active pgvector index migration; "
            "create a new re-embedding/index migration before changing model or dimensions"
        )
