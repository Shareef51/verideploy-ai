from __future__ import annotations

import math
import re
from dataclasses import dataclass
from uuid import UUID, uuid5

from verideploy.rag.retrieval.fusion import FusionConfig, normalize_scores, reciprocal_rank_fusion
from verideploy.rag.retrieval.schemas import ChannelCandidate, RetrievalChannel

_NAMESPACE = UUID("00000000-0000-4000-8000-000000000013")
_TOKEN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class SeedDocument:
    key: str
    title: str
    content: str

    @property
    def chunk_id(self) -> UUID:
        return uuid5(_NAMESPACE, f"chunk:{self.key}")

    @property
    def document_id(self) -> UUID:
        return uuid5(_NAMESPACE, f"doc:{self.key}")


@dataclass(frozen=True)
class SeedCase:
    query: str
    relevant_key: str
    semantic_aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class RetrievalMetrics:
    recall_at_5: float
    mrr: float


CORPUS = (
    SeedDocument("db-pool", "Checkout database pool exhaustion", "checkout latency increased because database connection pool slots were exhausted after deployment"),
    SeedDocument("migration", "Database migration incompatibility", "schema migration removed a column still required by the payment service"),
    SeedDocument("redis", "Redis saturation", "cache memory pressure caused redis evictions and request latency"),
    SeedDocument("kafka", "Kafka consumer lag", "event processing delay grew because consumers could not keep up with partition traffic"),
    SeedDocument("certificate", "Expired TLS certificate", "authentication calls failed when the upstream certificate expired"),
    SeedDocument("memory", "Memory leak eviction", "a heap growth regression caused pod out of memory termination and eviction"),
)

CASES = (
    SeedCase("checkout connection slots exhausted", "db-pool", ("database", "pool", "latency")),
    SeedCase("schema change broke payment", "migration", ("migration", "column", "database")),
    SeedCase("cache evictions memory pressure", "redis", ("redis", "cache", "latency")),
    SeedCase("event processing backlog", "kafka", ("kafka", "consumer", "delay")),
    SeedCase("upstream tls expired", "certificate", ("certificate", "authentication", "failed")),
    SeedCase("heap growth killed pod", "memory", ("memory", "eviction", "termination")),
)


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def _bm25(query: str, docs: tuple[SeedDocument, ...]) -> list[tuple[SeedDocument, float]]:
    query_tokens = _tokens(query)
    tokenized = [_tokens(f"{doc.title} {doc.content}") for doc in docs]
    avgdl = sum(map(len, tokenized)) / len(tokenized)
    scores: list[tuple[SeedDocument, float]] = []
    for doc, terms in zip(docs, tokenized, strict=True):
        score = 0.0
        for token in query_tokens:
            df = sum(1 for other in tokenized if token in other)
            if df == 0:
                continue
            idf = math.log(1 + (len(docs) - df + 0.5) / (df + 0.5))
            tf = terms.count(token)
            if tf:
                k1, b = 1.2, 0.75
                score += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * len(terms) / avgdl))
        scores.append((doc, score))
    return sorted(scores, key=lambda pair: (-pair[1], pair[0].key))


def _semantic(case: SeedCase, docs: tuple[SeedDocument, ...]) -> list[tuple[SeedDocument, float]]:
    aliases = set(case.semantic_aliases)
    scores = []
    for doc in docs:
        doc_terms = set(_tokens(f"{doc.title} {doc.content}"))
        overlap = len(aliases & doc_terms) / max(1, len(aliases))
        # A deterministic semantic channel intentionally uses curated concept aliases, not lexical query overlap.
        scores.append((doc, overlap))
    return sorted(scores, key=lambda pair: (-pair[1], pair[0].key))


def _candidates(ranked: list[tuple[SeedDocument, float]], channel: RetrievalChannel) -> list[ChannelCandidate]:
    normalized = normalize_scores([score for _, score in ranked])
    return [
        ChannelCandidate(
            chunk_id=doc.chunk_id,
            document_id=doc.document_id,
            source_key=doc.key,
            title=doc.title,
            content=doc.content,
            channel=channel,
            rank=index + 1,
            raw_score=score,
            normalized_score=normalized[index],
        )
        for index, (doc, score) in enumerate(ranked)
    ]


def _metrics(rankings: list[list[str]], relevant: list[str]) -> RetrievalMetrics:
    reciprocal = []
    hits = 0
    for ranking, expected in zip(rankings, relevant, strict=True):
        try:
            rank = ranking.index(expected) + 1
        except ValueError:
            rank = 0
        hits += int(0 < rank <= 5)
        reciprocal.append(1.0 / rank if rank else 0.0)
    return RetrievalMetrics(recall_at_5=hits / len(rankings), mrr=sum(reciprocal) / len(reciprocal))


def run_seed_benchmark() -> dict[str, RetrievalMetrics]:
    keyword_rankings: list[list[str]] = []
    dense_rankings: list[list[str]] = []
    hybrid_rankings: list[list[str]] = []
    relevant = [case.relevant_key for case in CASES]
    for case in CASES:
        keyword_pairs = _bm25(case.query, CORPUS)
        dense_pairs = _semantic(case, CORPUS)
        keyword = _candidates(keyword_pairs, RetrievalChannel.KEYWORD)
        dense = _candidates(dense_pairs, RetrievalChannel.DENSE)
        hybrid = reciprocal_rank_fusion(keyword, dense, top_k=5, config=FusionConfig(rrf_k=60, max_per_source=2))
        keyword_rankings.append([doc.key for doc, _ in keyword_pairs])
        dense_rankings.append([doc.key for doc, _ in dense_pairs])
        hybrid_rankings.append([hit.source_key for hit in hybrid])
    return {
        "keyword": _metrics(keyword_rankings, relevant),
        "dense": _metrics(dense_rankings, relevant),
        "hybrid": _metrics(hybrid_rankings, relevant),
    }
