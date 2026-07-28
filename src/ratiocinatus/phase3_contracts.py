"""Phase 3 diarization and participant-identity evidence boundaries."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .addressing_contracts import MediaInterval, TimeDomain
from .chunk_contracts import ProcessingChunk
from .contracts import Contract, Sha256
from .phase1_contracts import ToolInvocationRecord
from .phase2_contracts import (
    ConfidenceMeasure,
    RawProviderEvidence,
    SpeechActivityInterval,
)
from .transcript_contracts import TranscriptSegment, TranscriptWord

PHASE3_FORMAT_VERSION = "1.0.0"
DIARIZATION_POLICY_VERSION = "1.0.0"
EMBEDDING_POLICY_VERSION = "1.0.0"
IDENTITY_POLICY_VERSION = "1.0.0"


class DiarizationCapability(str, Enum):
    TURN_SEGMENTATION = "turn_segmentation"
    OVERLAPPING_SPEECH = "overlapping_speech"
    SPEAKER_EMBEDDINGS = "speaker_embeddings"
    SPEAKER_CLUSTERING = "speaker_clustering"


class DiarizationFailureKind(str, Enum):
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    MODEL_UNAVAILABLE = "model_unavailable"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    MALFORMED_OUTPUT = "malformed_output"
    UNSUPPORTED_AUDIO = "unsupported_audio"
    VALIDATION_FAILURE = "validation_failure"
    INTERNAL_FAILURE = "internal_failure"


class ObservationUsability(str, Enum):
    USABLE = "usable"
    PROVISIONAL = "provisional"
    TOO_SHORT = "too_short"
    OVERLAPPED = "overlapped"
    CONTAMINATED = "contaminated"
    UNUSABLE = "unusable"
    UNKNOWN = "unknown"


class SpeakerTurnKind(str, Enum):
    SINGLE_SPEAKER = "single_speaker"
    DOMINANT_WITH_BACKGROUND = "dominant_with_background"
    OVERLAPPING_SPEAKERS = "overlapping_speakers"
    UNCERTAIN_SPEAKER = "uncertain_speaker"
    UNASSIGNED_SPEECH = "unassigned_speech"
    NON_LEXICAL_VOCALIZATION = "non_lexical_vocalization"
    UNUSABLE_AUDIO = "unusable_audio"


class OverlapClassification(str, Enum):
    SIMULTANEOUS_SPEECH = "simultaneous_speech"
    RAPID_TURN_EXCHANGE = "rapid_turn_exchange"
    CROSS_TALK = "cross_talk"
    BACKGROUND_SPEECH = "background_speech"
    AUDIENCE_REACTION = "audience_reaction"
    REPLAYED_OR_BROADCAST = "replayed_or_broadcast"
    UNCERTAIN = "uncertain"


class EmbeddingStorageDisposition(str, Enum):
    OMITTED = "omitted"
    PROTECTED_REFERENCE = "protected_reference"
    ENCRYPTED_ARTIFACT = "encrypted_artifact"


class ClusterStatus(str, Enum):
    PROVISIONAL = "provisional"
    UNRESOLVED = "unresolved"
    SUPERSEDED = "superseded"
    INVALID = "invalid"


class IdentityKind(str, Enum):
    NAMED_INDIVIDUAL = "named_individual"
    LOCAL_PARTICIPANT = "local_participant"
    ROLE_DEFINED = "role_defined"
    MODERATOR = "moderator"
    AUDIENCE_MEMBER = "audience_member"
    REMOTE_OR_RECORDED_VOICE = "remote_or_recorded_voice"
    INSTITUTIONAL_ANNOUNCER = "institutional_announcer"
    UNRESOLVED_PLACEHOLDER = "unresolved_placeholder"


class IdentityStatus(str, Enum):
    PROVISIONAL = "provisional"
    ACTIVE = "active"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    UNRESOLVED = "unresolved"


class IdentityScopeKind(str, Enum):
    OBSERVATION = "observation"
    SPEAKER_TURN = "speaker_turn"
    LOCAL_SEGMENT = "local_segment"
    CLUSTER = "cluster"
    RECORDING = "recording"
    RECORDING_SERIES = "recording_series"
    CORPUS = "corpus"


class IdentityHypothesisSource(str, Enum):
    REFERENCE_VOICE_COMPARISON = "reference_voice_comparison"
    TRUSTED_EVENT_METADATA = "trusted_event_metadata"
    TRANSCRIPT_SELF_IDENTIFICATION = "transcript_self_identification"
    MODERATOR_INTRODUCTION = "moderator_introduction"
    MANUAL_REVIEWER = "manual_reviewer"
    IMPORTED_ANNOTATION = "imported_annotation"
    LATER_AUDIOVISUAL_EVIDENCE = "later_audiovisual_evidence"


class IdentityHypothesisDisposition(str, Enum):
    PROPOSED = "proposed"
    SUPPORTED = "supported"
    CONTESTED = "contested"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    UNRESOLVED = "unresolved"


class BindingAction(str, Enum):
    BIND = "bind"
    REJECT_IDENTITY = "reject_identity"
    MARK_UNKNOWN = "mark_unknown"
    REVISE = "revise"
    RESTORE = "restore"
    MERGE_IDENTITY_PLACEHOLDERS = "merge_identity_placeholders"
    SPLIT_IDENTITY = "split_identity"


class DiarizationProviderIdentity(Contract):
    provider_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    display_name: str = Field(min_length=1)
    provider_version: str = Field(min_length=1)
    model_id: str | None = None
    model_version: str | None = None
    model_fingerprint: Sha256 | None = None
    runtime_fingerprint: Sha256 | None = None
    runtime_description: str | None = None
    device_description: str | None = None
    local: bool
    license_expression: str | None = None
    model_redistributed: bool = False


class DiarizationProviderCapabilities(Contract):
    format_version: Literal["1.0.0"] = PHASE3_FORMAT_VERSION
    identity: DiarizationProviderIdentity
    capabilities: tuple[DiarizationCapability, ...]
    available: bool
    minimum_speaker_count: bool = False
    maximum_speaker_count: bool = False
    confidence_scores: bool = False
    batch_processing: bool = False
    chunk_processing: bool = False
    raw_response_retention: bool = False
    cancellation_boundaries: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def declared_features_require_capabilities(
        self,
    ) -> "DiarizationProviderCapabilities":
        if len(self.capabilities) != len(set(self.capabilities)):
            raise ValueError("diarization capabilities must be unique")
        if (
            self.minimum_speaker_count or self.maximum_speaker_count
        ) and DiarizationCapability.SPEAKER_CLUSTERING not in self.capabilities:
            raise ValueError(
                "speaker-count constraints require clustering capability"
            )
        return self


class VoiceEmbeddingPolicy(Contract):
    policy_version: Literal["1.0.0"] = EMBEDDING_POLICY_VERSION
    storage_disposition: EmbeddingStorageDisposition = (
        EmbeddingStorageDisposition.PROTECTED_REFERENCE
    )
    portable_export: bool = False
    export_authorization_reference: str | None = None
    log_embedding_values: Literal[False] = False
    comparison_scope: Literal["declared_project_purpose_only"] = (
        "declared_project_purpose_only"
    )

    @model_validator(mode="after")
    def export_requires_explicit_authority(self) -> "VoiceEmbeddingPolicy":
        if self.portable_export:
            if (
                self.storage_disposition == EmbeddingStorageDisposition.OMITTED
                or not self.export_authorization_reference
            ):
                raise ValueError(
                    "embedding export requires stored evidence and explicit "
                    "authorization"
                )
        elif self.export_authorization_reference is not None:
            raise ValueError(
                "embedding export authority is invalid when export is disabled"
            )
        return self


class DiarizationPolicy(Contract):
    policy_version: Literal["1.0.0"] = DIARIZATION_POLICY_VERSION
    minimum_observation_microseconds: int = Field(
        default=500_000, gt=0
    )
    maximum_processing_interval_microseconds: int = Field(
        default=600_000_000, gt=0, le=900_000_000
    )
    minimum_speakers: int | None = Field(default=None, ge=1, le=100)
    maximum_speakers: int | None = Field(default=None, ge=1, le=100)
    overlap_policy: Literal["preserve_explicitly"] = "preserve_explicitly"
    unknown_policy: Literal["preserve_without_forcing_assignment"] = (
        "preserve_without_forcing_assignment"
    )
    chunk_ownership_policy: Literal["inherit_phase1_earliest_chunk"] = (
        "inherit_phase1_earliest_chunk"
    )
    boundary_uncertainty_microseconds: int = Field(default=50_000, ge=0)
    boundary_review_confidence_threshold: float = Field(
        default=0.50, ge=0.0, le=1.0
    )
    boundary_competition_window_microseconds: int = Field(
        default=100_000, ge=0
    )
    timeout_seconds: int = Field(default=600, ge=1, le=86_400)
    retain_raw_evidence: bool = True
    embeddings: VoiceEmbeddingPolicy = VoiceEmbeddingPolicy()

    @model_validator(mode="after")
    def speaker_bounds_are_ordered(self) -> "DiarizationPolicy":
        if (
            self.minimum_speakers is not None
            and self.maximum_speakers is not None
            and self.minimum_speakers > self.maximum_speakers
        ):
            raise ValueError("minimum speakers cannot exceed maximum speakers")
        return self


class DiarizationRequest(Contract):
    format_version: Literal["1.0.0"] = PHASE3_FORMAT_VERSION
    request_id: str = Field(pattern=r"^diareq_[a-f0-9]{32}$")
    requested_at: datetime
    corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    source_id: str = Field(pattern=r"^src_[a-f0-9]{32}$")
    selected_audio_stream_id: str = Field(pattern=r"^stream_[a-f0-9]{32}$")
    normalized_audio_sha256: Sha256
    normalized_audio_duration_microseconds: int = Field(gt=0)
    source_mapping_offset_microseconds: int
    speech_activity_run_id: str = Field(pattern=r"^sarun_[a-f0-9]{32}$")
    speech_interval_ids: tuple[str, ...] = Field(min_length=1)
    speech_intervals: tuple[SpeechActivityInterval, ...] = Field(min_length=1)
    transcript_assembly_id: str | None = Field(
        default=None, pattern=r"^txassembly_[a-f0-9]{32}$"
    )
    transcript_version_id: str | None = Field(
        default=None, pattern=r"^txversion_[a-f0-9]{32}$"
    )
    transcript_segment_ids: tuple[str, ...] = ()
    transcript_segments: tuple[TranscriptSegment, ...] = ()
    transcript_words: tuple[TranscriptWord, ...] = ()
    chunks: tuple[ProcessingChunk, ...] = Field(min_length=1)
    policy: DiarizationPolicy
    provider: DiarizationProviderIdentity
    configuration_hash: Sha256

    @model_validator(mode="after")
    def transcript_lineage_is_complete(self) -> "DiarizationRequest":
        if (self.transcript_assembly_id is None) != (
            self.transcript_version_id is None
        ):
            raise ValueError(
                "transcript assembly and version lineage must be supplied together"
            )
        if self.transcript_assembly_id is None and self.transcript_segment_ids:
            raise ValueError(
                "transcript segments require transcript assembly lineage"
            )
        if len(self.transcript_segment_ids) != len(set(self.transcript_segment_ids)):
            raise ValueError("transcript segment references must be unique")
        if tuple(item.segment_id for item in self.transcript_segments) != (
            self.transcript_segment_ids
        ):
            raise ValueError(
                "transcript segment identities and embedded evidence disagree"
            )
        known_segments = set(self.transcript_segment_ids)
        if any(item.segment_id not in known_segments for item in self.transcript_words):
            raise ValueError("transcript word references unknown segment evidence")
        if any(
            item.corpus_id != self.corpus_id
            or item.source_id != self.source_id
            or item.selected_audio_stream_id != self.selected_audio_stream_id
            for item in self.transcript_segments
        ):
            raise ValueError("transcript segment lineage differs from diarization")
        if any(item.corpus_id != self.corpus_id for item in self.transcript_words):
            raise ValueError("transcript word lineage differs from diarization")
        transcript_artifacts = (*self.transcript_segments, *self.transcript_words)
        if any(
            item.source_interval.start_microseconds
            != item.normalized_audio_interval.start_microseconds
            + self.source_mapping_offset_microseconds
            or item.normalized_audio_interval.start_microseconds
            + item.normalized_audio_interval.duration_microseconds
            > self.normalized_audio_duration_microseconds
            for item in transcript_artifacts
        ):
            raise ValueError("transcript evidence addressing differs from diarization")
        if len(self.speech_interval_ids) != len(set(self.speech_interval_ids)):
            raise ValueError("speech interval references must be unique")
        if tuple(item.interval_id for item in self.speech_intervals) != (
            self.speech_interval_ids
        ):
            raise ValueError(
                "diarization interval identities and embedded evidence disagree"
            )
        if any(item.corpus_id != self.corpus_id for item in self.speech_intervals):
            raise ValueError("diarization interval belongs to another corpus")
        return self


class SpeakerEmbedding(Contract):
    format_version: Literal["1.0.0"] = PHASE3_FORMAT_VERSION
    embedding_id: str = Field(pattern=r"^spkembed_[a-f0-9]{32}$")
    observation_id: str = Field(pattern=r"^spkobs_[a-f0-9]{32}$")
    model_space_id: str = Field(pattern=r"^[a-z][a-z0-9_.:-]+$")
    model_fingerprint: Sha256
    dimension_count: int = Field(gt=0, le=1_000_000)
    numeric_format: Literal["float32", "float64", "int8"]
    extraction_interval: MediaInterval
    storage_disposition: EmbeddingStorageDisposition
    relative_path: str | None = None
    content_sha256: Sha256 | None = None
    byte_size: int | None = Field(default=None, gt=0)
    portable_export_permitted: bool = False
    export_authorization_reference: str | None = None

    @model_validator(mode="after")
    def sensitive_storage_is_explicit(self) -> "SpeakerEmbedding":
        if self.extraction_interval.domain != TimeDomain.NORMALIZED_CORPUS:
            raise ValueError("embedding extraction uses normalized-corpus time")
        stored = (
            self.storage_disposition != EmbeddingStorageDisposition.OMITTED
        )
        if stored != all(
            item is not None
            for item in (self.relative_path, self.content_sha256, self.byte_size)
        ):
            raise ValueError(
                "stored embedding requires path, hash, and byte size"
            )
        if self.portable_export_permitted != (
            self.export_authorization_reference is not None
        ):
            raise ValueError(
                "portable embedding export requires explicit authorization"
            )
        return self


class ProviderSpeakerObservation(Contract):
    observation_id: str = Field(pattern=r"^spkobs_[a-f0-9]{32}$")
    speech_interval_ids: tuple[str, ...] = Field(min_length=1)
    transcript_segment_ids: tuple[str, ...] = ()
    source_interval: MediaInterval
    normalized_audio_interval: MediaInterval
    chunk_local_interval: MediaInterval
    processing_chunk_id: str = Field(pattern=r"^chunk_[a-f0-9]{32}$")
    provider_speaker_label: str | None = None
    canonical_owner: bool = True
    acoustic_evidence_available: bool
    usability: ObservationUsability
    usability_confidence: ConfidenceMeasure
    embedding_id: str | None = Field(
        default=None, pattern=r"^spkembed_[a-f0-9]{32}$"
    )
    provider_reference: str | None = None
    findings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def mapped_intervals_are_consistent(
        self,
    ) -> "ProviderSpeakerObservation":
        if self.source_interval.domain != TimeDomain.SOURCE_MEDIA:
            raise ValueError("speaker observation source interval is invalid")
        if (
            self.normalized_audio_interval.domain
            != TimeDomain.NORMALIZED_CORPUS
        ):
            raise ValueError("speaker observation normalized interval is invalid")
        if self.chunk_local_interval.domain != TimeDomain.CHUNK_LOCAL:
            raise ValueError("speaker observation chunk-local interval is invalid")
        durations = {
            self.source_interval.duration_microseconds,
            self.normalized_audio_interval.duration_microseconds,
            self.chunk_local_interval.duration_microseconds,
        }
        if len(durations) != 1:
            raise ValueError("speaker observation mapped durations disagree")
        if not self.acoustic_evidence_available and self.embedding_id is not None:
            raise ValueError("unavailable acoustic evidence cannot have embedding")
        return self


class ProviderSpeakerTurn(Contract):
    provider_turn_id: str = Field(min_length=1)
    observation_ids: tuple[str, ...] = Field(min_length=1)
    source_interval: MediaInterval
    normalized_audio_interval: MediaInterval
    provider_speaker_label: str | None = None
    turn_kind: SpeakerTurnKind
    boundary_confidence: ConfidenceMeasure
    assignment_confidence: ConfidenceMeasure
    overlap: bool = False
    findings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def intervals_are_mapped(self) -> "ProviderSpeakerTurn":
        if (
            self.source_interval.domain != TimeDomain.SOURCE_MEDIA
            or self.normalized_audio_interval.domain
            != TimeDomain.NORMALIZED_CORPUS
            or self.source_interval.duration_microseconds
            != self.normalized_audio_interval.duration_microseconds
        ):
            raise ValueError("provider turn intervals are not consistently mapped")
        if self.overlap != (
            self.turn_kind == SpeakerTurnKind.OVERLAPPING_SPEAKERS
        ):
            raise ValueError("provider turn overlap marker is inconsistent")
        return self


class ProviderOverlapInterval(Contract):
    provider_overlap_id: str = Field(min_length=1)
    source_interval: MediaInterval
    normalized_audio_interval: MediaInterval
    classification: OverlapClassification
    estimated_active_speaker_count: int | None = Field(default=None, ge=2)
    candidate_provider_labels: tuple[str, ...] = ()
    overlap_confidence: ConfidenceMeasure
    speaker_count_confidence: ConfidenceMeasure
    findings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def intervals_are_mapped(self) -> "ProviderOverlapInterval":
        if (
            self.source_interval.domain != TimeDomain.SOURCE_MEDIA
            or self.normalized_audio_interval.domain
            != TimeDomain.NORMALIZED_CORPUS
            or self.source_interval.duration_microseconds
            != self.normalized_audio_interval.duration_microseconds
        ):
            raise ValueError("provider overlap intervals are not consistently mapped")
        return self


class DiarizationProviderResponse(Contract):
    format_version: Literal["1.0.0"] = PHASE3_FORMAT_VERSION
    response_id: str = Field(pattern=r"^diaresponse_[a-f0-9]{32}$")
    request_id: str = Field(pattern=r"^diareq_[a-f0-9]{32}$")
    provider: DiarizationProviderIdentity
    started_at: datetime
    completed_at: datetime
    observations: tuple[ProviderSpeakerObservation, ...]
    turns: tuple[ProviderSpeakerTurn, ...]
    overlaps: tuple[ProviderOverlapInterval, ...] = ()
    embeddings: tuple[SpeakerEmbedding, ...] = ()
    raw_evidence: RawProviderEvidence
    invocations: tuple[ToolInvocationRecord, ...] = ()
    normalized_evidence_sha256: Sha256
    failure: DiarizationFailureKind | None = None
    failure_message: str | None = None
    complete: bool

    @model_validator(mode="after")
    def result_state_is_consistent(self) -> "DiarizationProviderResponse":
        if self.completed_at < self.started_at:
            raise ValueError("diarization response completes before it starts")
        if self.complete == (self.failure is not None):
            raise ValueError(
                "complete response requires no failure; failed response "
                "requires failure"
            )
        observation_ids = [item.observation_id for item in self.observations]
        if len(observation_ids) != len(set(observation_ids)):
            raise ValueError("speaker observation identifiers must be unique")
        known = set(observation_ids)
        if any(
            not set(turn.observation_ids).issubset(known)
            for turn in self.turns
        ):
            raise ValueError("provider turn references unknown observation")
        return self


class SpeakerObservation(Contract):
    format_version: Literal["1.0.0"] = PHASE3_FORMAT_VERSION
    policy_version: Literal["1.0.0"] = DIARIZATION_POLICY_VERSION
    observation_id: str = Field(pattern=r"^spkobs_[a-f0-9]{32}$")
    corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    source_id: str = Field(pattern=r"^src_[a-f0-9]{32}$")
    selected_audio_stream_id: str = Field(pattern=r"^stream_[a-f0-9]{32}$")
    speech_activity_run_id: str = Field(pattern=r"^sarun_[a-f0-9]{32}$")
    speech_interval_ids: tuple[str, ...] = Field(min_length=1)
    transcript_segment_ids: tuple[str, ...] = ()
    source_interval: MediaInterval
    normalized_audio_interval: MediaInterval
    chunk_local_interval: MediaInterval
    processing_chunk_id: str = Field(pattern=r"^chunk_[a-f0-9]{32}$")
    canonical_owner: bool = True
    acoustic_evidence_available: bool
    usability: ObservationUsability
    usability_confidence: ConfidenceMeasure
    provider: DiarizationProviderIdentity
    provider_response_id: str = Field(
        pattern=r"^diaresponse_[a-f0-9]{32}$"
    )
    embedding_id: str | None = Field(
        default=None, pattern=r"^spkembed_[a-f0-9]{32}$"
    )
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def mapped_intervals_are_consistent(self) -> "SpeakerObservation":
        if self.source_interval.domain != TimeDomain.SOURCE_MEDIA:
            raise ValueError("canonical observation source interval is invalid")
        if self.normalized_audio_interval.domain != TimeDomain.NORMALIZED_CORPUS:
            raise ValueError("canonical observation normalized interval is invalid")
        if self.chunk_local_interval.domain != TimeDomain.CHUNK_LOCAL:
            raise ValueError("canonical observation chunk-local interval is invalid")
        if len({
            self.source_interval.duration_microseconds,
            self.normalized_audio_interval.duration_microseconds,
            self.chunk_local_interval.duration_microseconds,
        }) != 1:
            raise ValueError("canonical observation mapped durations disagree")
        if not self.acoustic_evidence_available and self.embedding_id is not None:
            raise ValueError("unavailable acoustic evidence cannot have embedding")
        return self

class SpeakerChangeBoundary(Contract):
    format_version: Literal["1.0.0"] = PHASE3_FORMAT_VERSION
    boundary_id: str = Field(pattern=r"^spkboundary_[a-f0-9]{32}$")
    corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    normalized_audio_microseconds: int = Field(ge=0)
    source_microseconds: int
    uncertainty_microseconds: int = Field(ge=0)
    preceding_observation_id: str | None = Field(
        default=None, pattern=r"^spkobs_[a-f0-9]{32}$"
    )
    following_observation_id: str | None = Field(
        default=None, pattern=r"^spkobs_[a-f0-9]{32}$"
    )
    change_confidence: ConfidenceMeasure
    competing_boundary_ids: tuple[str, ...] = ()
    inside_transcript_artifact_ids: tuple[str, ...] = ()
    overlap_affected: bool = False
    review_required: bool
    provider_basis: str = Field(min_length=1)


class SpeakerTurn(Contract):
    format_version: Literal["1.0.0"] = PHASE3_FORMAT_VERSION
    turn_id: str = Field(pattern=r"^spkturn_[a-f0-9]{32}$")
    corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    source_interval: MediaInterval
    normalized_audio_interval: MediaInterval
    observation_ids: tuple[str, ...] = Field(min_length=1)
    provisional_cluster_id: str | None = Field(
        default=None, pattern=r"^spkcluster_[a-f0-9]{32}$"
    )
    turn_kind: SpeakerTurnKind
    start_boundary_id: str = Field(pattern=r"^spkboundary_[a-f0-9]{32}$")
    end_boundary_id: str = Field(pattern=r"^spkboundary_[a-f0-9]{32}$")
    boundary_confidence: ConfidenceMeasure
    assignment_confidence: ConfidenceMeasure
    transcript_segment_ids: tuple[str, ...] = ()
    transcript_word_ids: tuple[str, ...] = ()
    processing_chunk_ids: tuple[str, ...] = Field(min_length=1)
    continuation_of_turn_id: str | None = Field(
        default=None, pattern=r"^spkturn_[a-f0-9]{32}$"
    )
    provider: DiarizationProviderIdentity
    validation_findings: tuple[str, ...] = ()
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def mapped_intervals_are_consistent(self) -> "SpeakerTurn":
        if self.source_interval.domain != TimeDomain.SOURCE_MEDIA:
            raise ValueError("speaker turn source interval is invalid")
        if self.normalized_audio_interval.domain != TimeDomain.NORMALIZED_CORPUS:
            raise ValueError("speaker turn normalized interval is invalid")
        if self.source_interval.duration_microseconds != self.normalized_audio_interval.duration_microseconds:
            raise ValueError("speaker turn mapped durations disagree")
        if len(self.observation_ids) != len(set(self.observation_ids)):
            raise ValueError("speaker turn observation references must be unique")
        return self

class OverlapInterval(Contract):
    format_version: Literal["1.0.0"] = PHASE3_FORMAT_VERSION
    overlap_id: str = Field(pattern=r"^spkoverlap_[a-f0-9]{32}$")
    corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    source_interval: MediaInterval
    normalized_audio_interval: MediaInterval
    classification: OverlapClassification
    observation_ids: tuple[str, ...] = Field(min_length=1)
    candidate_cluster_ids: tuple[str, ...] = ()
    estimated_active_speaker_count: int | None = Field(default=None, ge=2)
    dominant_cluster_id: str | None = Field(
        default=None, pattern=r"^spkcluster_[a-f0-9]{32}$"
    )
    partially_attributed: bool
    overlap_confidence: ConfidenceMeasure
    speaker_count_confidence: ConfidenceMeasure
    limitations: tuple[str, ...] = ()
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def mapped_intervals_are_consistent(self) -> "OverlapInterval":
        if self.source_interval.domain != TimeDomain.SOURCE_MEDIA:
            raise ValueError("overlap source interval is invalid")
        if self.normalized_audio_interval.domain != TimeDomain.NORMALIZED_CORPUS:
            raise ValueError("overlap normalized interval is invalid")
        if self.source_interval.duration_microseconds != self.normalized_audio_interval.duration_microseconds:
            raise ValueError("overlap mapped durations disagree")
        if self.dominant_cluster_id is not None and self.dominant_cluster_id not in self.candidate_cluster_ids:
            raise ValueError("dominant overlap cluster must be a candidate")
        return self

class ClusterMembership(Contract):
    membership_id: str = Field(pattern=r"^spkmember_[a-f0-9]{32}$")
    cluster_id: str = Field(pattern=r"^spkcluster_[a-f0-9]{32}$")
    observation_id: str = Field(pattern=r"^spkobs_[a-f0-9]{32}$")
    membership_confidence: ConfidenceMeasure
    canonical: bool
    competing_cluster_ids: tuple[str, ...] = ()
    basis: str = Field(min_length=1)


class SpeakerCluster(Contract):
    format_version: Literal["1.0.0"] = PHASE3_FORMAT_VERSION
    cluster_id: str = Field(pattern=r"^spkcluster_[a-f0-9]{32}$")
    corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    membership_ids: tuple[str, ...] = Field(min_length=1)
    observation_ids: tuple[str, ...] = Field(min_length=1)
    turn_ids: tuple[str, ...] = ()
    formation_method: str = Field(min_length=1)
    configuration_hash: Sha256
    representative_embedding_id: str | None = Field(
        default=None, pattern=r"^spkembed_[a-f0-9]{32}$"
    )
    model_space_id: str | None = Field(
        default=None, pattern=r"^[a-z][a-z0-9_.:-]+$"
    )
    model_fingerprint: Sha256 | None = None
    internal_similarity_minimum: float | None = Field(
        default=None, ge=0.0, le=1.0
    )
    internal_similarity_mean: float | None = Field(
        default=None, ge=0.0, le=1.0
    )
    similarity_measurement_basis: str | None = None
    outlier_observation_ids: tuple[str, ...] = ()
    temporal_distribution: tuple[MediaInterval, ...] = ()
    source_coverage: tuple[MediaInterval, ...] = ()
    total_observation_microseconds: int = Field(default=0, ge=0)
    consistency_result_id: str | None = Field(
        default=None, pattern=r"^clusterconsistency_[a-f0-9]{32}$"
    )
    competing_cluster_ids: tuple[str, ...] = ()
    merge_proposal_ids: tuple[str, ...] = ()
    split_proposal_ids: tuple[str, ...] = ()
    status: ClusterStatus
    predecessor_cluster_ids: tuple[str, ...] = ()
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def cluster_is_acoustic_not_person(self) -> "SpeakerCluster":
        if len(self.observation_ids) != len(set(self.observation_ids)):
            raise ValueError("cluster observations must be unique")
        if self.cluster_id in self.predecessor_cluster_ids:
            raise ValueError("cluster cannot be its own predecessor")
        similarity_values = (
            self.internal_similarity_minimum,
            self.internal_similarity_mean,
        )
        if any(value is not None for value in similarity_values) != (
            self.similarity_measurement_basis is not None
        ):
            raise ValueError(
                "cluster similarity values require an explicit measurement basis"
            )
        if any(
            item.domain != TimeDomain.NORMALIZED_CORPUS
            for item in self.temporal_distribution
        ):
            raise ValueError("cluster temporal distribution has invalid domain")
        if any(
            item.domain != TimeDomain.SOURCE_MEDIA
            for item in self.source_coverage
        ):
            raise ValueError("cluster source coverage has invalid domain")
        if self.model_space_id is None and self.model_fingerprint is not None:
            raise ValueError("cluster model fingerprint requires a model space")
        return self


class IdentityScope(Contract):
    kind: IdentityScopeKind
    target_id: str = Field(min_length=1)
    explanation: str = Field(min_length=1)


class ParticipantIdentity(Contract):
    format_version: Literal["1.0.0"] = PHASE3_FORMAT_VERSION
    identity_id: str = Field(pattern=r"^identity_[a-f0-9]{32}$")
    canonical_display_label: str = Field(min_length=1)
    alternate_labels: tuple[str, ...] = ()
    identity_kind: IdentityKind
    information_source: str = Field(min_length=1)
    scope: IdentityScope
    status: IdentityStatus
    provenance_references: tuple[str, ...] = Field(min_length=1)
    created_at: datetime
    supersedes_identity_id: str | None = Field(
        default=None, pattern=r"^identity_[a-f0-9]{32}$"
    )


class IdentityHypothesis(Contract):
    format_version: Literal["1.0.0"] = PHASE3_FORMAT_VERSION
    hypothesis_id: str = Field(pattern=r"^identityhyp_[a-f0-9]{32}$")
    target_artifact_id: str = Field(min_length=1)
    proposed_identity_id: str = Field(pattern=r"^identity_[a-f0-9]{32}$")
    source: IdentityHypothesisSource
    supporting_evidence_references: tuple[str, ...] = ()
    contrary_evidence_references: tuple[str, ...] = ()
    acoustic_support: ConfidenceMeasure
    contextual_support: ConfidenceMeasure
    documentary_support: ConfidenceMeasure
    manual_assertion_support: ConfidenceMeasure
    scope: IdentityScope
    competing_hypothesis_ids: tuple[str, ...] = ()
    creation_process: str = Field(min_length=1)
    disposition: IdentityHypothesisDisposition
    created_at: datetime


class ManualIdentityBinding(Contract):
    format_version: Literal["1.0.0"] = PHASE3_FORMAT_VERSION
    policy_version: Literal["1.0.0"] = IDENTITY_POLICY_VERSION
    binding_id: str = Field(pattern=r"^identitybind_[a-f0-9]{32}$")
    target_artifact_id: str = Field(min_length=1)
    identity_id: str | None = Field(
        default=None, pattern=r"^identity_[a-f0-9]{32}$"
    )
    related_identity_ids: tuple[str, ...] = ()
    scope: IdentityScope
    action: BindingAction
    predecessor_binding_id: str | None = Field(
        default=None, pattern=r"^identitybind_[a-f0-9]{32}$"
    )
    author_id: str = Field(min_length=1)
    author_display_name: str = Field(min_length=1)
    bound_at: datetime
    rationale: str = Field(min_length=1)
    supporting_evidence_references: tuple[str, ...] = ()
    contrary_evidence_acknowledged: tuple[str, ...] = ()
    reviewer_certainty: ConfidenceMeasure
    resulting_identity_view_version_id: str = Field(
        pattern=r"^identityview_[a-f0-9]{32}$"
    )

    @model_validator(mode="after")
    def action_and_identity_are_consistent(self) -> "ManualIdentityBinding":
        requires_identity = self.action in {
            BindingAction.BIND,
            BindingAction.REJECT_IDENTITY,
            BindingAction.REVISE,
            BindingAction.RESTORE,
            BindingAction.MERGE_IDENTITY_PLACEHOLDERS,
            BindingAction.SPLIT_IDENTITY,
        }
        if requires_identity != (self.identity_id is not None):
            raise ValueError(
                "binding action and participant identity availability disagree"
            )
        if self.action in {BindingAction.REVISE, BindingAction.RESTORE} and (
            self.predecessor_binding_id is None
        ):
            raise ValueError("revision or restoration requires predecessor binding")
        structural = self.action in {
            BindingAction.MERGE_IDENTITY_PLACEHOLDERS,
            BindingAction.SPLIT_IDENTITY,
        }
        if structural != bool(self.related_identity_ids):
            raise ValueError(
                "merge or split actions require related participant identities"
            )
        if len(self.related_identity_ids) != len(set(self.related_identity_ids)):
            raise ValueError("related participant identities must be unique")
        if self.identity_id in self.related_identity_ids:
            raise ValueError(
                "primary identity cannot also be a related identity"
            )
        return self

class DiarizationRun(Contract):
    format_version: Literal["1.0.0"] = PHASE3_FORMAT_VERSION
    run_id: str = Field(pattern=r"^diarun_[a-f0-9]{32}$")
    request_id: str = Field(pattern=r"^diareq_[a-f0-9]{32}$")
    response_id: str = Field(pattern=r"^diaresponse_[a-f0-9]{32}$")
    corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    source_id: str = Field(pattern=r"^src_[a-f0-9]{32}$")
    provider: DiarizationProviderIdentity
    observations: tuple[SpeakerObservation, ...]
    boundaries: tuple[SpeakerChangeBoundary, ...]
    turns: tuple[SpeakerTurn, ...]
    overlaps: tuple[OverlapInterval, ...] = ()
    created_at: datetime
    complete: bool
    integrity_sha256: Sha256


class DiarizationReport(Contract):
    format_version: Literal["1.0.0"] = PHASE3_FORMAT_VERSION
    report_id: str = Field(pattern=r"^diareport_[a-f0-9]{32}$")
    run_id: str = Field(pattern=r"^diarun_[a-f0-9]{32}$")
    request_id: str = Field(pattern=r"^diareq_[a-f0-9]{32}$")
    corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    generated_at: datetime
    provider: DiarizationProviderIdentity
    observation_count: int = Field(ge=0)
    turn_count: int = Field(ge=0)
    boundary_count: int = Field(ge=0)
    unknown_turn_count: int = Field(ge=0)
    review_boundary_count: int = Field(ge=0)
    overlap_count: int = Field(ge=0)
    overlap_duration_microseconds: int = Field(ge=0)
    measured: tuple[str, ...]
    provider_claims: tuple[str, ...]
    validation_findings: tuple[str, ...] = ()
    unresolved_limitations: tuple[str, ...] = ()
    status: Literal["complete", "partial", "failed", "warning"]

PHASE3_CONTRACT_MODELS = (
    DiarizationProviderIdentity,
    DiarizationProviderCapabilities,
    VoiceEmbeddingPolicy,
    DiarizationPolicy,
    DiarizationRequest,
    SpeakerEmbedding,
    ProviderSpeakerObservation,
    ProviderSpeakerTurn,
    ProviderOverlapInterval,
    DiarizationProviderResponse,
    DiarizationRun,
    DiarizationReport,
    SpeakerObservation,
    SpeakerChangeBoundary,
    SpeakerTurn,
    OverlapInterval,
    ClusterMembership,
    SpeakerCluster,
    IdentityScope,
    ParticipantIdentity,
    IdentityHypothesis,
    ManualIdentityBinding,
)
