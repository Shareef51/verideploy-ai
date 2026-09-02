from __future__ import annotations
from dataclasses import dataclass


class QueryBudgetError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class QueryBudget:
    statement_timeout_ms: int = 15_000
    lock_timeout_ms: int = 2_000
    idle_in_transaction_timeout_ms: int = 30_000

    def __post_init__(self) -> None:
        for name, value, low, high in (
            ('statement_timeout_ms', self.statement_timeout_ms, 100, 600_000),
            ('lock_timeout_ms', self.lock_timeout_ms, 50, 120_000),
            ('idle_in_transaction_timeout_ms', self.idle_in_transaction_timeout_ms, 1_000, 900_000),
        ):
            if not low <= value <= high:
                raise QueryBudgetError(f'{name} must be between {low} and {high}')
        if self.lock_timeout_ms > self.statement_timeout_ms:
            raise QueryBudgetError('lock_timeout_ms cannot exceed statement_timeout_ms')
