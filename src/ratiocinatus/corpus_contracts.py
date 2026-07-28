"""Portable audiovisual corpus and resumable ingestion contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .chunk_contracts import ChunkPolicy
from .contracts import Contract, IntegrityState, Sha256, SourceFingerprint
from .normalization_contracts import AudioNormalizationPolicy, CacheKey
from .qualification_contracts import DecodeQualificationPolicy
from .selection_contracts import StreamSelectionPolicy
from .video_contracts import VideoNormalizationPolicy

CORPUS_FORMAT_VERSION = "1.0.0"
INGESTION_FORMAT_VERSION = "1.0.0"


class IngestionStage(str, Enum):
    SOURCE_VERIFIED = "source_verified"
    INSPECTION_COMMITTED = "inspection_committed"
    SELECTION_COMMITTED = "selection_committed"
    QUALIFICATION_COMMITTED = "qualification_committed"
    AUDIO_NORMALIZATION_COMMITTED = "audio_normalization_committed"
    VIDEO_ACCESS_COMMITTED = "video_access_committed"
    TIMELINE_COMMITTED = "timeline_committed"
    CHUNK_PLAN_COMMITTED = "chunk_plan_committed"
    CORPUS_COMMITTED = "corpus_committed"
    REPORTS_COMMITTED = "reports_committed"
    COMPLETE = "complete"


class IngestionStageStatus(str, Enum):
    COMMITTED = "committed"
    REUSED = "reused"
    INVALIDATED = "invalidated"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class CorpusArtifactReference(Contract):
    artifact_type: str = Field(min_length=1)
    relative_path: str = Field(min_length=1)
    content_sha256: Sha256
    byte_size: int = Field(gt=0)


class IngestionPolicy(Contract):
    copy_source: Literal[True] = True
    selection: StreamSelectionPolicy = StreamSelectionPolicy()
    qualification: DecodeQualificationPolicy = DecodeQualificationPolicy()
    audio: AudioNormalizationPolicy = AudioNormalizationPolicy()
    video: VideoNormalizationPolicy = VideoNormalizationPolicy()
    chunks: ChunkPolicy = ChunkPolicy()


class IngestionRequest(Contract):
    format_version: Literal["1.0.0"] = INGESTION_FORMAT_VERSION
    ingestion_id: str = Field(pattern=r"^ingestion_[a-f0-9]{32}$")
    requested_at: datetime
    source: str
    workspace: str
    source_fingerprint: SourceFingerprint
    policy: IngestionPolicy
    configuration_hash: Sha256
    ffprobe: str
    ffmpeg: str
    external_tool_identity_hashes: tuple[Sha256, Sha256]


class IngestionStageRecord(Contract):
    stage: IngestionStage
    status: IngestionStageStatus
    attempt_id: str = Field(pattern=r"^attempt_[a-f0-9]{32}$")
    recorded_at: datetime
    artifact: CorpusArtifactReference | None = None
    message: str | None = None


class IngestionCheckpoint(Contract):
    format_version: Literal["1.0.0"] = INGESTION_FORMAT_VERSION
    ingestion_id: str = Field(pattern=r"^ingestion_[a-f0-9]{32}$")
    source_fingerprint: SourceFingerprint
    configuration_hash: Sha256
    latest_committed_stage: IngestionStage | None = None
    records: tuple[IngestionStageRecord, ...] = ()
    complete: bool = False


class IngestionManifest(Contract):
    format_version: Literal["1.0.0"] = INGESTION_FORMAT_VERSION
    request: IngestionRequest
    checkpoint: IngestionCheckpoint
    corpus: CorpusArtifactReference | None = None


class AudiovisualCorpus(Contract):
    format_version: Literal["1.0.0"] = CORPUS_FORMAT_VERSION
    corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    created_at: datetime
    source_id: str = Field(pattern=r"^src_[a-f0-9]{32}$")
    source_fingerprint: SourceFingerprint
    source: CorpusArtifactReference
    inspection: CorpusArtifactReference
    selection: CorpusArtifactReference
    qualification: CorpusArtifactReference
    timeline: CorpusArtifactReference
    normalized_audio: CorpusArtifactReference
    normalized_audio_manifest: CorpusArtifactReference
    video_access: CorpusArtifactReference
    chunk_plan: CorpusArtifactReference
    cache_keys: tuple[CacheKey, ...] = ()
    configuration_hash: Sha256
    integrity: IntegrityState
    provenance: tuple[CorpusArtifactReference, ...]
    complete: bool

    @model_validator(mode="after")
    def completed_corpus_is_valid(self) -> "AudiovisualCorpus":
        if self.complete and self.integrity != IntegrityState.VALID:
            raise ValueError("complete corpus must have valid integrity")
        return self


class CorpusIntegrityReport(Contract):
    format_version: Literal["1.0.0"] = CORPUS_FORMAT_VERSION
    corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    generated_at: datetime
    valid: bool
    checked_artifacts: int = Field(ge=0)
    findings: tuple[str, ...] = ()


class NormalizedSourceReport(Contract):
    format_version: Literal["1.0.0"] = CORPUS_FORMAT_VERSION
    corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    generated_at: datetime
    source_id: str = Field(pattern=r"^src_[a-f0-9]{32}$")
    source_bytes: int = Field(gt=0)
    source_duration_microseconds: int = Field(gt=0)
    audio_derivative_bytes: int = Field(gt=0)
    audio_duration_microseconds: int = Field(gt=0)
    video_strategy: str
    chunk_count: int = Field(gt=0)
    cache_ids: tuple[str, ...]
    status: Literal["complete", "partial", "warning", "failed"]


CORPUS_CONTRACT_MODELS = (
    CorpusArtifactReference,
    IngestionPolicy,
    IngestionRequest,
    IngestionStageRecord,
    IngestionCheckpoint,
    IngestionManifest,
    AudiovisualCorpus,
    CorpusIntegrityReport,
    NormalizedSourceReport,
)
