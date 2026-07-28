"""Stable Phase 2 request preparation over the Phase 1 corpus boundary."""

from __future__ import annotations

from datetime import datetime

from .addressing_contracts import SourceTimeline
from .chunk_contracts import ProcessingChunkPlan
from .corpus_contracts import AudiovisualCorpus
from .kernel import canonical_hash, typed_id
from .normalization_contracts import AudioDerivative
from .phase2_contracts import (
    SpeechActivityPolicy,
    SpeechActivityRequest,
    SpeechActivityRun,
    SpeechEvidenceProviderIdentity,
    TranscriptionPolicy,
    TranscriptionRequest,
)


def prepare_speech_activity_request(
    corpus: AudiovisualCorpus,
    audio: AudioDerivative,
    timeline: SourceTimeline,
    chunks: ProcessingChunkPlan,
    provider: SpeechEvidenceProviderIdentity,
    requested_at: datetime,
    *,
    policy: SpeechActivityPolicy | None = None,
) -> SpeechActivityRequest:
    """Create a content/configuration-stable request without reading audio."""

    policy = policy or SpeechActivityPolicy()
    if audio.source_id != corpus.source_id:
        raise ValueError("normalized audio belongs to a different source")
    if audio.content_sha256 != corpus.normalized_audio.content_sha256:
        raise ValueError("normalized audio hash does not match corpus")
    if timeline.source_id != corpus.source_id:
        raise ValueError("timeline belongs to a different source")
    if chunks.source_id != corpus.source_id:
        raise ValueError("chunk plan belongs to a different source")
    duration_difference = abs(
        chunks.corpus_duration_microseconds - audio.duration_microseconds
    )
    if duration_difference > audio.interval_mapping.tolerance_microseconds:
        raise ValueError(
            "chunk plan and normalized audio durations exceed mapping tolerance"
        )
    configuration_hash = canonical_hash(
        {
            "operation": "speech_activity.detect",
            "policy": policy.model_dump(mode="json"),
            "provider": provider.model_dump(mode="json"),
            "chunk_plan_id": chunks.plan_id,
        }
    )
    request_id = typed_id(
        "sareq",
        corpus.corpus_id,
        corpus.source_id,
        audio.content_sha256,
        chunks.plan_id,
        configuration_hash,
    )
    return SpeechActivityRequest(
        request_id=request_id,
        requested_at=requested_at,
        corpus_id=corpus.corpus_id,
        source_id=corpus.source_id,
        normalized_audio_sha256=audio.content_sha256,
        normalized_audio_duration_microseconds=(
            chunks.corpus_duration_microseconds
        ),
        audio_derivative_duration_microseconds=audio.duration_microseconds,
        chunk_plan_id=chunks.plan_id,
        chunks=chunks.chunks,
        source_mapping_offset_microseconds=timeline.mapping_offset_microseconds,
        policy=policy,
        provider=provider,
        configuration_hash=configuration_hash,
    )


def prepare_transcription_request(
    speech_activity: SpeechActivityRun,
    provider: SpeechEvidenceProviderIdentity,
    requested_at: datetime,
    *,
    speech_interval_ids: tuple[str, ...],
    policy: TranscriptionPolicy | None = None,
) -> TranscriptionRequest:
    """Create a stable transcription request for explicit activity intervals."""

    policy = policy or TranscriptionPolicy()
    if not speech_activity.complete:
        raise ValueError("cannot transcribe an incomplete speech activity run")
    known = {
        item.interval_id: item
        for item in speech_activity.intervals
        if item.canonical_owner
    }
    if not speech_interval_ids:
        raise ValueError("transcription requires at least one interval")
    if len(speech_interval_ids) != len(set(speech_interval_ids)):
        raise ValueError("transcription interval identities must be unique")
    missing = set(speech_interval_ids) - set(known)
    if missing:
        raise ValueError(
            "transcription references unknown or non-canonical intervals: "
            + ", ".join(sorted(missing))
        )
    selected_intervals = tuple(known[item] for item in speech_interval_ids)
    configuration_hash = canonical_hash(
        {
            "operation": "speech.transcribe",
            "speech_activity_run_id": speech_activity.run_id,
            "speech_interval_ids": speech_interval_ids,
            "policy": policy.model_dump(mode="json"),
            "provider": provider.model_dump(mode="json"),
        }
    )
    request_id = typed_id(
        "txreq",
        speech_activity.request.corpus_id,
        speech_activity.run_id,
        speech_interval_ids,
        configuration_hash,
    )
    return TranscriptionRequest(
        request_id=request_id,
        requested_at=requested_at,
        corpus_id=speech_activity.request.corpus_id,
        source_id=speech_activity.request.source_id,
        normalized_audio_sha256=speech_activity.request.normalized_audio_sha256,
        normalized_audio_duration_microseconds=(
            speech_activity.request.normalized_audio_duration_microseconds
        ),
        source_mapping_offset_microseconds=(
            speech_activity.request.source_mapping_offset_microseconds
        ),
        speech_activity_run_id=speech_activity.run_id,
        speech_interval_ids=speech_interval_ids,
        speech_intervals=selected_intervals,
        policy=policy,
        provider=provider,
        configuration_hash=configuration_hash,
    )
