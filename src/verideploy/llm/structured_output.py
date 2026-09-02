from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from verideploy.llm.contracts import AIRequest, AIResult
from verideploy.llm.responses import AIJSONSchemaFormat

T = TypeVar("T", bound=BaseModel)
_SCHEMA_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_SCHEMA_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


class StructuredOutputError(RuntimeError):
    pass


class UnknownStructuredSchemaError(StructuredOutputError):
    pass


class StructuredOutputValidationError(StructuredOutputError):
    def __init__(self, message: str, *, schema_name: str, schema_version: str, errors: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.schema_name = schema_name
        self.schema_version = schema_version
        self.errors = errors


class StructuredValidationAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["accepted"] = "accepted"
    schema_name: str
    schema_version: str
    local_repair_applied: bool


class StructuredValidationRejected(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["rejected"] = "rejected"
    schema_name: str
    schema_version: str
    error_count: int = Field(ge=1)


StructuredValidationOutcome = Annotated[
    StructuredValidationAccepted | StructuredValidationRejected,
    Field(discriminator="status"),
]
STRUCTURED_VALIDATION_OUTCOME_ADAPTER = TypeAdapter(StructuredValidationOutcome)


class StructuredOutputTelemetryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str
    tenant_id: str
    operation: str
    schema_name: str
    schema_version: str
    attempt: int = Field(ge=1)
    outcome: Literal["valid", "invalid", "locally_repaired", "retry_exhausted"]
    error_count: int = Field(ge=0)
    latency_ms: float = Field(ge=0)


class StructuredOutputTelemetry:
    def __init__(self) -> None:
        self.events: list[StructuredOutputTelemetryEvent] = []

    def emit(self, event: StructuredOutputTelemetryEvent) -> None:
        self.events.append(event)


class StructuredOutputRepairPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_provider_attempts: int = Field(default=2, ge=1, le=3)
    allow_local_json_unwrap: bool = True


@dataclass(frozen=True)
class StructuredSchemaDefinition:
    name: str
    version: str
    model: type[BaseModel]
    description: str | None = None

    @property
    def key(self) -> str:
        return f"{self.name}@{self.version}"

    def json_schema(self) -> dict[str, Any]:
        schema = self.model.model_json_schema(mode="validation")
        _enforce_closed_objects(schema)
        return schema

    def provider_format(self) -> AIJSONSchemaFormat:
        return AIJSONSchemaFormat(
            name=self.name,
            description=self.description,
            schema=self.json_schema(),
            strict=True,
        )


class StructuredSchemaRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, StructuredSchemaDefinition] = {}

    def register(
        self,
        *,
        name: str,
        version: str,
        model: type[T],
        description: str | None = None,
    ) -> StructuredSchemaDefinition:
        if not _SCHEMA_NAME.fullmatch(name):
            raise ValueError("schema name must match ^[A-Za-z][A-Za-z0-9_-]{0,63}$")
        if not _SCHEMA_VERSION.fullmatch(version):
            raise ValueError("schema version must use semantic x.y.z format")
        definition = StructuredSchemaDefinition(name=name, version=version, model=model, description=description)
        existing = self._definitions.get(definition.key)
        if existing and existing.model is not model:
            raise ValueError(f"schema already registered with different model: {definition.key}")
        self._definitions[definition.key] = definition
        return definition

    def get(self, name: str, version: str) -> StructuredSchemaDefinition:
        try:
            return self._definitions[f"{name}@{version}"]
        except KeyError as exc:
            raise UnknownStructuredSchemaError(f"unknown structured schema: {name}@{version}") from exc

    def definitions(self) -> tuple[StructuredSchemaDefinition, ...]:
        return tuple(sorted(self._definitions.values(), key=lambda item: item.key))

    def export_json_schemas(self, directory: Path) -> list[Path]:
        directory.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        manifest: list[dict[str, str]] = []
        for definition in self.definitions():
            filename = f"{definition.name}.v{definition.version}.schema.json"
            path = directory / filename
            path.write_text(json.dumps(definition.json_schema(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
            written.append(path)
            manifest.append({"name": definition.name, "version": definition.version, "file": filename})
        manifest_path = directory / "manifest.json"
        manifest_path.write_text(json.dumps({"schemas": manifest}, indent=2) + "\n", encoding="utf-8")
        written.append(manifest_path)
        return written

    def export_typescript(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "/* AUTO-GENERATED by VeriDeploy structured-output registry. DO NOT EDIT. */",
            "",
        ]
        for definition in self.definitions():
            schema = definition.json_schema()
            type_name = _pascal_case(definition.name) + "V" + definition.version.replace(".", "_")
            lines.append(f"export type {type_name} = {_schema_to_ts(schema, schema)};")
            lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")
        return path


class StructuredOutputEngine:
    def __init__(
        self,
        *,
        registry: StructuredSchemaRegistry,
        gateway: Any,
        telemetry: StructuredOutputTelemetry | None = None,
    ) -> None:
        self._registry = registry
        self._gateway = gateway
        self._telemetry = telemetry or StructuredOutputTelemetry()

    @property
    def telemetry(self) -> StructuredOutputTelemetry:
        return self._telemetry

    def ensure_schema(self, *, name: str, version: str, model: type[BaseModel]) -> StructuredSchemaDefinition:
        """Public, idempotent schema-registration boundary for model adapters."""
        try:
            return self._registry.get(name, version)
        except UnknownStructuredSchemaError:
            return self._registry.register(name=name, version=version, model=model)

    async def execute(
        self,
        request: AIRequest,
        *,
        schema_name: str,
        schema_version: str,
        policy: StructuredOutputRepairPolicy | None = None,
    ) -> tuple[AIResult, BaseModel, StructuredValidationOutcome]:
        selected_policy = policy or StructuredOutputRepairPolicy()
        definition = self._registry.get(schema_name, schema_version)
        last_error: StructuredOutputValidationError | None = None
        for attempt in range(1, selected_policy.max_provider_attempts + 1):
            started = time.perf_counter()
            routed = request.model_copy(
                update={
                    "structured_output": definition.provider_format(),
                    "defer_response_persistence": True,
                    "instructions": self._instructions(request.instructions, definition, retry=attempt > 1),
                }
            )
            result = await self._gateway.execute(routed)
            try:
                parsed, repaired = validate_structured_text(
                    definition,
                    result.output_text,
                    allow_local_json_unwrap=selected_policy.allow_local_json_unwrap,
                )
                self._emit(request, definition, attempt, "locally_repaired" if repaired else "valid", 0, started)
                persist = getattr(self._gateway, "persist_validated_response", None)
                if persist is not None:
                    await persist(request=routed, result=result)
                outcome = StructuredValidationAccepted(
                    schema_name=schema_name,
                    schema_version=schema_version,
                    local_repair_applied=repaired,
                )
                return result, parsed, outcome
            except StructuredOutputValidationError as exc:
                last_error = exc
                self._emit(request, definition, attempt, "invalid", len(exc.errors), started)
        assert last_error is not None
        self._emit(
            request,
            definition,
            selected_policy.max_provider_attempts,
            "retry_exhausted",
            len(last_error.errors),
            time.perf_counter(),
            latency_override=0,
        )
        raise last_error

    def _emit(
        self,
        request: AIRequest,
        definition: StructuredSchemaDefinition,
        attempt: int,
        outcome: Literal["valid", "invalid", "locally_repaired", "retry_exhausted"],
        error_count: int,
        started: float,
        *,
        latency_override: float | None = None,
    ) -> None:
        self._telemetry.emit(
            StructuredOutputTelemetryEvent(
                request_id=str(request.request_id),
                tenant_id=str(request.tenant_id),
                operation=request.operation,
                schema_name=definition.name,
                schema_version=definition.version,
                attempt=attempt,
                outcome=outcome,
                error_count=error_count,
                latency_ms=(time.perf_counter() - started) * 1000 if latency_override is None else latency_override,
            )
        )

    @staticmethod
    def _instructions(current: str | None, definition: StructuredSchemaDefinition, *, retry: bool) -> str:
        guard = (
            f"Return only data matching structured schema {definition.name}@{definition.version}. "
            "Do not add keys not present in the schema and do not wrap the response in Markdown."
        )
        if retry:
            guard += " The previous provider output failed local schema validation; produce a fresh schema-valid response."
        return f"{current}\n\n{guard}" if current else guard


def validate_structured_text(
    definition: StructuredSchemaDefinition,
    text: str,
    *,
    allow_local_json_unwrap: bool = True,
) -> tuple[BaseModel, bool]:
    candidates = [(text, False)]
    if allow_local_json_unwrap:
        unwrapped = _unwrap_json(text)
        if unwrapped is not None and unwrapped != text:
            candidates.append((unwrapped, True))
    last_errors: list[dict[str, Any]] = [{"type": "json_invalid", "msg": "response is not valid schema JSON"}]
    for candidate, repaired in candidates:
        try:
            return definition.model.model_validate_json(candidate), repaired
        except ValidationError as exc:
            last_errors = _safe_validation_errors(exc)
        except ValueError as exc:
            last_errors = [{"type": "json_invalid", "msg": str(exc)[:240]}]
    raise StructuredOutputValidationError(
        "structured output failed validation",
        schema_name=definition.name,
        schema_version=definition.version,
        errors=last_errors,
    )


def _safe_validation_errors(exc: ValidationError) -> list[dict[str, Any]]:
    safe: list[dict[str, Any]] = []
    for item in exc.errors(include_input=False, include_context=False, include_url=False):
        safe.append({"type": str(item.get("type", "validation_error")), "loc": list(item.get("loc", ())), "msg": str(item.get("msg", ""))[:240]})
    return safe[:50]


def _unwrap_json(text: str) -> str | None:
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        body = stripped[3:-3].strip()
        if body.lower().startswith("json"):
            body = body[4:].lstrip()
        return body
    first = min((idx for idx in (stripped.find("{"), stripped.find("[")) if idx >= 0), default=-1)
    if first < 0:
        return None
    opener = stripped[first]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escaped = False
    for idx in range(first, len(stripped)):
        char = stripped[idx]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return stripped[first : idx + 1]
    return None


def _enforce_closed_objects(schema: dict[str, Any]) -> None:
    if schema.get("type") == "object" or "properties" in schema:
        schema["additionalProperties"] = False
    for key in ("properties", "$defs"):
        value = schema.get(key)
        if isinstance(value, dict):
            for child in value.values():
                if isinstance(child, dict):
                    _enforce_closed_objects(child)
    items = schema.get("items")
    if isinstance(items, dict):
        _enforce_closed_objects(items)
    for key in ("anyOf", "oneOf", "allOf", "prefixItems"):
        value = schema.get(key)
        if isinstance(value, list):
            for child in value:
                if isinstance(child, dict):
                    _enforce_closed_objects(child)


def _pascal_case(value: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in re.split(r"[^A-Za-z0-9]+", value) if part) or "Schema"


def _schema_to_ts(schema: dict[str, Any], root: dict[str, Any]) -> str:
    if "$ref" in schema:
        ref = str(schema["$ref"])
        if ref.startswith("#/$defs/"):
            target = root.get("$defs", {}).get(ref.split("/")[-1])
            if isinstance(target, dict):
                return _schema_to_ts(target, root)
    if "const" in schema:
        return json.dumps(schema["const"])
    if "enum" in schema:
        return " | ".join(json.dumps(value) for value in schema["enum"])
    if "anyOf" in schema:
        return " | ".join(_schema_to_ts(item, root) for item in schema["anyOf"])
    kind = schema.get("type")
    if isinstance(kind, list):
        mapping = {"string": "string", "integer": "number", "number": "number", "boolean": "boolean", "null": "null"}
        return " | ".join(mapping.get(item, "unknown") for item in kind)
    if kind == "object" or "properties" in schema:
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))
        fields = []
        for name, child in properties.items():
            optional = "" if name in required else "?"
            fields.append(f"{json.dumps(name)}{optional}: {_schema_to_ts(child, root)}")
        return "{ " + "; ".join(fields) + " }"
    if kind == "array":
        return f"Array<{_schema_to_ts(schema.get('items', {}), root)}>"
    return {"string": "string", "integer": "number", "number": "number", "boolean": "boolean", "null": "null"}.get(kind, "unknown")
