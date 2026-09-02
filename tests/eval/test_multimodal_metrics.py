from __future__ import annotations

from verideploy.evaluation.multimodal_metrics import (
    MultimodalObservation,
    TemporalAnchor,
    modality_gate,
    score_observation,
    set_f1,
    summarize_metrics,
    temporal_alignment,
)


def test_set_f1_handles_exact_partial_and_empty() -> None:
    assert set_f1(frozenset(), frozenset()) == 1.0
    assert set_f1(frozenset({"a"}), frozenset({"a"})) == 1.0
    assert 0.0 < set_f1(frozenset({"a", "b"}), frozenset({"a"})) < 1.0


def test_visual_case_scores_grounding_reasoning_and_citations() -> None:
    metric = score_observation(MultimodalObservation(
        case_id="visual-1",
        modality="diagram",
        expected_grounding=frozenset({"node:a", "edge:a-b"}),
        observed_grounding=frozenset({"node:a", "edge:a-b"}),
        expected_visual_facts=frozenset({"payment->redis"}),
        observed_visual_facts=frozenset({"payment->redis"}),
        ocr_text_available=False,
        visual_reasoning_correct=True,
        expected_citations=frozenset({"page:2#bbox:1"}),
        observed_citations=frozenset({"page:2#bbox:1"}),
    ))
    assert metric.aggregate_score == 1.0
    assert metric.ocr_free_visual_reasoning == 1.0


def test_temporal_alignment_reports_score_and_mae() -> None:
    score, mae = temporal_alignment((TemporalAnchor(1000, 1100), TemporalAnchor(5000, 5200)), tolerance_ms=1000)
    assert mae == 150.0
    assert 0.8 < score < 1.0


def test_audio_video_metrics_do_not_fake_visual_denominators() -> None:
    metric = score_observation(MultimodalObservation(
        case_id="audio-1",
        modality="audio",
        expected_citations=frozenset({"audio:1200-2400"}),
        observed_citations=frozenset({"audio:1200-2400"}),
        temporal_anchors=(TemporalAnchor(1800, 1850),),
    ))
    assert metric.image_grounding_accuracy is None
    assert metric.temporal_alignment_score is not None


def test_modality_gate_checks_overall_and_specific_modalities() -> None:
    rows = [
        score_observation(MultimodalObservation(case_id="i", modality="image", expected_citations=frozenset({"x"}), observed_citations=frozenset({"x"}))),
        score_observation(MultimodalObservation(case_id="v", modality="video", expected_citations=frozenset({"v"}), observed_citations=frozenset({"v"}), temporal_anchors=(TemporalAnchor(1000, 1000),))),
    ]
    summary = summarize_metrics(rows)
    gate = modality_gate(summary, {"aggregate_score": 0.9, "modality:video:aggregate_score": 0.9})
    assert gate["passed"] is True
