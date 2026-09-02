from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid5

from verideploy.knowledge.schemas import KnowledgeManifest, KnowledgeRetentionPolicy
from verideploy.rag.retrieval.corpus import RetrievalChunkInput, RetrievalDocumentInput
from verideploy.knowledge.document_chunking import document_sections

_CHUNK_NAMESPACE = UUID("9d47a333-79c5-43ba-a8e3-65ca3bcf02c6")


@dataclass(frozen=True)
class KnowledgeChunk:
    chunk_id: UUID
    document_id: UUID
    ordinal: int
    content: str
    content_sha256: str
    chunk_kind: str = "document"
    hierarchy_path: tuple[str, ...] = ()


class EngineeringKnowledgeCorpus:
    """Load a validated, file-backed engineering corpus without network access."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.manifest = KnowledgeManifest.model_validate_json((self.root / "manifest.json").read_text(encoding="utf-8"))
        self.retention = KnowledgeRetentionPolicy.model_validate_json((self.root / "retention-policy.json").read_text(encoding="utf-8"))

    def document_path(self, relative_path: str) -> Path:
        candidate = (self.root / relative_path).resolve()
        if self.root not in candidate.parents:
            raise ValueError("knowledge document path escapes corpus root")
        return candidate

    def read_document(self, relative_path: str) -> str:
        return self.document_path(relative_path).read_text(encoding="utf-8")

    @staticmethod
    def sha256(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def chunks(self, *, document_id: UUID, content: str, max_chars: int = 1800, category="general") -> list[KnowledgeChunk]:
        if max_chars < 256:
            raise ValueError("max_chars must be at least 256")
        grouped = document_sections(content, category=category, max_chars=max_chars)
        chunks: list[KnowledgeChunk] = []
        for ordinal, section in enumerate(grouped):
            text = section.text
            content_hash = self.sha256(text)
            chunk_id = uuid5(_CHUNK_NAMESPACE, f"{document_id}:{ordinal}:{content_hash}")
            chunks.append(KnowledgeChunk(chunk_id, document_id, ordinal, text, content_hash, section.kind, section.hierarchy_path))
        return chunks

    def retrieval_inputs(self) -> list[tuple[RetrievalDocumentInput, list[RetrievalChunkInput]]]:
        output: list[tuple[RetrievalDocumentInput, list[RetrievalChunkInput]]] = []
        for item in self.manifest.documents:
            content = self.read_document(item.path)
            document = RetrievalDocumentInput(
                document_id=item.document_id,
                tenant_id=self.manifest.tenant_id,
                source_key=item.provenance_uri,
                title=item.title,
                service=item.service,
                environment=item.environment,
                document_kind=item.retrieval_kind,
            )
            chunks = [
                RetrievalChunkInput(
                    chunk_id=chunk.chunk_id,
                    tenant_id=self.manifest.tenant_id,
                    document_id=item.document_id,
                    ordinal=chunk.ordinal,
                    content=chunk.content,
                    chunk_kind=chunk.chunk_kind,
                    hierarchy_path=chunk.hierarchy_path,
                )
                for chunk in self.chunks(document_id=item.document_id, content=content, category=item.category)
            ]
            output.append((document, chunks))
        return output

    def manifest_digest(self) -> str:
        canonical = json.dumps(self.manifest.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
