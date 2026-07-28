"""Stable Phase 3 request preparation over validated Phase 1/2 evidence."""

from __future__ import annotations

from datetime import datetime

from .addressing_contracts import SourceTimeline
from .chunk_contracts import ProcessingChunkPlan
from .corpus_contracts import AudiovisualCorpus
from .kernel import canonical_hash, typed_id
from .normalization_contracts import AudioDerivative
from .phase2_contracts import SpeechActivityRun
from .phase3_contracts import (
    DiarizationPolicy,
    DiarizationProviderIdentity,
    DiarizationRequest,
)
from .transcript_contracts import TranscriptAssembly


def prepare_diarization_request(
    corpus: AudiovisualCorpus,
    audio: AudioDerivative,
    timeline: SourceTimeline,
    chunks: ProcessingChunkPlan,
    speech_activity: SpeechActivityRun,
    provider: DiarizationProviderIdentity,
    requested_at: datetime,
    *,
    selected_audio_stream_id: str,
    speech_interval_ids: tuple[str, ...],
    policy: DiarizationPolicy | None = None,
    transcript: TranscriptAssembly | None = None,
) -> DiarizationRequest:
    """Create a content/configuration-stable diarization request."""

    policy = policy or DiarizationPolicy()
    if audio.source_id != corpus.source_id:
        raise ValueError("normalized audio belongs to a different source")
    if audio.content_sha256 != corpus.normalized_audio.content_sha256:
        raise ValueError("normalized audio hash does not match corpus")
    if timeline.source_id != corpus.source_id:
        raise ValueError("timeline belongs to a different source")
    if chunks.source_id != corpus.source_id:
        raise ValueError("chunk plan belongs to a different source")
    if speech_activity.request.corpus_id != corpus.corpus_id:
        raise ValueError("speech activity belongs to a different corpus")
    if speech_activity.request.source_id != corpus.source_id:
        raise ValueError("speech activity belongs to a different source")
    if (
        speech_activity.request.normalized_audio_sha256
        != audio.content_sha256
    ):
        raise ValueError("speech activity uses different normalized audio")
    if speech_activity.request.chunk_plan_id != chunks.plan_id:
        raise ValueError("speech activity uses a different chunk plan")
    if not speech_activity.complete:
        raise ValueError("cannot diarize an incomplete speech activity run")

    known = {
        item.interval_id: item
        for item in speech_activity.intervals
        if item.canonical_owner
    }
    if not speech_interval_ids:
        raise ValueError("diarization requires at least one speech interval")
    if len(speech_interval_ids) != len(set(speech_interval_ids)):
        raise ValueError("diarization interval identities must be unique")
    missing = set(speech_interval_ids) - set(known)
    if missing:
        raise ValueError(
            "diarization references unknown or non-canonical intervals: "
            + ", ".join(sorted(missing))
        )
    selected_intervals = tuple(known[item] for item in speech_interval_ids)

    assembly_id = None
    version_id = None
    transcript_segment_ids: tuple[str, ...] = ()
    transcript_segments = ()
    transcript_words = ()
    if transcript is not None:
        if transcript.version.corpus_id != corpus.corpus_id:
            raise ValueError("transcript belongs to a different corpus")
        if transcript.source_id != corpus.source_id:
            raise ValueError("transcript belongs to a different source")
        if transcript.normalized_audio_sha256 != audio.content_sha256:
            raise ValueError("transcript uses different normalized audio")
        if (
            transcript.normalized_audio_duration_microseconds
            != chunks.corpus_duration_microseconds
        ):
            raise ValueError("transcript duration differs from the corpus")
        if (
            transcript.source_mapping_offset_microseconds
            != timeline.mapping_offset_microseconds
        ):
            raise ValueError("transcript source mapping differs from the corpus")
        assembly_id = transcript.assembly_id
        version_id = transcript.version.version_id
        transcript_segment_ids = tuple(
            item.segment_id for item in transcript.segments
        )
        transcript_segments = transcript.segments
        transcript_words = transcript.words

    configuration_hash = canonical_hash(
        {
            "operation": "speaker.diarize",
            "speech_activity_run_id": speech_activity.run_id,
            "speech_interval_ids": speech_interval_ids,
            "transcript_assembly_id": assembly_id,
            "transcript_version_id": version_id,
            "transcript_integrity_sha256": (
                transcript.integrity_sha256 if transcript is not None else None
            ),
            "transcript_version_integrity_sha256": (
                transcript.version.integrity_sha256
                if transcript is not None
                else None
            ),
            "chunk_plan_id": chunks.plan_id,
            "policy": policy.model_dump(mode="json"),
            "provider": provider.model_dump(mode="json"),
        }
    )
    request_id = typed_id(
        "diareq",
        corpus.corpus_id,
        speech_activity.run_id,
        speech_interval_ids,
        assembly_id,
        version_id,
        configuration_hash,
    )
    return DiarizationRequest(
        request_id=request_id,
        requested_at=requested_at,
        corpus_id=corpus.corpus_id,
        source_id=corpus.source_id,
        selected_audio_stream_id=selected_audio_stream_id,
        normalized_audio_sha256=audio.content_sha256,
        normalized_audio_duration_microseconds=(
            chunks.corpus_duration_microseconds
        ),
        source_mapping_offset_microseconds=timeline.mapping_offset_microseconds,
        speech_activity_run_id=speech_activity.run_id,
        speech_interval_ids=speech_interval_ids,
        speech_intervals=selected_intervals,
        transcript_assembly_id=assembly_id,
        transcript_version_id=version_id,
        transcript_segment_ids=transcript_segment_ids,
        transcript_segments=transcript_segments,
        transcript_words=transcript_words,
        chunks=chunks.chunks,
        policy=policy,
        provider=provider,
        configuration_hash=configuration_hash,
    )
