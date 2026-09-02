from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from verideploy.knowledge.corpus import EngineeringKnowledgeCorpus
from verideploy.knowledge.schemas import KnowledgeCategory, KnowledgeManifest
from verideploy.knowledge.validation import validate_corpus
from verideploy.rag.retrieval.schemas import RetrievalDocumentKind

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "data" / "knowledge"


def test_corpus_validation_gate_passes():
    report = validate_corpus(CORPUS)
    assert report.valid is True
    assert report.document_count == 8
    assert set(report.categories) == {item.value for item in KnowledgeCategory}
    assert report.errors == ()


def test_manifest_hashes_match_every_document():
    corpus = EngineeringKnowledgeCorpus(CORPUS)
    for item in corpus.manifest.documents:
        assert corpus.sha256(corpus.read_document(item.path)) == item.content_sha256


def test_every_document_has_labels_and_synthetic_provenance():
    corpus = EngineeringKnowledgeCorpus(CORPUS)
    for item in corpus.manifest.documents:
        assert item.category.value in item.labels
        assert item.lineage.synthetic is True
        assert item.lineage.source_system == "verideploy-synthetic-corpus"
        assert item.provenance_uri.startswith("synthetic://verideploy/knowledge/")


def test_retention_policy_covers_every_manifest_document():
    corpus = EngineeringKnowledgeCorpus(CORPUS)
    configured = {rule.retention_class for rule in corpus.retention.rules}
    assert configured == {item.retention_class for item in corpus.manifest.documents}


def test_manifest_rejects_duplicate_document_ids():
    payload = json.loads((CORPUS / "manifest.json").read_text())
    payload["documents"][1]["document_id"] = payload["documents"][0]["document_id"]
    with pytest.raises(ValueError, match="document IDs must be unique"):
        KnowledgeManifest.model_validate(payload)


def test_corpus_rejects_path_traversal():
    corpus = EngineeringKnowledgeCorpus(CORPUS)
    with pytest.raises(ValueError, match="escapes corpus root"):
        corpus.document_path("../secrets.md")


def test_retrieval_inputs_reuse_existing_rag_contract():
    corpus = EngineeringKnowledgeCorpus(CORPUS)
    items = corpus.retrieval_inputs()
    assert len(items) == 8
    doc, chunks = items[0]
    assert doc.tenant_id == UUID("00000000-0000-5000-8000-000000000027")
    assert doc.document_kind is RetrievalDocumentKind.ARCHITECTURE
    assert chunks
    assert all(chunk.tenant_id == doc.tenant_id for chunk in chunks)


def test_chunk_ids_are_deterministic_and_content_addressed():
    corpus = EngineeringKnowledgeCorpus(CORPUS)
    item = corpus.manifest.documents[0]
    content = corpus.read_document(item.path)
    first = corpus.chunks(document_id=item.document_id, content=content)
    second = corpus.chunks(document_id=item.document_id, content=content)
    assert first == second
    assert all(len(chunk.content_sha256) == 64 for chunk in first)


def test_document_aware_chunking_preserves_heading_hierarchy():
    corpus = EngineeringKnowledgeCorpus(CORPUS)
    chunks = corpus.chunks(document_id=uuid4(), content="# Checkout\n\nIntro\n\n## Recovery\n\n1. Roll back\n\n## Verify\n\nCheck metrics", category=KnowledgeCategory.RUNBOOK, max_chars=256)
    assert [x.chunk_kind for x in chunks] == ["runbook_heading"] * 3
    assert chunks[1].hierarchy_path == ("Checkout", "Recovery")


def test_no_untracked_markdown_documents_exist():
    corpus = EngineeringKnowledgeCorpus(CORPUS)
    tracked = {item.path for item in corpus.manifest.documents}
    actual = {f"documents/{path.name}" for path in (CORPUS / "documents").glob("*.md")}
    assert actual == tracked

@pytest.mark.asyncio
async def test_ingestor_is_idempotent_by_using_existing_upsert_contracts():
    from verideploy.knowledge.ingestion import KnowledgeCorpusIngestor

    class Writer:
        def __init__(self):
            self.documents = {}
            self.chunks = {}
        def upsert_document(self, item):
            self.documents[(item.tenant_id, item.source_key)] = item
        def upsert_chunk(self, item):
            self.chunks[(item.tenant_id, item.document_id, item.ordinal)] = item
            return "hash"

    corpus = EngineeringKnowledgeCorpus(CORPUS)
    writer = Writer()
    ingestor = KnowledgeCorpusIngestor(corpus=corpus, writer=writer)
    first = await ingestor.ingest()
    second = await ingestor.ingest()
    assert first == second
    assert first.documents_upserted == 8
    assert len(writer.documents) == 8
    assert len(writer.chunks) == first.chunks_upserted
    assert first.embeddings_requested == 0


@pytest.mark.asyncio
async def test_ingestor_can_feed_embedding_pipeline_contract():
    from verideploy.knowledge.ingestion import KnowledgeCorpusIngestor

    class Writer:
        def upsert_document(self, item): pass
        def upsert_chunk(self, item): return "hash"

    class Embedder:
        def __init__(self): self.request = None
        async def embed(self, request): self.request = request

    corpus = EngineeringKnowledgeCorpus(CORPUS)
    embedder = Embedder()
    result = await KnowledgeCorpusIngestor(corpus=corpus, writer=Writer(), embedding_pipeline=embedder).ingest()
    assert result.embeddings_requested == result.chunks_upserted
    assert embedder.request.tenant_id == corpus.manifest.tenant_id
    assert all(item.document_id and item.chunk_id for item in embedder.request.inputs)


def test_validator_rejects_tampered_document(tmp_path):
    import shutil
    clone = tmp_path / "knowledge"
    shutil.copytree(CORPUS, clone)
    target = clone / "documents" / "runbook-db-pool.md"
    target.write_text(target.read_text() + "\nTampered content.\n")
    report = validate_corpus(clone)
    assert report.valid is False
    assert any(error.startswith("hash mismatch:") for error in report.errors)


def test_validator_rejects_untracked_document(tmp_path):
    import shutil
    clone = tmp_path / "knowledge"
    shutil.copytree(CORPUS, clone)
    (clone / "documents" / "untracked.md").write_text("# Untracked\n")
    report = validate_corpus(clone)
    assert report.valid is False
    assert any(error.startswith("untracked documents:") for error in report.errors)
