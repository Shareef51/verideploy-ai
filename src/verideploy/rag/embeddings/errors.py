class EmbeddingError(RuntimeError):
    """Base embedding pipeline failure."""


class EmbeddingConfigurationError(EmbeddingError):
    pass


class EmbeddingDimensionDriftError(EmbeddingError):
    pass


class EmbeddingProviderError(EmbeddingError):
    def __init__(self, message: str, *, retryable: bool = False, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
