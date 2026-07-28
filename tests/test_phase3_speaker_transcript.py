from __future__ import annotations

from pathlib import Path

import pytest

from ratiocinatus.addressing_contracts import MediaInterval, TimeDomain
from ratiocinatus.cli import EXIT_SUCCESS, main
from ratiocinatus.correction_contracts import TranscriptViewKind
from ratiocinatus.corrections import (
    build_transcript_revision,
    prepare_correction_batch,
)
from ratiocinatus.identity_binding import append_manual_identity_binding
from ratiocinatus.identity_view import (
    assemble_identity_views,
    persist_identity_view_assembly,
)
from ratiocinatus.kernel import canonical_bytes, canonical_hash, typed_id
from ratiocinatus.phase2_contracts import (
    ConfidenceMeasure,
    ConfidenceOrigin,
    SpeechEvidenceProviderIdentity,
)
from ratiocinatus.phase3_contracts import BindingAction
from ratiocinatus.speaker_transcript import (
    SpeakerTranscriptIntegrityError,
    build_speaker_labeled_transcript,
    persist_speaker_labeled_transcript,
)
from ratiocinatus.speaker_transcript_contracts import (
    SPEAKER_TRANSCRIPT_CONTRACT_MODELS,
    SpeakerAttributionKind,
    SpeakerLabeledTranscriptPolicy,
)
from ratiocinatus.transcript_assembly import validate_transcript_assembly
from ratiocinatus.transcript_contracts import (
    TranscriptArtifactDigest,
    TranscriptAssembly,
    TranscriptAssemblyPolicy,
    TranscriptAssemblyStatus,
    TranscriptSegment,
    TranscriptVersion,
)

from test_phase2_transcript_assembly import replacement_draft
from test_phase3_clustering import HAS_FFMPEG
from test_phase3_identity_binding import NOW, _certainty
from test_phase3_identity_views import _inputs


def _seal(model, payload):
    provisional = model(**payload, integrity_sha256="0" * 64)
    integrity = canonical_hash(
        provisional.model_dump(mode="json", exclude={"integrity_sha256"})
    )
    return model(**payload, integrity_sha256=integrity)


def _confidence() -> ConfidenceMeasure:
    return ConfidenceMeasure(
        value=0.9,
        origin=ConfidenceOrigin.DERIVED,
        basis="Controlled speaker-transcript integration fixture.",
    )


def _transcript(diarization) -> TranscriptAssembly:
    turns = diarization.turns
    start = min(
        item.normalized_audio_interval.start_microseconds for item in turns
    )
    end = max(
        item.normalized_audio_interval.start_microseconds
        + item.normalized_audio_interval.duration_microseconds
        for item in turns
    )
    midpoint = start + (end - start) // 2
    offset = (
        turns[0].source_interval.start_microseconds
        - turns[0].normalized_audio_interval.start_microseconds
    )
    intervals = []
    if start > 0:
        gap_end = min(start, max(1, start // 2))
        intervals.append((0, gap_end, "Unattributed introduction"))
    intervals.extend(
        (
            (start, midpoint, "First attributed portion"),
            (midpoint, end, "Second attributed portion"),
        )
    )
    provider = SpeechEvidenceProviderIdentity(
        provider_id="test.speaker_transcript",
        display_name="Controlled transcript provider",
        provider_version="1.0.0",
        local=True,
    )
    assembly_policy = TranscriptAssemblyPolicy()
    response_id = typed_id("txresponse", diarization.run_id)
    observations = {
        item.observation_id: item for item in diarization.observations
    }
    chunks = tuple(
        dict.fromkeys(
            chunk
            for turn in turns
            for chunk in turn.processing_chunk_ids
        )
    )
    speech_ids = tuple(
        dict.fromkeys(
            speech_id
            for turn in turns
            for observation_id in turn.observation_ids
            for speech_id in observations[observation_id].speech_interval_ids
        )
    )
    segments = []
    for ordinal, (segment_start, segment_end, text) in enumerate(intervals):
        segment_id = typed_id(
            "txsegment", diarization.run_id, ordinal, segment_start, segment_end
        )
        segments.append(
            _seal(
                TranscriptSegment,
                {
                    "segment_id": segment_id,
                    "corpus_id": diarization.corpus_id,
                    "source_id": diarization.source_id,
                    "selected_audio_stream_id": (
                        diarization.observations[0].selected_audio_stream_id
                    ),
                    "selected_audio_stream_index": 0,
                    "source_interval": MediaInterval(
                        domain=TimeDomain.SOURCE_MEDIA,
                        start_microseconds=segment_start + offset,
                        duration_microseconds=segment_end - segment_start,
                    ),
                    "normalized_audio_interval": MediaInterval(
                        domain=TimeDomain.NORMALIZED_CORPUS,
                        start_microseconds=segment_start,
                        duration_microseconds=segment_end - segment_start,
                    ),
                    "processing_chunk_ids": chunks,
                    "proposed_text": text,
                    "normalized_text": text,
                    "speech_activity_evidence_ids": speech_ids,
                    "provider": provider,
                    "transcription_response_id": response_id,
                    "provider_observation_id": typed_id(
                        "txobs", diarization.run_id, ordinal
                    ),
                    "selected_candidate_id": f"candidate-{ordinal}",
                    "promotion_basis": "Controlled Phase 3 integration fixture.",
                    "text_confidence": _confidence(),
                    "timing_confidence": _confidence(),
                    "boundary_confidence": _confidence(),
                    "created_at": NOW,
                },
            )
        )
    version = _seal(
        TranscriptVersion,
        {
            "version_id": typed_id("txversion", diarization.run_id),
            "corpus_id": diarization.corpus_id,
            "transcription_response_id": response_id,
            "assembly_policy": assembly_policy,
            "segments": tuple(
                TranscriptArtifactDigest(
                    artifact_id=item.segment_id,
                    content_sha256=canonical_hash(item),
                )
                for item in segments
            ),
            "words": (),
            "low_confidence_regions": (),
            "created_at": NOW,
        },
    )
    assembly = _seal(
        TranscriptAssembly,
        {
            "assembly_id": typed_id("txassembly", diarization.run_id),
            "source_id": diarization.source_id,
            "normalized_audio_sha256": "0" * 64,
            "normalized_audio_duration_microseconds": max(end, 1),
            "source_mapping_offset_microseconds": offset,
            "version": version,
            "segments": tuple(segments),
            "words": (),
            "low_confidence_regions": (),
            "status": TranscriptAssemblyStatus.COMPLETE,
            "assembled_at": NOW,
        },
    )
    validate_transcript_assembly(assembly)
    return assembly


def _speaker_inputs(tmp_path: Path):
    values = _inputs(tmp_path)
    response, diarization, clustering, foundation, binding_run = values[:5]
    identity_assembly = assemble_identity_views(
        response,
        diarization,
        clustering,
        foundation,
        binding_run,
        created_at=NOW,
    )
    transcript = _transcript(diarization)
    return values, transcript, identity_assembly


def test_speaker_transcript_contract_schemas_are_closed() -> None:
    assert len(SPEAKER_TRANSCRIPT_CONTRACT_MODELS) == 5
    for model in SPEAKER_TRANSCRIPT_CONTRACT_MODELS:
        schema = model.model_json_schema()
        assert schema["title"] == model.__name__
        assert schema.get("additionalProperties") is False


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_original_transcript_preserves_text_with_temporal_attribution_spans(
    tmp_path: Path,
) -> None:
    values, transcript, identity_assembly = _speaker_inputs(tmp_path)
    diarization = values[1]
    before = transcript.model_dump_json()
    view = build_speaker_labeled_transcript(
        transcript,
        diarization,
        identity_assembly,
        created_at=NOW,
    )
    assert tuple(item.source_text for item in view.segments) == tuple(
        item.proposed_text for item in transcript.segments
    )
    assert any(
        span.attribution_kind == SpeakerAttributionKind.UNATTRIBUTED
        for segment in view.segments
        for span in segment.attribution_spans
    )
    assert any(
        span.attribution_kind
        in {
            SpeakerAttributionKind.REVIEWED,
            SpeakerAttributionKind.MULTIPLE_CANDIDATES,
        }
        for segment in view.segments
        for span in segment.attribution_spans
    )
    assert all(
        sum(
            span.normalized_audio_interval.duration_microseconds
            for span in item.attribution_spans
        )
        == item.normalized_audio_interval.duration_microseconds
        for item in view.segments
    )
    assert transcript.model_dump_json() == before


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_corrected_transcript_view_preserves_revision_lineage(
    tmp_path: Path,
) -> None:
    values, transcript, identity_assembly = _speaker_inputs(tmp_path)
    diarization = values[1]
    batch = prepare_correction_batch(
        transcript.version.version_id,
        (replacement_draft(transcript),),
    )
    revision, _ = build_transcript_revision(transcript, batch)
    view = build_speaker_labeled_transcript(
        transcript,
        diarization,
        identity_assembly,
        revision=revision,
        policy=SpeakerLabeledTranscriptPolicy(
            transcript_view_kind=TranscriptViewKind.CURRENT_CORRECTED
        ),
        created_at=NOW,
    )
    assert view.source_revision_id == revision.revision_id
    assert view.source_transcript_version_id == revision.version.version_id
    assert view.segments[0].source_text == "Corrected words"
    with pytest.raises(
        SpeakerTranscriptIntegrityError, match="requires a transcript revision"
    ):
        build_speaker_labeled_transcript(
            transcript,
            diarization,
            identity_assembly,
            policy=SpeakerLabeledTranscriptPolicy(
                transcript_view_kind=TranscriptViewKind.CURRENT_CORRECTED
            ),
        )


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_conflicted_identity_view_blocks_trusted_transcript(
    tmp_path: Path,
) -> None:
    values, transcript, _ = _speaker_inputs(tmp_path)
    (
        response,
        diarization,
        clustering,
        foundation,
        first,
        _,
        scope,
        identities,
    ) = values[:8]
    conflicted, _ = append_manual_identity_binding(
        foundation,
        clustering,
        diarization,
        target_artifact_id=scope.target_id,
        identity_id=identities[1].identity_id,
        scope=scope,
        action=BindingAction.BIND,
        author_id="reviewer:conflicted-transcript",
        author_display_name="Conflicted Transcript Reviewer",
        rationale="Independent review branch for transcript qualification.",
        supporting_evidence_references=("fixture:speaker-transcript:conflict",),
        reviewer_certainty=_certainty(0.7),
        predecessor=first,
        created_at=NOW,
    )
    identity_assembly = assemble_identity_views(
        response,
        diarization,
        clustering,
        foundation,
        conflicted,
        created_at=NOW,
    )
    view = build_speaker_labeled_transcript(
        transcript,
        diarization,
        identity_assembly,
        created_at=NOW,
    )
    assert view.blocking_findings
    assert not view.trusted_for_participant_rendering
    assert any(
        span.attribution_kind == SpeakerAttributionKind.CONFLICTED
        for segment in view.segments
        for span in segment.attribution_spans
    )


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_speaker_transcript_persistence_cache_and_cli(
    tmp_path: Path,
) -> None:
    values, transcript, identity_assembly = _speaker_inputs(tmp_path)
    diarization = values[1]
    view = build_speaker_labeled_transcript(
        transcript,
        diarization,
        identity_assembly,
        created_at=NOW,
    )
    stored = persist_speaker_labeled_transcript(
        view,
        transcript,
        diarization,
        identity_assembly,
        tmp_path / "speaker-output",
    )
    assert not stored[-1]
    assert persist_speaker_labeled_transcript(
        view,
        transcript,
        diarization,
        identity_assembly,
        tmp_path / "speaker-output",
    )[-1]

    assembly_root = tmp_path / "transcript-source"
    assembly_root.mkdir()
    (assembly_root / "assembly.json").write_bytes(canonical_bytes(transcript))
    identity_root = persist_identity_view_assembly(
        identity_assembly,
        values[0],
        diarization,
        values[2],
        values[3],
        values[4],
        tmp_path / "identity-output",
    )[2]
    destination = tmp_path / "speaker-cli"
    assert main(
        [
            "--json",
            "diarization",
            "speaker-transcript-render",
            str(assembly_root),
            str(values[11]),
            str(identity_root),
            str(destination),
        ]
    ) == EXIT_SUCCESS
    root = next((destination / "speaker-transcripts").iterdir())
    assert main(
        ["--json", "diarization", "speaker-transcript-inspect", str(root)]
    ) == EXIT_SUCCESS
    assert main(
        [
            "--json",
            "diarization",
            "speaker-transcript-list-spans",
            str(root),
        ]
    ) == EXIT_SUCCESS
    assert main(
        [
            "--json",
            "diarization",
            "speaker-transcript-validate",
            str(root),
            str(assembly_root),
            str(values[11]),
            str(identity_root),
        ]
    ) == EXIT_SUCCESS
