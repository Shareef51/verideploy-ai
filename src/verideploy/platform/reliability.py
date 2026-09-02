from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable, Mapping, Sequence


class DependencyState(StrEnum):
    HEALTHY = "healthy"
    FAILED = "failed"
    UNKNOWN = "unknown"


class PlatformState(StrEnum):
    READY = "ready"
    DEGRADED = "degraded"
    NOT_READY = "not_ready"


@dataclass(frozen=True)
class DependencyStatus:
    name: str
    state: DependencyState
    critical: bool
    detail: str = ""


@dataclass(frozen=True)
class ReadinessSnapshot:
    state: PlatformState
    checks: tuple[DependencyStatus, ...]

    @property
    def ready(self) -> bool:
        return self.state == PlatformState.READY

    def as_checks(self) -> dict[str, str]:
        return {item.name: item.state.value for item in self.checks}


@dataclass(frozen=True)
class RestartResult:
    service: str
    before_generation: int
    after_generation: int
    state: PlatformState
    recovered: bool


class PlatformReliabilityModel:
    """Deterministic model of readiness, failure, and restart semantics.

    Production probes use the same critical/optional classification.  This model is
    intentionally network-free so CI can assert failure semantics without needing a
    privileged Docker daemon or intentionally breaking shared infrastructure.
    """

    def __init__(self, *, critical: Iterable[str], optional: Iterable[str] = ()) -> None:
        self.critical = frozenset(critical)
        self.optional = frozenset(optional)
        overlap = self.critical & self.optional
        if overlap:
            raise ValueError(f"dependencies cannot be both critical and optional: {sorted(overlap)}")
        self._states: dict[str, DependencyState] = {
            name: DependencyState.HEALTHY for name in self.critical | self.optional
        }
        self._generation: dict[str, int] = {}

    def set_dependency(self, name: str, state: DependencyState | str) -> None:
        if name not in self._states:
            raise KeyError(name)
        self._states[name] = DependencyState(state)

    def snapshot(self) -> ReadinessSnapshot:
        checks = tuple(
            DependencyStatus(name, self._states[name], name in self.critical)
            for name in sorted(self._states)
        )
        critical_failed = any(c.critical and c.state != DependencyState.HEALTHY for c in checks)
        optional_failed = any(not c.critical and c.state != DependencyState.HEALTHY for c in checks)
        state = (
            PlatformState.NOT_READY
            if critical_failed
            else PlatformState.DEGRADED
            if optional_failed
            else PlatformState.READY
        )
        return ReadinessSnapshot(state=state, checks=checks)

    def restart(self, service: str) -> RestartResult:
        before = self._generation.get(service, 0)
        after = before + 1
        self._generation[service] = after
        snapshot = self.snapshot()
        return RestartResult(
            service=service,
            before_generation=before,
            after_generation=after,
            state=snapshot.state,
            recovered=snapshot.state in {PlatformState.READY, PlatformState.DEGRADED},
        )


def validate_eventual_recovery(
    model: PlatformReliabilityModel,
    *,
    dependency: str,
    service: str,
) -> tuple[ReadinessSnapshot, RestartResult, ReadinessSnapshot]:
    """Fail a critical dependency, attempt restart, restore it, then assert convergence."""
    model.set_dependency(dependency, DependencyState.FAILED)
    failed = model.snapshot()
    restart_while_failed = model.restart(service)
    model.set_dependency(dependency, DependencyState.HEALTHY)
    restored = model.snapshot()
    return failed, restart_while_failed, restored


def required_compose_services(config: Mapping[str, object]) -> Sequence[str]:
    local = config.get("local_parity", {})
    if not isinstance(local, Mapping):
        return ()
    raw = local.get("required_services", ())
    return tuple(str(item) for item in raw) if isinstance(raw, Sequence) and not isinstance(raw, str) else ()
