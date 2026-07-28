from __future__ import annotations

import math
import shutil
import wave
from array import array
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ratiocinatus.activity import FFmpegEnergySpeechActivityProvider
from ratiocinatus.addressing_contracts import MediaInterval, TimeDomain
from ratiocinatus.chunk_contracts import ProcessingChunk
from ratiocinatus.cli import EXIT_SUCCESS, main
from ratiocinatus.corpus import load_corpus
from ratiocinatus.diarization import (
    DiarizationIntegrityError,
    _canonicalize,
    validate_diarization_response,
    diarize_corpus,
)
from ratiocinatus.diarization_evidence import prepare_diarization_request
from ratiocinatus.diarization_providers import DiarizationProvider
from ratiocinatus.ingestion import prepare_ingestion_request, run_ingestion
from ratiocinatus.kernel import canonical_hash, typed_id
from ratiocinatus.media import sha256_file
from ratiocinatus.phase2_contracts import (
    ConfidenceMeasure,
    ConfidenceOrigin,
    RawEvidenceDisposition,
    RawProviderEvidence,
    SpeechActivityClassification,
)
from ratiocinatus.phase3_contracts import (
    DiarizationCapability,
    DiarizationPolicy,
    DiarizationProviderCapabilities,
    DiarizationProviderIdentity,
    DiarizationProviderResponse,
    ObservationUsability,
    OverlapClassification,
    ProviderOverlapInterval,
    ProviderSpeakerObservation,
    ProviderSpeakerTurn,
    SpeakerTurnKind,
)
from ratiocinatus.speech_activity import detect_corpus_activity
from ratiocinatus.transcript_contracts import (
    TimestampOrigin,
    TranscriptArtifactDigest,
    TranscriptAssembly,
    TranscriptAssemblyPolicy,
    TranscriptAssemblyStatus,
    TranscriptSegment,
    TranscriptVersion,
    TranscriptWord,
)

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
NOW = datetime(2000, 1, 1, tzinfo=timezone.utc)


def _confidence() -> ConfidenceMeasure:
    return ConfidenceMeasure(
        origin=ConfidenceOrigin.PROVIDER_NATIVE,
        value=0.8,
        basis="deterministic test provider",
    )


class DeterministicDiarizationProvider(DiarizationProvider):
    def __init__(self) -> None:
        self.calls = 0

    @property
    def capabilities(self) -> DiarizationProviderCapabilities:
        return DiarizationProviderCapabilities(
            identity=DiarizationProviderIdentity(
                provider_id="test.deterministic_diarization",
                display_name="Deterministic test diarization",
                provider_version="1.0.0",
                local=True,
            ),
            capabilities=(DiarizationCapability.TURN_SEGMENTATION,),
            available=True,
        )

    def diarize(
        self,
        request,
        normalized_audio: Path,
        *,
        evidence_root: Path | None = None,
    ) -> DiarizationProviderResponse:
        self.calls += 1
        chunks = {item.chunk_id: item for item in request.chunks}
        observations = []
        turns = []
        for ordinal, evidence in enumerate(request.speech_intervals):
            normalized = evidence.normalized_audio_interval
            chunk = chunks[evidence.processing_chunk_id]
            observation_id = typed_id(
                "spkobs", request.request_id, evidence.interval_id
            )
            observation = ProviderSpeakerObservation(
                observation_id=observation_id,
                speech_interval_ids=(evidence.interval_id,),
                source_interval=evidence.source_interval,
                normalized_audio_interval=normalized,
                chunk_local_interval=MediaInterval(
                    domain=TimeDomain.CHUNK_LOCAL,
                    start_microseconds=(
                        normalized.start_microseconds
                        - chunk.corpus_interval.start_microseconds
                    ),
                    duration_microseconds=normalized.duration_microseconds,
                ),
                processing_chunk_id=evidence.processing_chunk_id,
                provider_speaker_label=f"SPEAKER_{ordinal % 2:02d}",
                acoustic_evidence_available=True,
                usability=ObservationUsability.PROVISIONAL,
                usability_confidence=_confidence(),
            )
            observations.append(observation)
            turns.append(
                ProviderSpeakerTurn(
                    provider_turn_id=f"provider-turn-{ordinal}",
                    observation_ids=(observation_id,),
                    source_interval=evidence.source_interval,
                    normalized_audio_interval=normalized,
                    provider_speaker_label=f"SPEAKER_{ordinal % 2:02d}",
                    turn_kind=SpeakerTurnKind.SINGLE_SPEAKER,
                    boundary_confidence=_confidence(),
                    assignment_confidence=_confidence(),
                )
            )
        response_id = typed_id("diaresponse", request.request_id, "test")
        normalized_hash = canonical_hash(
            {
                "request_id": request.request_id,
                "provider": request.provider.model_dump(mode="json"),
                "observations": [
                    item.model_dump(mode="json") for item in observations
                ],
                "turns": [item.model_dump(mode="json") for item in turns],
                "overlaps": [],
                "embeddings": [],
            }
        )
        return DiarizationProviderResponse(
            response_id=response_id,
            request_id=request.request_id,
            provider=request.provider,
            started_at=NOW,
            completed_at=NOW,
            observations=tuple(observations),
            turns=tuple(turns),
            raw_evidence=RawProviderEvidence(
                disposition=RawEvidenceDisposition.UNAVAILABLE,
                explanation="deterministic structured test response",
            ),
            normalized_evidence_sha256=normalized_hash,
            complete=True,
        )


def _write_fixture(path: Path) -> None:
    samples = array("h")
    for index in range(3 * 48_000):
        second = index / 48_000
        value = (
            int(0.25 * 32767 * math.sin(2 * math.pi * 440 * second))
            if 1 <= second < 2
            else 0
        )
        samples.append(value)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(48_000)
        output.writeframes(samples.tobytes())


def _prepare_case(tmp_path: Path):
    source = tmp_path / "speaker-fixture.wav"
    _write_fixture(source)
    phase1 = tmp_path / "phase1"
    ingestion = prepare_ingestion_request(source, phase1)
    run_ingestion(ingestion)
    corpus_root = (
        phase1 / "ingestions" / ingestion.ingestion_id / "corpus"
    )
    activity, _, activity_root, _ = detect_corpus_activity(
        corpus_root,
        tmp_path / "phase2",
        provider=FFmpegEnergySpeechActivityProvider(),
    )
    speech_ids = tuple(
        item.interval_id
        for item in activity.intervals
        if item.classification
        == SpeechActivityClassification.PROBABLE_SPEECH
    )
    assert speech_ids
    return corpus_root, activity_root, activity, speech_ids


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_request_identity_tracks_lineage_not_wall_clock(tmp_path: Path) -> None:
    corpus_root, _, activity, speech_ids = _prepare_case(tmp_path)
    loaded = load_corpus(corpus_root)
    provider = DeterministicDiarizationProvider()
    kwargs = {
        "selected_audio_stream_id": (
            loaded["selection"].audio.selected_stream_id
        ),
        "speech_interval_ids": speech_ids,
    }
    first = prepare_diarization_request(
        loaded["corpus"],
        loaded["audio"],
        loaded["timeline"],
        loaded["chunks"],
        activity,
        provider.capabilities.identity,
        NOW,
        **kwargs,
    )
    repeated = prepare_diarization_request(
        loaded["corpus"],
        loaded["audio"],
        loaded["timeline"],
        loaded["chunks"],
        activity,
        provider.capabilities.identity,
        datetime(2001, 1, 1, tzinfo=timezone.utc),
        **kwargs,
    )
    changed = prepare_diarization_request(
        loaded["corpus"],
        loaded["audio"],
        loaded["timeline"],
        loaded["chunks"],
        activity,
        provider.capabilities.identity,
        NOW,
        policy=DiarizationPolicy(minimum_observation_microseconds=600_000),
        **kwargs,
    )

    assert first.request_id == repeated.request_id
    assert first.configuration_hash == repeated.configuration_hash
    assert changed.request_id != first.request_id
    assert tuple(item.interval_id for item in first.speech_intervals) == speech_ids


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_diarization_persists_validates_and_reuses_without_identity(
    tmp_path: Path,
) -> None:
    corpus_root, activity_root, _, _ = _prepare_case(tmp_path)
    provider = DeterministicDiarizationProvider()
    audio_path = load_corpus(corpus_root)["audio_path"]
    before = sha256_file(audio_path)

    result = diarize_corpus(
        corpus_root,
        activity_root,
        tmp_path / "phase3",
        provider=provider,
    )
    request, response, run, report, run_root, reused = result
    assert not reused
    assert provider.calls == 1
    assert run.observations
    assert run.turns
    assert all(item.provisional_cluster_id is None for item in run.turns)
    assert report.observation_count == len(response.observations)
    assert (run_root / "request.json").is_file()
    assert (run_root / "response.json").is_file()
    assert (run_root / "run.json").is_file()
    assert sha256_file(audio_path) == before
    assert request.normalized_audio_sha256 == before

    assert main(["--json", "diarization", "inspect", str(run_root)]) == (
        EXIT_SUCCESS
    )
    assert main(["--json", "diarization", "validate", str(run_root)]) == (
        EXIT_SUCCESS
    )
    assert main(["--json", "diarization", "list-turns", str(run_root)]) == (
        EXIT_SUCCESS
    )
    assert main(
        ["--json", "diarization", "list-boundaries", str(run_root)]
    ) == EXIT_SUCCESS
    assert main(["--json", "diarization", "list-overlaps", str(run_root)]) == (
        EXIT_SUCCESS
    )
    cached = diarize_corpus(
        corpus_root,
        activity_root,
        tmp_path / "phase3",
        provider=provider,
    )
    assert cached[-1]
    assert provider.calls == 1
    assert cached[2] == run

    (run_root / "report.json").unlink()
    with pytest.raises(
        DiarizationIntegrityError, match="cache.*incomplete"
    ):
        diarize_corpus(
            corpus_root,
            activity_root,
            tmp_path / "phase3",
            provider=provider,
        )

@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_overlap_uncertain_boundaries_transcript_mapping_and_chunk_reconciliation(
    tmp_path: Path,
) -> None:
    corpus_root, _, activity, speech_ids = _prepare_case(tmp_path)
    loaded = load_corpus(corpus_root)
    evidence = next(
        item for item in activity.intervals if item.interval_id == speech_ids[0]
    )
    base = evidence.normalized_audio_interval
    margin = min(100_000, base.duration_microseconds // 4)
    observed = MediaInterval(
        domain=TimeDomain.NORMALIZED_CORPUS,
        start_microseconds=base.start_microseconds + margin,
        duration_microseconds=base.duration_microseconds - 2 * margin,
    )
    source_observed = MediaInterval(
        domain=TimeDomain.SOURCE_MEDIA,
        start_microseconds=(
            observed.start_microseconds
            + loaded["timeline"].mapping_offset_microseconds
        ),
        duration_microseconds=observed.duration_microseconds,
    )
    segment_id = typed_id("txsegment", "phase3-alignment")
    word_id = typed_id("txword", "phase3-alignment")
    tx_provider = activity.provider
    segment = TranscriptSegment(
        segment_id=segment_id,
        corpus_id=loaded["corpus"].corpus_id,
        source_id=loaded["corpus"].source_id,
        selected_audio_stream_id=(
            loaded["selection"].audio.selected_stream_id
        ),
        selected_audio_stream_index=(
            loaded["selection"].audio.selected_stream_index
        ),
        source_interval=evidence.source_interval,
        normalized_audio_interval=base,
        processing_chunk_ids=(evidence.processing_chunk_id,),
        proposed_text="alpha",
        normalized_text="alpha",
        speech_activity_evidence_ids=(evidence.interval_id,),
        provider=tx_provider,
        transcription_response_id=typed_id("txresponse", "phase3"),
        provider_observation_id=typed_id("txobs", "phase3"),
        selected_candidate_id="candidate-1",
        promotion_basis="controlled Phase 3 alignment test",
        text_confidence=_confidence(),
        timing_confidence=_confidence(),
        boundary_confidence=_confidence(),
        created_at=NOW,
        integrity_sha256="1" * 64,
    )
    word = TranscriptWord(
        word_id=word_id,
        segment_id=segment_id,
        corpus_id=loaded["corpus"].corpus_id,
        source_interval=evidence.source_interval,
        normalized_audio_interval=base,
        surface_text="alpha",
        normalized_form="alpha",
        sequence_position=0,
        recognition_confidence=_confidence(),
        timing_confidence=_confidence(),
        timestamp_origin=TimestampOrigin.PROVIDER_NATIVE,
        provider_word_id="provider-word-1",
        provider_observation_id=segment.provider_observation_id,
        provider_candidate_id=segment.selected_candidate_id,
        created_at=NOW,
        integrity_sha256="2" * 64,
    )
    policy = TranscriptAssemblyPolicy()
    version = TranscriptVersion(
        version_id=typed_id("txversion", "phase3"),
        corpus_id=loaded["corpus"].corpus_id,
        transcription_response_id=segment.transcription_response_id,
        assembly_policy=policy,
        segments=(
            TranscriptArtifactDigest(
                artifact_id=segment_id, content_sha256="1" * 64
            ),
        ),
        words=(
            TranscriptArtifactDigest(
                artifact_id=word_id, content_sha256="2" * 64
            ),
        ),
        low_confidence_regions=(),
        created_at=NOW,
        integrity_sha256="3" * 64,
    )
    transcript = TranscriptAssembly(
        assembly_id=typed_id("txassembly", "phase3"),
        source_id=loaded["corpus"].source_id,
        normalized_audio_sha256=loaded["audio"].content_sha256,
        normalized_audio_duration_microseconds=(
            loaded["chunks"].corpus_duration_microseconds
        ),
        source_mapping_offset_microseconds=(
            loaded["timeline"].mapping_offset_microseconds
        ),
        version=version,
        segments=(segment,),
        words=(word,),
        low_confidence_regions=(),
        status=TranscriptAssemblyStatus.COMPLETE,
        assembled_at=NOW,
        integrity_sha256="4" * 64,
    )
    provider = DeterministicDiarizationProvider()
    request = prepare_diarization_request(
        loaded["corpus"],
        loaded["audio"],
        loaded["timeline"],
        loaded["chunks"],
        activity,
        provider.capabilities.identity,
        NOW,
        selected_audio_stream_id=(
            loaded["selection"].audio.selected_stream_id
        ),
        speech_interval_ids=speech_ids,
        transcript=transcript,
        policy=DiarizationPolicy(
            boundary_uncertainty_microseconds=75_000,
            boundary_competition_window_microseconds=100_000,
        ),
    )

    owner_chunk = next(
        item
        for item in request.chunks
        if item.chunk_id == evidence.processing_chunk_id
    )
    duplicate_chunk = ProcessingChunk(
        chunk_id=typed_id("chunk", "phase3-duplicate-window"),
        ordinal=len(request.chunks),
        corpus_interval=MediaInterval(
            domain=TimeDomain.NORMALIZED_CORPUS,
            start_microseconds=observed.start_microseconds,
            duration_microseconds=(
                request.normalized_audio_duration_microseconds
                - observed.start_microseconds
            ),
        ),
        source_interval=MediaInterval(
            domain=TimeDomain.SOURCE_MEDIA,
            start_microseconds=(
                observed.start_microseconds
                + request.source_mapping_offset_microseconds
            ),
            duration_microseconds=(
                request.normalized_audio_duration_microseconds
                - observed.start_microseconds
            ),
        ),
        ownership_interval=MediaInterval(
            domain=TimeDomain.NORMALIZED_CORPUS,
            start_microseconds=observed.start_microseconds + margin,
            duration_microseconds=(
                request.normalized_audio_duration_microseconds
                - observed.start_microseconds
                - margin
            ),
        ),
        overlap_before_microseconds=margin,
        overlap_after_microseconds=0,
    )
    request = request.__class__.model_validate(
        {
            **request.model_dump(),
            "chunks": (*request.chunks, duplicate_chunk),
        }
    )
    canonical_id = typed_id("spkobs", request.request_id, "owned")
    duplicate_id = typed_id("spkobs", request.request_id, "duplicate")
    canonical = ProviderSpeakerObservation(
        observation_id=canonical_id,
        speech_interval_ids=(evidence.interval_id,),
        source_interval=source_observed,
        normalized_audio_interval=observed,
        chunk_local_interval=MediaInterval(
            domain=TimeDomain.CHUNK_LOCAL,
            start_microseconds=(
                observed.start_microseconds
                - owner_chunk.corpus_interval.start_microseconds
            ),
            duration_microseconds=observed.duration_microseconds,
        ),
        processing_chunk_id=owner_chunk.chunk_id,
        provider_speaker_label="SPEAKER_00",
        acoustic_evidence_available=True,
        usability=ObservationUsability.PROVISIONAL,
        usability_confidence=_confidence(),
    )
    duplicate = canonical.model_copy(
        update={
            "observation_id": duplicate_id,
            "processing_chunk_id": duplicate_chunk.chunk_id,
            "chunk_local_interval": MediaInterval(
                domain=TimeDomain.CHUNK_LOCAL,
                start_microseconds=0,
                duration_microseconds=observed.duration_microseconds,
            ),
            "canonical_owner": False,
        }
    )
    expanded = MediaInterval(
        domain=TimeDomain.NORMALIZED_CORPUS,
        start_microseconds=observed.start_microseconds - 20_000,
        duration_microseconds=observed.duration_microseconds + 40_000,
    )
    expanded_source = MediaInterval(
        domain=TimeDomain.SOURCE_MEDIA,
        start_microseconds=(
            expanded.start_microseconds
            + request.source_mapping_offset_microseconds
        ),
        duration_microseconds=expanded.duration_microseconds,
    )
    turns = (
        ProviderSpeakerTurn(
            provider_turn_id="proposal-a",
            observation_ids=(canonical_id, duplicate_id),
            source_interval=source_observed,
            normalized_audio_interval=observed,
            provider_speaker_label="SPEAKER_00",
            turn_kind=SpeakerTurnKind.SINGLE_SPEAKER,
            boundary_confidence=_confidence(),
            assignment_confidence=_confidence(),
        ),
        ProviderSpeakerTurn(
            provider_turn_id="proposal-b",
            observation_ids=(duplicate_id,),
            source_interval=expanded_source,
            normalized_audio_interval=expanded,
            provider_speaker_label="SPEAKER_00",
            turn_kind=SpeakerTurnKind.UNCERTAIN_SPEAKER,
            boundary_confidence=ConfidenceMeasure(
                origin=ConfidenceOrigin.UNAVAILABLE,
                basis="provider supplied competing boundary only",
            ),
            assignment_confidence=_confidence(),
        ),
    )
    overlap_normalized = MediaInterval(
        domain=TimeDomain.NORMALIZED_CORPUS,
        start_microseconds=(
            observed.start_microseconds
            + observed.duration_microseconds // 4
        ),
        duration_microseconds=observed.duration_microseconds // 2,
    )
    overlap = ProviderOverlapInterval(
        provider_overlap_id="overlap-1",
        source_interval=MediaInterval(
            domain=TimeDomain.SOURCE_MEDIA,
            start_microseconds=(
                overlap_normalized.start_microseconds
                + request.source_mapping_offset_microseconds
            ),
            duration_microseconds=overlap_normalized.duration_microseconds,
        ),
        normalized_audio_interval=overlap_normalized,
        classification=OverlapClassification.SIMULTANEOUS_SPEECH,
        estimated_active_speaker_count=2,
        candidate_provider_labels=("SPEAKER_00", "SPEAKER_01"),
        overlap_confidence=_confidence(),
        speaker_count_confidence=_confidence(),
    )
    response_id = typed_id("diaresponse", request.request_id, "overlap")
    observations = (canonical, duplicate)
    normalized_hash = canonical_hash(
        {
            "request_id": request.request_id,
            "provider": request.provider.model_dump(mode="json"),
            "observations": [
                item.model_dump(mode="json") for item in observations
            ],
            "turns": [item.model_dump(mode="json") for item in turns],
            "overlaps": [overlap.model_dump(mode="json")],
            "embeddings": [],
        }
    )
    response = DiarizationProviderResponse(
        response_id=response_id,
        request_id=request.request_id,
        provider=request.provider,
        started_at=NOW,
        completed_at=NOW,
        observations=observations,
        turns=turns,
        overlaps=(overlap,),
        raw_evidence=RawProviderEvidence(
            disposition=RawEvidenceDisposition.UNAVAILABLE,
            explanation="controlled overlap response",
        ),
        normalized_evidence_sha256=normalized_hash,
        complete=True,
    )

    validate_diarization_response(response, request, tmp_path)
    run = _canonicalize(request, response)
    assert len(run.observations) == 1
    assert len(run.turns) == 2
    assert all(item.observation_ids == (canonical_id,) for item in run.turns)
    assert all(segment_id in item.transcript_segment_ids for item in run.turns)
    assert all(word_id in item.transcript_word_ids for item in run.turns)
    assert len(run.overlaps) == 1
    assert run.overlaps[0].observation_ids == (canonical_id,)
    assert run.overlaps[0].partially_attributed
    assert all(item.uncertainty_microseconds == 75_000 for item in run.boundaries)
    assert any(item.inside_transcript_artifact_ids for item in run.boundaries)
    assert any(item.competing_boundary_ids for item in run.boundaries)
    assert all(item.review_required for item in run.boundaries)
    invalid_overlap = overlap.model_copy(
        update={
            "source_interval": overlap.source_interval.model_copy(
                update={
                    "start_microseconds": (
                        overlap.source_interval.start_microseconds + 1
                    )
                }
            )
        }
    )
    invalid_hash = canonical_hash(
        {
            "request_id": request.request_id,
            "provider": request.provider.model_dump(mode="json"),
            "observations": [
                item.model_dump(mode="json") for item in observations
            ],
            "turns": [item.model_dump(mode="json") for item in turns],
            "overlaps": [invalid_overlap.model_dump(mode="json")],
            "embeddings": [],
        }
    )
    invalid_response = response.model_copy(
        update={
            "overlaps": (invalid_overlap,),
            "normalized_evidence_sha256": invalid_hash,
        }
    )
    with pytest.raises(
        DiarizationIntegrityError, match="overlap interval source mapping"
    ):
        validate_diarization_response(invalid_response, request, tmp_path)