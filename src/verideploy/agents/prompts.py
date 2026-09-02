from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


@dataclass(frozen=True)
class PromptDefinition:
    name: str
    version: str
    text: str
    sha256: str
    path: Path


class PromptRegistry:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], PromptDefinition] = {}

    def register_file(self, *, name: str, version: str, path: str | Path) -> PromptDefinition:
        if not _VERSION.fullmatch(version):
            raise ValueError("prompt version must use semantic x.y.z format")
        source = Path(path)
        text = source.read_text(encoding="utf-8").strip()
        if not text:
            raise ValueError("prompt file must not be blank")
        key = (name, version)
        definition = PromptDefinition(name, version, text, hashlib.sha256(text.encode()).hexdigest(), source)
        existing = self._items.get(key)
        if existing and existing.sha256 != definition.sha256:
            raise ValueError(f"prompt already registered with different content: {name}@{version}")
        self._items[key] = definition
        return definition

    def get(self, name: str, version: str) -> PromptDefinition:
        try:
            return self._items[(name, version)]
        except KeyError as exc:
            raise KeyError(f"unknown prompt: {name}@{version}") from exc


def build_prompt_registry(root: str | Path = ".") -> PromptRegistry:
    root = Path(root)
    registry = PromptRegistry()
    for name in ("supervisor", "planner", "github"):
        registry.register_file(name=name, version="1.0.0", path=root / "prompts" / name / "v1.0.0.txt")
    # RAG Agent extends routing/planning without mutating historical prompt versions.
    registry.register_file(name="supervisor", version="1.1.0", path=root / "prompts" / "supervisor" / "v1.1.0.txt")
    registry.register_file(name="planner", version="1.1.0", path=root / "prompts" / "planner" / "v1.1.0.txt")
    registry.register_file(name="rag", version="1.0.0", path=root / "prompts" / "rag" / "v1.0.0.txt")
    # Visual Evidence Agent extends routing/planning without mutating earlier prompt versions.
    registry.register_file(name="supervisor", version="1.2.0", path=root / "prompts" / "supervisor" / "v1.2.0.txt")
    registry.register_file(name="planner", version="1.2.0", path=root / "prompts" / "planner" / "v1.2.0.txt")
    registry.register_file(name="visual_evidence", version="1.0.0", path=root / "prompts" / "visual_evidence" / "v1.0.0.txt")
    # Runtime Evidence Agent adds runtime evidence without mutating earlier prompt versions.
    registry.register_file(name="supervisor", version="1.3.0", path=root / "prompts" / "supervisor" / "v1.3.0.txt")
    registry.register_file(name="planner", version="1.3.0", path=root / "prompts" / "planner" / "v1.3.0.txt")
    registry.register_file(name="runtime_evidence", version="1.0.0", path=root / "prompts" / "runtime_evidence" / "v1.0.0.txt")
    # RCA Agent adds RCA without mutating earlier prompt versions.
    registry.register_file(name="supervisor", version="1.4.0", path=root / "prompts" / "supervisor" / "v1.4.0.txt")
    registry.register_file(name="planner", version="1.4.0", path=root / "prompts" / "planner" / "v1.4.0.txt")
    registry.register_file(name="rca", version="1.0.0", path=root / "prompts" / "rca" / "v1.0.0.txt")
    # Critic Agent adds critic validation without mutating earlier prompt versions.
    registry.register_file(name="supervisor", version="1.5.0", path=root / "prompts" / "supervisor" / "v1.5.0.txt")
    registry.register_file(name="planner", version="1.5.0", path=root / "prompts" / "planner" / "v1.5.0.txt")
    registry.register_file(name="critic", version="1.0.0", path=root / "prompts" / "critic" / "v1.0.0.txt")
    registry.register_file(name="supervisor", version="1.6.0", path=root / "prompts" / "supervisor" / "v1.6.0.txt")
    registry.register_file(name="planner", version="1.6.0", path=root / "prompts" / "planner" / "v1.6.0.txt")
    return registry
