from __future__ import annotations

from threading import RLock

from verideploy.rag.embeddings.errors import EmbeddingConfigurationError, EmbeddingDimensionDriftError
from verideploy.rag.embeddings.schemas import EmbeddingModelSpec


class EmbeddingModelRegistry:
    """Versioned model/dimension registry. Existing bindings cannot drift silently."""

    def __init__(self, specs: list[EmbeddingModelSpec] | None = None) -> None:
        self._specs: dict[str, EmbeddingModelSpec] = {}
        self._lock = RLock()
        for spec in specs or []:
            self.register(spec)

    def register(self, spec: EmbeddingModelSpec) -> EmbeddingModelSpec:
        with self._lock:
            existing = self._specs.get(spec.model)
            if existing and existing.dimensions != spec.dimensions:
                raise EmbeddingDimensionDriftError(
                    f"embedding model {spec.model!r} already registered at {existing.dimensions} dimensions; "
                    f"requested {spec.dimensions}. Create a migration/re-embedding plan instead."
                )
            if existing and spec.registry_version < existing.registry_version:
                raise EmbeddingConfigurationError("embedding registry version cannot move backwards")
            self._specs[spec.model] = spec
            return spec

    def resolve(self, model: str, requested_dimensions: int | None = None) -> EmbeddingModelSpec:
        spec = self._specs.get(model)
        if spec is None or not spec.enabled:
            raise EmbeddingConfigurationError(f"embedding model not registered/enabled: {model}")
        if requested_dimensions is None:
            return spec
        if not spec.supports_dimensions_override and requested_dimensions != spec.dimensions:
            raise EmbeddingConfigurationError(f"embedding model {model} does not allow dimension override")
        if requested_dimensions != spec.dimensions:
            raise EmbeddingDimensionDriftError(
                f"requested dimensions {requested_dimensions} do not match registry dimensions {spec.dimensions} for {model}"
            )
        return spec

    def list(self) -> list[EmbeddingModelSpec]:
        return sorted(self._specs.values(), key=lambda item: item.model)
