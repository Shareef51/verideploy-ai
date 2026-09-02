from __future__ import annotations

import re
from dataclasses import dataclass

from verideploy.knowledge.schemas import KnowledgeCategory


@dataclass(frozen=True)
class DocumentSection:
    text: str
    kind: str
    hierarchy_path: tuple[str, ...]


_HEADING = re.compile(r"^(#{1,6})\s+(.+)$", re.M)
_CODE = re.compile(r"^(?:async\s+)?(?:def|class|function|export\s+(?:async\s+)?function)\s+([A-Za-z_$][\w$]*)", re.M)
_LOG_TS = re.compile(r"(?m)^(?=\[?\d{4}-\d{2}-\d{2}[T ][0-9:.+-]+)")


def document_sections(content: str, *, category: KnowledgeCategory | str, max_chars: int = 1800) -> list[DocumentSection]:
    """Split on semantic document boundaries, retaining a navigable hierarchy path."""
    category_value = category.value if isinstance(category, KnowledgeCategory) else str(category)
    if category_value in {"service", "deployment"} and _CODE.search(content):
        return _split_markers(content, _CODE, "code_symbol", max_chars)
    if category_value in {"runbook", "postmortem", "architecture"}:
        kind = {"runbook": "runbook_heading", "postmortem": "rca_section", "architecture": "architecture_component"}[category_value]
        return _split_markers(content, _HEADING, kind, max_chars)
    if _LOG_TS.search(content):
        return _split_markers(content, _LOG_TS, "event_window", max_chars)
    return _bounded([DocumentSection(content.strip(), "document", ())], max_chars)


def _split_markers(content: str, pattern: re.Pattern[str], kind: str, max_chars: int) -> list[DocumentSection]:
    matches = list(pattern.finditer(content))
    if not matches:
        return _bounded([DocumentSection(content.strip(), kind, ())], max_chars)
    sections: list[DocumentSection] = []
    hierarchy: list[str] = []
    for index, match in enumerate(matches):
        start, end = match.start(), matches[index + 1].start() if index + 1 < len(matches) else len(content)
        label = (match.group(match.lastindex or 0) if match.lastindex else match.group(0)).strip("# []")
        if pattern is _HEADING:
            level = len(match.group(1)); hierarchy = hierarchy[:level - 1] + [match.group(2).strip()]
        else:
            hierarchy = [label]
        prefix = content[:start].strip() if index == 0 else ""
        body = "\n\n".join(x for x in (prefix, content[start:end].strip()) if x)
        if body:
            sections.append(DocumentSection(body, kind, tuple(hierarchy)))
    return _bounded(sections, max_chars)


def _bounded(sections: list[DocumentSection], max_chars: int) -> list[DocumentSection]:
    output: list[DocumentSection] = []
    for section in sections:
        paragraphs = [x.strip() for x in section.text.split("\n\n") if x.strip()]
        current = ""
        for paragraph in paragraphs:
            candidate = paragraph if not current else f"{current}\n\n{paragraph}"
            if current and len(candidate) > max_chars:
                output.append(DocumentSection(current, section.kind, section.hierarchy_path)); current = paragraph
            else:
                current = candidate
        if current:
            output.append(DocumentSection(current, section.kind, section.hierarchy_path))
    return output
