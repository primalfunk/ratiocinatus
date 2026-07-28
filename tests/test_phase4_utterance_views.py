from __future__ import annotations

from pathlib import Path

import pytest

from ratiocinatus.quotation_evidence import build_quotation_evidence
from ratiocinatus.turn_repair import build_turn_repair_run
from ratiocinatus.utterance_analysis import analyze_utterance_corpus
from ratiocinatus.utterance_relation_contracts import (
    UtteranceTemporalRelation,
)
from ratiocinatus.utterance_relations import build_utterance_relations
from ratiocinatus.utterance_view_contracts import (
    SpeakerAttributedTranscriptBundle,
    SpeakerAttributedTranscriptPolicy,
    SpeakerAttributedViewKind,
    UtterancePresentationLossKind,
    UtterancePresentationMarker,
)
from ratiocinatus.utterance_views import (
    UtteranceViewIntegrityError,
    build_speaker_attributed_views,
    load_speaker_attributed_views,
    persist_speaker_attributed_views,
    validate_speaker_attributed_views,
)

from test_phase3_clustering import HAS_FFMPEG
from test_phase3_speaker_transcript import NOW
from test_phase4_quotation import _quotation_inputs


def _view_inputs(tmp_path: Path):
    values, transcript, speaker_view, utterance_run, corpus = (
        _quotation_inputs(tmp_path)
    )
    diarization = values[1]
    analysis = analyze_utterance_corpus(
        utterance_run, corpus, transcript, created_at=NOW
    )
    relations = build_utterance_relations(
        utterance_run, corpus, analysis, diarization, created_at=NOW
    )
    repair = build_turn_repair_run(
        utterance_run,
        corpus,
        transcript,
        speaker_view,
        diarization,
        created_at=NOW,
    )
    quotation = build_quotation_evidence(
        utterance_run, corpus, transcript, created_at=NOW
    )
    return (
        utterance_run,
        corpus,
        analysis,
        relations,
        repair,
        quotation,
    )


def _build(tmp_path: Path):
    inputs = _view_inputs(tmp_path)
    return build_speaker_attributed_views(
        *inputs, generated_at=NOW
    ), inputs


def test_view_contract_requires_all_six_non_authoritative_views() -> None:
    policy = SpeakerAttributedTranscriptPolicy()
    assert not policy.authoritative_replacement
    assert policy.preserve_utterance_identifiers
    assert policy.preserve_source_intervals
    assert policy.preserve_unknown_speakers

    with pytest.raises(ValueError, match="exactly all six"):
        SpeakerAttributedTranscriptBundle.model_construct(
            bundle_id="utteranceviewbundle_" + "0" * 32,
            utterance_corpus_id="utterancecorpus_" + "0" * 32,
            utterance_run_id="utterancerun_" + "0" * 32,
            utterance_analysis_id="utteranceanalysis_" + "0" * 32,
            utterance_relation_run_id="utterancerelations_" + "0" * 32,
            turn_repair_run_id="turnrepairrun_" + "0" * 32,
            quotation_run_id="quotationrun_" + "0" * 32,
            configuration_hash="0" * 64,
            views=(),
            generated_at=NOW,
            integrity_sha256="0" * 64,
        ).required_views_are_present()


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_all_views_are_deterministic_complete_and_marker_rich(
    tmp_path: Path,
) -> None:
    bundle, inputs = _build(tmp_path)
    repeated = build_speaker_attributed_views(*inputs, generated_at=NOW)
    assert repeated == bundle
    assert {item.kind for item in bundle.views} == set(
        SpeakerAttributedViewKind
    )

    corpus = inputs[1]
    expected_ids = {item.utterance_id for item in corpus.utterances}
    source_intervals = {
        item.utterance_id: item.source_intervals for item in corpus.utterances
    }
    for view in bundle.views:
        assert {
            item.utterance_id for item in view.rendered_utterances
        } == expected_ids
        assert all(
            item.source_intervals == source_intervals[item.utterance_id]
            for item in view.rendered_utterances
        )

    expanded = next(
        item
        for item in bundle.views
        if item.kind == SpeakerAttributedViewKind.OVERLAP_EXPANDED
    )
    assert expanded.preserves_overlap_partial_order
    markers = {
        marker
        for item in expanded.rendered_utterances
        for marker in item.markers
    }
    assert UtterancePresentationMarker.QUOTATION in markers
    assert UtterancePresentationMarker.EMBEDDED_SOURCE in markers
    validate_speaker_attributed_views(bundle, *inputs)


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_sequential_views_disclose_overlap_linearization(
    tmp_path: Path,
) -> None:
    bundle, inputs = _build(tmp_path)
    has_overlap = any(
        item.temporal_relation == UtteranceTemporalRelation.OVERLAPPING
        for item in inputs[3].adjacencies
    ) or bool(inputs[3].overlaps)
    sequential = tuple(
        item
        for item in bundle.views
        if item.kind != SpeakerAttributedViewKind.OVERLAP_EXPANDED
    )
    if has_overlap:
        assert all(
            any(
                loss.kind
                == UtterancePresentationLossKind.OVERLAP_LINEARIZED
                for loss in item.losses
            )
            for item in sequential
        )
    assert not any(
        loss.kind == UtterancePresentationLossKind.OVERLAP_LINEARIZED
        for loss in next(
            item
            for item in bundle.views
            if item.kind == SpeakerAttributedViewKind.OVERLAP_EXPANDED
        ).losses
    )


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_view_persistence_replays_and_rejects_tampering(
    tmp_path: Path,
) -> None:
    bundle, inputs = _build(tmp_path)
    first = persist_speaker_attributed_views(
        bundle, *inputs, tmp_path / "views"
    )
    replay = persist_speaker_attributed_views(
        bundle, *inputs, tmp_path / "views"
    )
    assert not first[3]
    assert replay[3]
    loaded = load_speaker_attributed_views(first[2])
    assert loaded == first[:2]
    validate_speaker_attributed_views(
        loaded[0], *inputs, report=loaded[1]
    )
    assert len(tuple(first[2].glob("*.txt"))) == 6

    tampered = bundle.model_copy(
        update={"configuration_hash": "f" * 64}
    )
    with pytest.raises(UtteranceViewIntegrityError, match="integrity is invalid"):
        validate_speaker_attributed_views(tampered, *inputs)
