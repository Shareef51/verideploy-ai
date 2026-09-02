from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Callable

_LITERAL = re.compile(r"'(?:''|[^'])*'|\b\d+(?:\.\d+)?\b")
_WS = re.compile(r'\s+')


def sql_fingerprint(statement: str) -> str:
    normalized = _WS.sub(' ', _LITERAL.sub('?', statement)).strip().lower()
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


@dataclass(frozen=True, slots=True)
class SlowQuerySample:
    fingerprint: str
    duration_ms: float
    rowcount: int | None
    operation: str
    observed_at: datetime


class SlowQueryTelemetry:
    def __init__(self, threshold_ms: float = 750.0, *, sink: Callable[[SlowQuerySample], None] | None = None, max_samples: int = 1_000) -> None:
        if threshold_ms <= 0:
            raise ValueError('threshold_ms must be positive')
        if max_samples < 1:
            raise ValueError('max_samples must be positive')
        self.threshold_ms = threshold_ms
        self._sink = sink
        self._max_samples = max_samples
        self._samples: list[SlowQuerySample] = []
        self._lock = Lock()

    def record(self, statement: str, *, duration_ms: float, rowcount: int | None = None) -> SlowQuerySample | None:
        if duration_ms < self.threshold_ms:
            return None
        operation = statement.lstrip().split(None, 1)[0].upper() if statement.strip() else 'UNKNOWN'
        sample = SlowQuerySample(
            fingerprint=sql_fingerprint(statement), duration_ms=round(float(duration_ms), 3),
            rowcount=rowcount if rowcount is None or rowcount >= 0 else None,
            operation=operation, observed_at=datetime.now(timezone.utc),
        )
        if self._sink is not None:
            self._sink(sample)
        with self._lock:
            self._samples.append(sample)
            if len(self._samples) > self._max_samples:
                del self._samples[: len(self._samples) - self._max_samples]
        return sample

    def snapshot(self) -> tuple[SlowQuerySample, ...]:
        with self._lock:
            return tuple(self._samples)
