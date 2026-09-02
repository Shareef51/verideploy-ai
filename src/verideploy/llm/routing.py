from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping, Sequence


class ModelRole(StrEnum):
    FAST = "fast"
    STANDARD = "standard"
    REASONING = "reasoning"


_DEFAULT_OPERATION_ROLES: dict[str, ModelRole] = {
    "intent_classification": ModelRole.FAST,
    "query_rewriting": ModelRole.FAST,
    "metadata_extraction": ModelRole.FAST,
    "ordinary_tool_selection": ModelRole.FAST,
    "standard_rag": ModelRole.STANDARD,
    "release_risk": ModelRole.STANDARD,
    "evidence_fusion": ModelRole.STANDARD,
    "executive_report": ModelRole.STANDARD,
    "complex_rca": ModelRole.REASONING,
    "contradiction_resolution": ModelRole.REASONING,
}


@dataclass(frozen=True)
class ModelBinding:
    primary: str
    fallbacks: tuple[str, ...] = ()

    def ordered_models(self) -> tuple[str, ...]:
        seen: set[str] = set()
        ordered: list[str] = []
        for model in (self.primary, *self.fallbacks):
            candidate = model.strip()
            if candidate and candidate not in seen:
                seen.add(candidate)
                ordered.append(candidate)
        if not ordered:
            raise ValueError("model binding must contain at least one non-empty model")
        return tuple(ordered)


@dataclass(frozen=True)
class RoutingPolicy:
    bindings: Mapping[ModelRole, ModelBinding]
    operation_overrides: Mapping[str, ModelRole] = field(default_factory=dict)
    default_role: ModelRole = ModelRole.STANDARD
    allow_explicit_model_override: bool = False


@dataclass(frozen=True)
class RoutingDecision:
    role: ModelRole
    primary_model: str
    fallback_models: tuple[str, ...]
    reason: str
    policy_override: bool

    @property
    def ordered_models(self) -> tuple[str, ...]:
        return (self.primary_model, *self.fallback_models)


class ModelRouter:
    """Deterministic role router. Model identifiers are configuration, never routing logic."""

    def __init__(self, policy: RoutingPolicy) -> None:
        self._policy = policy
        missing = [role.value for role in ModelRole if role not in policy.bindings]
        if missing:
            raise ValueError(f"missing model bindings for roles: {', '.join(sorted(missing))}")
        for binding in policy.bindings.values():
            binding.ordered_models()

    def route(
        self,
        *,
        operation: str,
        requested_role: ModelRole | None = None,
        explicit_model: str | None = None,
    ) -> RoutingDecision:
        normalized = operation.strip().lower()
        if explicit_model:
            if not self._policy.allow_explicit_model_override:
                raise ValueError("explicit model override is disabled by routing policy")
            allowed_models = {model for binding in self._policy.bindings.values() for model in binding.ordered_models()}
            if explicit_model not in allowed_models:
                raise ValueError("explicit model override is not in configured model bindings")
            role = requested_role or self._role_for_operation(normalized)[0]
            return RoutingDecision(
                role=role,
                primary_model=explicit_model,
                fallback_models=(),
                reason="explicit_model_override",
                policy_override=True,
            )
        if requested_role is not None:
            role = requested_role
            reason = "requested_role_override"
            override = True
        else:
            role, reason = self._role_for_operation(normalized)
            override = normalized in self._policy.operation_overrides
        models = self._policy.bindings[role].ordered_models()
        return RoutingDecision(
            role=role,
            primary_model=models[0],
            fallback_models=models[1:],
            reason=reason,
            policy_override=override,
        )

    def _role_for_operation(self, operation: str) -> tuple[ModelRole, str]:
        if operation in self._policy.operation_overrides:
            return self._policy.operation_overrides[operation], "operation_policy_override"
        if operation in _DEFAULT_OPERATION_ROLES:
            return _DEFAULT_OPERATION_ROLES[operation], "deterministic_workload_rule"
        return self._policy.default_role, "default_role"
