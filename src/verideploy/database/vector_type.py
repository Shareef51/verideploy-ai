from __future__ import annotations

from sqlalchemy.types import UserDefinedType

try:
    from pgvector.sqlalchemy import Vector as PgVector  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised only in constrained build environments
    class PgVector(UserDefinedType):
        """DDL-compatible fallback; production installs pgvector-python from pyproject.toml."""

        cache_ok = True

        def __init__(self, dim: int) -> None:
            self.dim = dim

        def get_col_spec(self, **_: object) -> str:
            return f"VECTOR({self.dim})"


Vector = PgVector
