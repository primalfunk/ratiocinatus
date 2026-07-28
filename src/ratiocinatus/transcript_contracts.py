"""Canonical transcript assembly and low-confidence contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .addressing_contracts import MediaInterval, TimeDomain
from .contracts import Contract, Sha256
from .phase2_contracts import (
    ConfidenceMeasure,
    SpeechEvidenceProviderIdentity,
    TimestampOrigin,
)

TRANSCRIPT_FORMAT_VERSION = "1.0.0"
TRANSCRIPT_ASSEMBLY_POLICY_VERSION = "1.0.0"


class LowConfidenceClassification(str, Enum):
    LOW_SPEECH_PROBABILITY = "low_speech_probability"
    LOW_TRANSCRIPTION_CONFIDENCE = "low_transcription_confidence"
    UNAVAILABLE_TRANSCRIPTION_CONFIDENCE = (
        "unavailable_transcription_confidence"
    )
    LOW_TEMPORAL_ALIGNMENT_CONFIDENCE = (
        "low_temporal_alignment_confidence"
    )
    UNAVAILABLE_TEMPORAL_ALIGNMENT_CONFIDENCE = (
        "unavailable_temporal_alignment_confidence"
    )
    UNCERTAIN_SEGMENT_BOUNDARY = "uncertain_segment_boundary"
    CANDIDATE_DISAGREEMENT = "candidate_disagreement"
    PROBABLE_OVERLAP = "probable_overlap"
    CLIPPING = "clipping"
    NOISE = "noise"
    MUSIC = "music"
    REVERBERATION = "reverberation"
    DISTORTION = "distortion"
    UNSUPPORTED_LANGUAGE = "unsupported_language"
    RAPID_SPEECH = "rapid_speech"
    INCOMPLETE_BOUNDARY_WORD = "incomplete_boundary_word"
    PROVIDER_ERROR = "provider_error"
    MISSING_OUTPUT = "missing_output"
    FAILED_VALIDATION = "failed_validation"


class ReviewSeverity(str, Enum):
    INFORMATION = "information"
    WARNING = "warning"
    ERROR = "error"
    BLOCKING = "blocking"


class TranscriptAssemblyStatus(str, Enum):
    COMPLETE = "complete"
    REVIEW_REQUIRED = "review_required"
    BLOCKED = "blocked"


class TranscriptAssemblyPolicy(Contract):
    policy_version: Literal["1.0.0"] = TRANSCRIPT_ASSEMBLY_POLICY_VERSION
    text_normalization: Literal[
        "unicode_nfkc_case_preserving_whitespace_v1"
    ] = "unicode_nfkc_case_preserving_whitespace_v1"
    minimum_speech_presence_confidence: float = Field(default=0.50, ge=0.0, le=1.0)
    minimum_text_confidence: float = Field(default=0.50, ge=0.0, le=1.0)
    minimum_word_confidence: float = Field(default=0.50, ge=0.0, le=1.0)
    minimum_timing_confidence: float = Field(default=0.50, ge=0.0, le=1.0)
    minimum_boundary_confidence: float = Field(default=0.50, ge=0.0, le=1.0)
    review_unavailable_text_confidence: bool = True
    review_unavailable_timing_confidence: bool = True
    review_uncertain_boundaries: bool = True
    block_unresolved_observations: bool = True
    block_low_text_confidence: bool = False
    block_unavailable_text_confidence: bool = False


class TranscriptSegment(Contract):
    format_version: Literal["1.0.0"] = TRANSCRIPT_FORMAT_VERSION
    policy_version: Literal["1.0.0"] = TRANSCRIPT_ASSEMBLY_POLICY_VERSION
    segment_id: str = Field(pattern=r"^txsegment_[a-f0-9]{32}$")
    corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    source_id: str = Field(pattern=r"^src_[a-f0-9]{32}$")
    selected_audio_stream_id: str = Field(pattern=r"^stream_[a-f0-9]{32}$")
    selected_audio_stream_index: int = Field(ge=0)
    source_interval: MediaInterval
    normalized_audio_interval: MediaInterval
    processing_chunk_ids: tuple[str, ...] = Field(min_length=1)
    proposed_text: str = Field(min_length=1)
    normalized_text: str = Field(min_length=1)
    language_claim: str | None = None
    speech_activity_evidence_ids: tuple[str, ...] = Field(min_length=1)
    provider: SpeechEvidenceProviderIdentity
    transcription_response_id: str = Field(
        pattern=r"^txresponse_[a-f0-9]{32}$"
    )
    provider_observation_id: str = Field(pattern=r"^txobs_[a-f0-9]{32}$")
    selected_candidate_id: str = Field(min_length=1)
    promotion_basis: str = Field(min_length=1)
    text_confidence: ConfidenceMeasure
    timing_confidence: ConfidenceMeasure
    boundary_confidence: ConfidenceMeasure
    alternative_candidate_ids: tuple[str, ...] = ()
    low_confidence_classifications: tuple[
        LowConfidenceClassification, ...
    ] = ()
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def mapping_is_consistent(self) -> "TranscriptSegment":
        if self.source_interval.domain != TimeDomain.SOURCE_MEDIA:
            raise ValueError("transcript segment source interval has wrong domain")
        if self.normalized_audio_interval.domain != TimeDomain.NORMALIZED_CORPUS:
            raise ValueError(
                "transcript segment normalized interval has wrong domain"
            )
        if (
            self.source_interval.duration_microseconds
            != self.normalized_audio_interval.duration_microseconds
        ):
            raise ValueError("transcript segment mapped durations disagree")
        if len(self.processing_chunk_ids) != len(set(self.processing_chunk_ids)):
            raise ValueError("transcript segment chunk references must be unique")
        if len(self.speech_activity_evidence_ids) != len(
            set(self.speech_activity_evidence_ids)
        ):
            raise ValueError("transcript segment speech references must be unique")
        if self.selected_candidate_id in self.alternative_candidate_ids:
            raise ValueError("selected candidate cannot also be an alternative")
        return self


class TranscriptWord(Contract):
    format_version: Literal["1.0.0"] = TRANSCRIPT_FORMAT_VERSION
    policy_version: Literal["1.0.0"] = TRANSCRIPT_ASSEMBLY_POLICY_VERSION
    word_id: str = Field(pattern=r"^txword_[a-f0-9]{32}$")
    segment_id: str = Field(pattern=r"^txsegment_[a-f0-9]{32}$")
    corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    source_interval: MediaInterval
    normalized_audio_interval: MediaInterval
    surface_text: str = Field(min_length=1)
    normalized_form: str = Field(min_length=1)
    sequence_position: int = Field(ge=0)
    recognition_confidence: ConfidenceMeasure
    timing_confidence: ConfidenceMeasure
    timestamp_origin: TimestampOrigin
    boundary_uncertainty_microseconds: int | None = Field(default=None, ge=0)
    provider_token_reference: str | None = None
    provider_word_id: str = Field(min_length=1)
    provider_observation_id: str = Field(pattern=r"^txobs_[a-f0-9]{32}$")
    provider_candidate_id: str = Field(min_length=1)
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def mapping_is_consistent(self) -> "TranscriptWord":
        if self.timestamp_origin == TimestampOrigin.UNAVAILABLE:
            raise ValueError("canonical word requires an explicit timestamp origin")
        if self.source_interval.domain != TimeDomain.SOURCE_MEDIA:
            raise ValueError("transcript word source interval has wrong domain")
        if self.normalized_audio_interval.domain != TimeDomain.NORMALIZED_CORPUS:
            raise ValueError("transcript word normalized interval has wrong domain")
        if (
            self.source_interval.duration_microseconds
            != self.normalized_audio_interval.duration_microseconds
        ):
            raise ValueError("transcript word mapped durations disagree")
        return self


class LowConfidenceRegion(Contract):
    format_version: Literal["1.0.0"] = TRANSCRIPT_FORMAT_VERSION
    policy_version: Literal["1.0.0"] = TRANSCRIPT_ASSEMBLY_POLICY_VERSION
    region_id: str = Field(pattern=r"^lowconf_[a-f0-9]{32}$")
    corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    segment_id: str | None = Field(
        default=None, pattern=r"^txsegment_[a-f0-9]{32}$"
    )
    word_id: str | None = Field(
        default=None, pattern=r"^txword_[a-f0-9]{32}$"
    )
    source_interval: MediaInterval
    normalized_audio_interval: MediaInterval
    classification: LowConfidenceClassification
    severity: ReviewSeverity
    evidence_references: tuple[str, ...] = Field(min_length=1)
    policy_basis: str = Field(min_length=1)
    review_recommended: bool
    blocks_downstream_use: bool
    explanation: str = Field(min_length=1)
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def mapping_is_consistent(self) -> "LowConfidenceRegion":
        if self.source_interval.domain != TimeDomain.SOURCE_MEDIA:
            raise ValueError("low-confidence source interval has wrong domain")
        if self.normalized_audio_interval.domain != TimeDomain.NORMALIZED_CORPUS:
            raise ValueError("low-confidence normalized interval has wrong domain")
        if (
            self.source_interval.duration_microseconds
            != self.normalized_audio_interval.duration_microseconds
        ):
            raise ValueError("low-confidence mapped durations disagree")
        if self.word_id is not None and self.segment_id is None:
            raise ValueError("word low-confidence region requires parent segment")
        if self.blocks_downstream_use and self.severity != ReviewSeverity.BLOCKING:
            raise ValueError("blocking region requires blocking severity")
        return self


class TranscriptArtifactDigest(Contract):
    artifact_id: str = Field(min_length=1)
    content_sha256: Sha256


class TranscriptVersion(Contract):
    format_version: Literal["1.0.0"] = TRANSCRIPT_FORMAT_VERSION
    version_id: str = Field(pattern=r"^txversion_[a-f0-9]{32}$")
    corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    transcription_response_id: str = Field(
        pattern=r"^txresponse_[a-f0-9]{32}$"
    )
    predecessor_version_id: str | None = Field(
        default=None, pattern=r"^txversion_[a-f0-9]{32}$"
    )
    version_kind: Literal["original_machine", "corrected"] = "original_machine"
    assembly_policy: TranscriptAssemblyPolicy
    segments: tuple[TranscriptArtifactDigest, ...]
    words: tuple[TranscriptArtifactDigest, ...]
    low_confidence_regions: tuple[TranscriptArtifactDigest, ...]
    corrections: tuple[TranscriptArtifactDigest, ...] = ()
    created_at: datetime
    integrity_sha256: Sha256


class TranscriptAssembly(Contract):
    format_version: Literal["1.0.0"] = TRANSCRIPT_FORMAT_VERSION
    assembly_id: str = Field(pattern=r"^txassembly_[a-f0-9]{32}$")
    source_id: str = Field(pattern=r"^src_[a-f0-9]{32}$")
    normalized_audio_sha256: Sha256
    normalized_audio_duration_microseconds: int = Field(gt=0)
    source_mapping_offset_microseconds: int
    version: TranscriptVersion
    segments: tuple[TranscriptSegment, ...]
    words: tuple[TranscriptWord, ...]
    low_confidence_regions: tuple[LowConfidenceRegion, ...]
    validation_findings: tuple[str, ...] = ()
    status: TranscriptAssemblyStatus
    assembled_at: datetime
    integrity_sha256: Sha256


class LowConfidenceSummary(Contract):
    classification: LowConfidenceClassification
    region_count: int = Field(ge=0)
    duration_microseconds: int = Field(ge=0)
    blocking_region_count: int = Field(ge=0)


class TranscriptAssemblyReport(Contract):
    format_version: Literal["1.0.0"] = TRANSCRIPT_FORMAT_VERSION
    report_id: str = Field(pattern=r"^txassemblyreport_[a-f0-9]{32}$")
    assembly_id: str = Field(pattern=r"^txassembly_[a-f0-9]{32}$")
    version_id: str = Field(pattern=r"^txversion_[a-f0-9]{32}$")
    corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    generated_at: datetime
    segment_count: int = Field(ge=0)
    word_count: int = Field(ge=0)
    low_confidence: tuple[LowConfidenceSummary, ...]
    review_region_count: int = Field(ge=0)
    blocking_region_count: int = Field(ge=0)
    validation_findings: tuple[str, ...] = ()
    status: TranscriptAssemblyStatus


TRANSCRIPT_CONTRACT_MODELS = (
    TranscriptAssemblyPolicy,
    TranscriptSegment,
    TranscriptWord,
    LowConfidenceRegion,
    TranscriptArtifactDigest,
    TranscriptVersion,
    TranscriptAssembly,
    LowConfidenceSummary,
    TranscriptAssemblyReport,
)
