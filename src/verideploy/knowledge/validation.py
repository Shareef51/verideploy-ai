from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from verideploy.knowledge.corpus import EngineeringKnowledgeCorpus
from verideploy.knowledge.schemas import KnowledgeCategory, RetentionClass


@dataclass(frozen=True)
class CorpusValidationReport:
    valid: bool
    document_count: int
    categories: dict[str, int]
    retention_classes: dict[str, int]
    manifest_sha256: str
    errors: tuple[str, ...]


def validate_corpus(root: Path) -> CorpusValidationReport:
    corpus = EngineeringKnowledgeCorpus(root)
    errors: list[str] = []
    category_counts = Counter(item.category.value for item in corpus.manifest.documents)
    retention_counts = Counter(item.retention_class.value for item in corpus.manifest.documents)

    required = {item.value for item in KnowledgeCategory}
    missing_categories = sorted(required - set(category_counts))
    if missing_categories:
        errors.append(f"missing categories: {','.join(missing_categories)}")

    tracked_paths = {item.path for item in corpus.manifest.documents}
    actual_paths = {
        str(path.relative_to(root)).replace("\\", "/")
        for path in (root / "documents").glob("*.md")
        if path.is_file()
    }
    untracked = sorted(actual_paths - tracked_paths)
    missing_files = sorted(tracked_paths - actual_paths)
    if untracked:
        errors.append(f"untracked documents: {','.join(untracked)}")
    if missing_files:
        errors.append(f"missing documents: {','.join(missing_files)}")

    policy_classes = {item.retention_class for item in corpus.retention.rules}
    if policy_classes != set(RetentionClass):
        errors.append("retention policy does not cover all retention classes")

    for item in corpus.manifest.documents:
        path = corpus.document_path(item.path)
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8")
        digest = corpus.sha256(content)
        if digest != item.content_sha256:
            errors.append(f"hash mismatch: {item.path}")
        if item.category.value not in item.labels:
            errors.append(f"category label missing: {item.path}")
        if not item.lineage.synthetic:
            errors.append(f"non-synthetic lineage: {item.path}")
        if not item.provenance_uri.startswith("synthetic://verideploy/knowledge/"):
            errors.append(f"invalid provenance: {item.path}")
        if not content.startswith("# "):
            errors.append(f"missing markdown title: {item.path}")

    return CorpusValidationReport(
        valid=not errors,
        document_count=len(corpus.manifest.documents),
        categories=dict(sorted(category_counts.items())),
        retention_classes=dict(sorted(retention_counts.items())),
        manifest_sha256=corpus.manifest_digest(),
        errors=tuple(errors),
    )
