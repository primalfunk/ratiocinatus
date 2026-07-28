from __future__ import annotations

from pathlib import Path

import pytest

from ratiocinatus.phase4_contracts import UtteranceReviewStatus
from ratiocinatus.utterance_analysis import analyze_utterance_corpus
from ratiocinatus.utterance_relation_contracts import (
    InterruptionKind,
    OverlapAttributionDisposition,
)
from ratiocinatus.utterance_relations import (
    UtteranceRelationIntegrityError,
    build_utterance_relations,
    load_utterance_relations,
    persist_utterance_relations,
    validate_utterance_relations,
)

from test_phase3_clustering import HAS_FFMPEG
from test_phase3_speaker_transcript import NOW
from test_phase4_analysis import _inputs


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_relations_preserve_phase3_overlap_and_partial_order(
    tmp_path: Path,
) -> None:
    values, transcript, _, utterance_run, corpus = _inputs(tmp_path)
    diarization = values[1]
    analysis = analyze_utterance_corpus(
        utterance_run, corpus, transcript, created_at=NOW
    )
    before_corpus = corpus.model_dump_json()
    before_analysis = analysis.model_dump_json()

    relations = build_utterance_relations(
        utterance_run,
        corpus,
        analysis,
        diarization,
        created_at=NOW,
    )
    repeated = build_utterance_relations(
        utterance_run,
        corpus,
        analysis,
        diarization,
        created_at=NOW,
    )

    assert repeated == relations
    assert corpus.model_dump_json() == before_corpus
    assert analysis.model_dump_json() == before_analysis
    assert len(relations.adjacencies) == max(0, len(corpus.utterances) - 1)
    assert tuple(item.phase3_overlap_id for item in relations.overlaps) == tuple(
        item.overlap_id for item in diarization.overlaps
    )
    assert all(
        item.normalized_audio_interval
        == next(
            overlap.normalized_audio_interval
            for overlap in diarization.overlaps
            if overlap.overlap_id == item.phase3_overlap_id
        )
        for item in relations.overlaps
    )
    assert all(
        item.review_status == UtteranceReviewStatus.REVIEW_REQUIRED
        for item in relations.overlaps
    )
    assert all(
        item.disposition
        in {
            OverlapAttributionDisposition.SEPARATED_UTTERANCES,
            OverlapAttributionDisposition.MIXED_TRANSCRIPT,
            OverlapAttributionDisposition.UNCERTAIN_WORD_ATTRIBUTION,
            OverlapAttributionDisposition.UNTRANSCRIBED_OVERLAP,
        }
        for item in relations.overlaps
    )
    assert all(
        item.kind != InterruptionKind.ACTUAL_SIMULTANEOUS
        or item.overlap_relation_id is not None
        for item in relations.interruptions
    )
    assert all(not item.semantic_inference_used for item in relations.continuations)


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_relation_persistence_replays_and_rejects_tampering(
    tmp_path: Path,
) -> None:
    values, transcript, _, utterance_run, corpus = _inputs(tmp_path)
    diarization = values[1]
    analysis = analyze_utterance_corpus(
        utterance_run, corpus, transcript, created_at=NOW
    )
    relations = build_utterance_relations(
        utterance_run,
        corpus,
        analysis,
        diarization,
        created_at=NOW,
    )
    first = persist_utterance_relations(
        relations,
        utterance_run,
        corpus,
        analysis,
        diarization,
        tmp_path / "relations",
    )
    replay = persist_utterance_relations(
        relations,
        utterance_run,
        corpus,
        analysis,
        diarization,
        tmp_path / "relations",
    )
    assert not first[3]
    assert replay[3]
    loaded = load_utterance_relations(first[2])
    assert loaded == first[:2]
    validate_utterance_relations(
        loaded[0],
        utterance_run,
        corpus,
        analysis,
        diarization,
        report=loaded[1],
    )

    tampered = relations.model_copy(
        update={"configuration_hash": "f" * 64}
    )
    with pytest.raises(
        UtteranceRelationIntegrityError, match="integrity is invalid"
    ):
        validate_utterance_relations(
            tampered, utterance_run, corpus, analysis, diarization
        )
