from __future__ import annotations
import json
from pathlib import Path
import pytest
from verideploy.rag.checkpoint.performance import run_rag_checkpoint, tuned_chunks
from verideploy.rag.retrieval.benchmark import run_seed_benchmark

ROOT=Path(__file__).resolve().parents[2]

def test_clean_index_protected_retrieval_targets_pass():
    result=run_rag_checkpoint()
    assert result.passed, result.failures
    assert result.metrics['keyword_recall_at_5'] == 1.0
    assert result.metrics['dense_recall_at_5'] == 1.0
    assert result.metrics['hybrid_recall_at_5'] == 1.0
    assert result.metrics['hybrid_mrr'] >= .95

def test_visual_filters_citations_and_tenant_protection_are_closed():
    result=run_rag_checkpoint()
    for name in ('visual_ndcg_at_4','metadata_filter_correctness','citation_completeness','tenant_isolation'):
        assert result.metrics[name] == 1.0

def test_latency_and_cache_budgets_pass_after_clean_warmup():
    policy=json.loads((ROOT/'config/rag/checkpoint.json').read_text())
    result=run_rag_checkpoint()
    assert result.latency_ms['cold_p95'] <= policy['latency_budget_ms']['cold_p95']
    assert result.latency_ms['warm_p95'] <= policy['latency_budget_ms']['warm_p95']
    assert result.cache['hit_ratio'] >= policy['cache']['minimum_hit_ratio_after_warmup']

def test_chunking_is_deterministic_bounded_and_overlapped():
    text=' '.join(f'token{i}.' if i % 50 == 49 else f'token{i}' for i in range(700))
    first=tuned_chunks(text,target_tokens=220,overlap_tokens=40,max_tokens=320)
    second=tuned_chunks(text,target_tokens=220,overlap_tokens=40,max_tokens=320)
    assert first == second
    assert len(first) >= 3
    assert all(0 < len(x.text.split()) <= 320 for x in first)
    assert len(set(x.sha256 for x in first)) == len(first)

def test_invalid_chunk_policy_fails_fast():
    with pytest.raises(ValueError): tuned_chunks('a b c',target_tokens=20,overlap_tokens=20,max_tokens=30)
