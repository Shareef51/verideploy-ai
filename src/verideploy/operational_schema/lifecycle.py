from __future__ import annotations

from enum import StrEnum


class LifecycleKind(StrEnum):
    INVESTIGATION = "investigation"
    REVIEW = "review"
    EVALUATION = "evaluation"
    JOB = "job"


_TRANSITIONS: dict[LifecycleKind, dict[str, frozenset[str]]] = {
    LifecycleKind.INVESTIGATION: {
        "created": frozenset({"collecting", "cancelled"}),
        "collecting": frozenset({"analyzing", "waiting_for_evidence", "cancelled", "failed"}),
        "waiting_for_evidence": frozenset({"collecting", "cancelled", "failed"}),
        "analyzing": frozenset({"review_required", "completed", "failed", "cancelled"}),
        "review_required": frozenset({"completed", "collecting", "cancelled"}),
        "completed": frozenset(), "failed": frozenset(), "cancelled": frozenset(),
    },
    LifecycleKind.REVIEW: {
        "pending": frozenset({"in_review", "cancelled"}),
        "in_review": frozenset({"approved", "rejected", "changes_requested", "cancelled"}),
        "changes_requested": frozenset({"in_review", "cancelled"}),
        "approved": frozenset(), "rejected": frozenset(), "cancelled": frozenset(),
    },
    LifecycleKind.EVALUATION: {
        "queued": frozenset({"running", "cancelled"}),
        "running": frozenset({"passed", "failed", "cancelled"}),
        "passed": frozenset(), "failed": frozenset(), "cancelled": frozenset(),
    },
    LifecycleKind.JOB: {
        "queued": frozenset({"running", "cancelled"}),
        "running": frozenset({"succeeded", "failed", "retry_wait", "cancelled"}),
        "retry_wait": frozenset({"queued", "failed", "cancelled"}),
        "succeeded": frozenset(), "failed": frozenset(), "cancelled": frozenset(),
    },
}


class LifecycleTransitionError(ValueError):
    pass


def allowed_transitions(kind: LifecycleKind, state: str) -> frozenset[str]:
    try:
        return _TRANSITIONS[kind][state]
    except KeyError as exc:
        raise LifecycleTransitionError(f"unknown {kind.value} state: {state}") from exc


def validate_transition(kind: LifecycleKind, current: str, target: str) -> None:
    if target == current:
        return
    allowed = allowed_transitions(kind, current)
    if target not in allowed:
        raise LifecycleTransitionError(f"invalid {kind.value} transition: {current} -> {target}")
