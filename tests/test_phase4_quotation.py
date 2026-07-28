from __future__ import annotations

from pathlib import Path

import pytest

from ratiocinatus.quotation_contracts import (
    EmbeddedSpeechKind,
    SpokenQuotationType,
)
from ratiocinatus.quotation_evidence import (
    QuotationEvidenceIntegrityError,
    build_quotation_evidence,
    load_quotation_evidence,
    persist_quotation_evidence,
    validate_quotation_evidence,
)
from ratiocinatus.speaker_transcript import build_speaker_labeled_transcript
from ratiocinatus.utterance_segmentation import build_utterance_corpus

from test_phase3_clustering import HAS_FFMPEG
from test_phase3_speaker_transcript import NOW, _speaker_inputs
from test_phase4_analysis import _with_surfaces
from test_phase4_segmentation import _with_words


def _quotation_inputs(tmp_path: Path):
    values, transcript, identity_assembly = _speaker_inputs(tmp_path)
    diarization = values[1]
    transcript = _with_words(transcript)
    controlled = (
        'Alice said "hello there".',
        "[remote] Good evening.",
        '"quotation marks alone"',
    )
    surfaces = tuple(
        controlled[index]
        if index < len(controlled)
        else word.surface_text
        for index, word in enumerate(transcript.words)
    )
    transcript = _with_surfaces(transcript, surfaces)
    speaker_view = build_speaker_labeled_transcript(
        transcript, diarization, identity_assembly, created_at=NOW
    )
    utterance_run, corpus = build_utterance_corpus(
        transcript, speaker_view, diarization, created_at=NOW
    )
    return values, transcript, speaker_view, utterance_run, corpus


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_quotation_detection_is_bounded_and_preserves_acoustic_attribution(
    tmp_path: Path,
) -> None:
    _, transcript, _, utterance_run, corpus = _quotation_inputs(tmp_path)
    before = corpus.model_dump_json()
    evidence = build_quotation_evidence(
        utterance_run, corpus, transcript, created_at=NOW
    )
    repeated = build_quotation_evidence(
        utterance_run, corpus, transcript, created_at=NOW
    )

    assert repeated == evidence
    assert corpus.model_dump_json() == before
    assert len(evidence.quotations) == 1
    quotation = evidence.quotations[0]
    utterance = next(
        item
        for item in corpus.utterances
        if item.utterance_id == quotation.quoting_utterance_id
    )
    assert quotation.quotation_type == SpokenQuotationType.DIRECT
    assert quotation.quoted_span.quoted_text == "hello there"
    assert quotation.acoustic_attribution_id == (
        utterance.attribution.attribution_id
    )
    assert quotation.acoustic_speaker_target_id == (
        utterance.attribution.target_id
    )
    assert quotation.quoted_speaker_target_id is None
    assert quotation.acoustic_attribution_preserved
    assert '"quotation marks alone"' not in tuple(
        item.quoted_span.quoted_text for item in evidence.quotations
    )
    assert len(evidence.embedded_sources) == 1
    assert evidence.embedded_sources[0].kind == EmbeddedSpeechKind.REMOTE_FEED


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_quotation_persistence_replays_and_rejects_tampering(
    tmp_path: Path,
) -> None:
    _, transcript, _, utterance_run, corpus = _quotation_inputs(tmp_path)
    evidence = build_quotation_evidence(
        utterance_run, corpus, transcript, created_at=NOW
    )
    first = persist_quotation_evidence(
        evidence,
        utterance_run,
        corpus,
        transcript,
        tmp_path / "quotation",
    )
    replay = persist_quotation_evidence(
        evidence,
        utterance_run,
        corpus,
        transcript,
        tmp_path / "quotation",
    )
    assert not first[3]
    assert replay[3]
    loaded = load_quotation_evidence(first[2])
    assert loaded == first[:2]
    validate_quotation_evidence(
        loaded[0], utterance_run, corpus, transcript, report=loaded[1]
    )

    tampered = evidence.model_copy(
        update={"configuration_hash": "f" * 64}
    )
    with pytest.raises(
        QuotationEvidenceIntegrityError, match="integrity is invalid"
    ):
        validate_quotation_evidence(
            tampered, utterance_run, corpus, transcript
        )
