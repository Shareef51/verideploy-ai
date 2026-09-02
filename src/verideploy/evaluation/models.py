from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class SourceRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    source_type: str
    required: bool = True
    locator: str | None = None
    rationale: str | None = None


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    category: str
    input: dict[str, Any]
    expected: dict[str, Any]
    ground_truth: dict[str, Any] = Field(default_factory=dict)
    source_requirements: list[SourceRequirement] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DatasetManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    version: str
    schema_version: str = "1.0"
    description: str
    created_at: datetime
    content_sha256: str
    case_count: int
    categories: dict[str, int]
    source_file: str


class EvaluationScore(BaseModel):
    evaluator: str
    score: float = Field(ge=0.0, le=1.0)
    passed: bool
    details: dict[str, Any] = Field(default_factory=dict)


class CaseResult(BaseModel):
    case_id: str
    category: str
    output: dict[str, Any]
    scores: list[EvaluationScore]
    passed: bool
    latency_ms: float = Field(ge=0.0)
    error: str | None = None


class ReproducibilityMetadata(BaseModel):
    python_version: str
    platform: str
    git_commit: str | None
    git_dirty: bool | None
    seed: int
    dependency_fingerprint: str
    environment: str


class RunManifest(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    dataset_id: str
    dataset_version: str
    dataset_sha256: str
    evaluator_names: list[str]
    runner_name: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    status: Literal["running", "completed", "failed"] = "running"
    total_cases: int = 0
    passed_cases: int = 0
    failed_cases: int = 0
    aggregate_score: float = 0.0
    reproducibility: ReproducibilityMetadata
    metadata: dict[str, Any] = Field(default_factory=dict)


class BaselineComparison(BaseModel):
    baseline_run_id: str
    candidate_run_id: str
    baseline_score: float
    candidate_score: float
    delta: float
    regression: bool
    tolerance: float
