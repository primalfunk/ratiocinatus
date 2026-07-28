"""Append-only transcript correction and corrected-view contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .addressing_contracts import MediaInterval, TimeDomain
from .contracts import Contract, Sha256
from .transcript_contracts import (
    TranscriptArtifactDigest,
    TranscriptAssemblyStatus,
    TranscriptVersion,
)

CORRECTION_FORMAT_VERSION = "1.0.0"
CORRECTION_POLICY_VERSION = "1.0.0"


class CorrectionType(str, Enum):
    REPLACEMENT = "replacement"
    INSERTION = "insertion"
    DELETION = "deletion"
    SPLIT = "split"
    MERGE = "merge"
    BOUNDARY_ADJUSTMENT = "boundary_adjustment"
    LANGUAGE_CORRECTION = "language_correction"
    NORMALIZATION_ONLY = "normalization_only"
    UNCERTAINTY_ANNOTATION = "uncertainty_annotation"
    RESTORE_EARLIER_CANDIDATE = "restore_earlier_candidate"


class CorrectionActorKind(str, Enum):
    HUMAN = "human"
    AUTOMATED_PROCESS = "automated_process"


class TranscriptViewKind(str, Enum):
    ORIGINAL_MACHINE = "original_machine"
    CURRENT_CORRECTED = "current_corrected"


class TranscriptSegmentState(Contract):
    artifact_id: str = Field(
        pattern=r"^(txsegment|txviewsegment)_[a-f0-9]{32}$"
    )
    source_interval: MediaInterval
    normalized_audio_interval: MediaInterval
    text: str = Field(min_length=1)
    normalized_text: str = Field(min_length=1)
    language_claim: str | None = None
    origin_segment_ids: tuple[str, ...] = ()
    retained_word_ids: tuple[str, ...] = ()
    applied_correction_ids: tuple[str, ...] = ()
    uncertainty_annotations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def mapping_is_consistent(self) -> "TranscriptSegmentState":
        if self.source_interval.domain != TimeDomain.SOURCE_MEDIA:
            raise ValueError("segment state source interval has wrong domain")
        if self.normalized_audio_interval.domain != TimeDomain.NORMALIZED_CORPUS:
            raise ValueError("segment state normalized interval has wrong domain")
        if (
            self.source_interval.duration_microseconds
            != self.normalized_audio_interval.duration_microseconds
        ):
            raise ValueError("segment state mapped durations disagree")
        return self


class TranscriptSegmentProposal(Contract):
    source_interval: MediaInterval
    normalized_audio_interval: MediaInterval
    text: str = Field(min_length=1)
    normalized_text: str = Field(min_length=1)
    language_claim: str | None = None
    restored_candidate_id: str | None = None
    uncertainty_annotation: str | None = None

    @model_validator(mode="after")
    def mapping_is_consistent(self) -> "TranscriptSegmentProposal":
        if self.source_interval.domain != TimeDomain.SOURCE_MEDIA:
            raise ValueError("segment proposal source interval has wrong domain")
        if self.normalized_audio_interval.domain != TimeDomain.NORMALIZED_CORPUS:
            raise ValueError("segment proposal normalized interval has wrong domain")
        if (
            self.source_interval.duration_microseconds
            != self.normalized_audio_interval.duration_microseconds
        ):
            raise ValueError("segment proposal mapped durations disagree")
        return self


class CorrectionActor(Contract):
    kind: CorrectionActorKind
    actor_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    process_version: str | None = None

    @model_validator(mode="after")
    def process_version_matches_actor(self) -> "CorrectionActor":
        if (
            self.kind == CorrectionActorKind.AUTOMATED_PROCESS
        ) != (self.process_version is not None):
            raise ValueError(
                "automated correction actor requires a process version; "
                "human actor must not claim one"
            )
        return self


class CorrectionPolicy(Contract):
    policy_version: Literal["1.0.0"] = CORRECTION_POLICY_VERSION
    allow_human: bool = True
    allow_automated_process: bool = True
    require_evidence_or_review_reference: bool = True
    conflict_policy: Literal["reject_overlapping_targets"] = (
        "reject_overlapping_targets"
    )
    maximum_corrections_per_version: int = Field(default=1000, ge=1, le=100_000)


class TranscriptCorrectionDraft(Contract):
    format_version: Literal["1.0.0"] = CORRECTION_FORMAT_VERSION
    target_version_id: str = Field(pattern=r"^txversion_[a-f0-9]{32}$")
    correction_type: CorrectionType
    target_artifact_ids: tuple[str, ...] = Field(min_length=1)
    prior_values: tuple[TranscriptSegmentState, ...]
    proposed_values: tuple[TranscriptSegmentProposal, ...]
    affected_source_interval: MediaInterval
    actor: CorrectionActor
    corrected_at: datetime
    reason: str = Field(min_length=1)
    evidence_or_review_references: tuple[str, ...] = ()

    @model_validator(mode="after")
    def basic_shape_is_consistent(self) -> "TranscriptCorrectionDraft":
        if self.affected_source_interval.domain != TimeDomain.SOURCE_MEDIA:
            raise ValueError("correction affected interval must use source time")
        if len(self.target_artifact_ids) != len(set(self.target_artifact_ids)):
            raise ValueError("correction target identifiers must be unique")
        expected = tuple(item.artifact_id for item in self.prior_values)
        if self.correction_type != CorrectionType.INSERTION and (
            expected != self.target_artifact_ids
        ):
            raise ValueError(
                "correction prior values must exactly identify all targets"
            )
        if self.correction_type == CorrectionType.INSERTION and self.prior_values:
            raise ValueError("insertion must not claim a prior segment value")
        return self


class TranscriptCorrectionBatch(Contract):
    format_version: Literal["1.0.0"] = CORRECTION_FORMAT_VERSION
    batch_id: str = Field(pattern=r"^correctionbatch_[a-f0-9]{32}$")
    target_version_id: str = Field(pattern=r"^txversion_[a-f0-9]{32}$")
    policy: CorrectionPolicy = CorrectionPolicy()
    corrections: tuple[TranscriptCorrectionDraft, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def target_versions_agree(self) -> "TranscriptCorrectionBatch":
        if len(self.corrections) > self.policy.maximum_corrections_per_version:
            raise ValueError("correction batch exceeds policy maximum")
        if any(
            item.target_version_id != self.target_version_id
            for item in self.corrections
        ):
            raise ValueError("all correction drafts must target the batch version")
        return self


class TranscriptCorrection(Contract):
    format_version: Literal["1.0.0"] = CORRECTION_FORMAT_VERSION
    correction_id: str = Field(pattern=r"^correction_[a-f0-9]{32}$")
    target_version_id: str = Field(pattern=r"^txversion_[a-f0-9]{32}$")
    resulting_version_id: str = Field(pattern=r"^txversion_[a-f0-9]{32}$")
    application_status: Literal["applied"] = "applied"
    correction_type: CorrectionType
    target_artifact_ids: tuple[str, ...] = Field(min_length=1)
    prior_values: tuple[TranscriptSegmentState, ...]
    proposed_values: tuple[TranscriptSegmentProposal, ...]
    resulting_segment_ids: tuple[str, ...]
    affected_source_interval: MediaInterval
    actor: CorrectionActor
    corrected_at: datetime
    reason: str = Field(min_length=1)
    evidence_or_review_references: tuple[str, ...]
    integrity_sha256: Sha256


class TranscriptView(Contract):
    format_version: Literal["1.0.0"] = CORRECTION_FORMAT_VERSION
    view_id: str = Field(pattern=r"^txview_[a-f0-9]{32}$")
    version_id: str = Field(pattern=r"^txversion_[a-f0-9]{32}$")
    view_kind: TranscriptViewKind
    segments: tuple[TranscriptSegmentState, ...]
    retained_word_ids: tuple[str, ...]
    rendered_text: str
    created_at: datetime
    integrity_sha256: Sha256


class TranscriptDifferenceEntry(Contract):
    correction_id: str = Field(pattern=r"^correction_[a-f0-9]{32}$")
    correction_type: CorrectionType
    prior_values: tuple[TranscriptSegmentState, ...]
    proposed_values: tuple[TranscriptSegmentState, ...]
    affected_source_interval: MediaInterval
    actor: CorrectionActor
    reason: str = Field(min_length=1)


class TranscriptDifferenceReport(Contract):
    format_version: Literal["1.0.0"] = CORRECTION_FORMAT_VERSION
    difference_id: str = Field(pattern=r"^txdiff_[a-f0-9]{32}$")
    base_version_id: str = Field(pattern=r"^txversion_[a-f0-9]{32}$")
    resulting_version_id: str = Field(pattern=r"^txversion_[a-f0-9]{32}$")
    entries: tuple[TranscriptDifferenceEntry, ...]
    generated_at: datetime
    integrity_sha256: Sha256


class CorrectionHistory(Contract):
    format_version: Literal["1.0.0"] = CORRECTION_FORMAT_VERSION
    history_id: str = Field(pattern=r"^txhistory_[a-f0-9]{32}$")
    base_version_id: str = Field(pattern=r"^txversion_[a-f0-9]{32}$")
    current_version_id: str = Field(pattern=r"^txversion_[a-f0-9]{32}$")
    version_chain: tuple[str, ...] = Field(min_length=2)
    corrections: tuple[TranscriptArtifactDigest, ...]
    generated_at: datetime
    integrity_sha256: Sha256


class TranscriptRevision(Contract):
    format_version: Literal["1.0.0"] = CORRECTION_FORMAT_VERSION
    revision_id: str = Field(pattern=r"^txrevision_[a-f0-9]{32}$")
    base_assembly_id: str = Field(pattern=r"^txassembly_[a-f0-9]{32}$")
    base_version_id: str = Field(pattern=r"^txversion_[a-f0-9]{32}$")
    version: TranscriptVersion
    corrections: tuple[TranscriptCorrection, ...]
    original_machine_view: TranscriptView
    current_corrected_view: TranscriptView
    difference_report: TranscriptDifferenceReport
    correction_history: CorrectionHistory
    status: TranscriptAssemblyStatus
    validation_findings: tuple[str, ...] = ()
    created_at: datetime
    integrity_sha256: Sha256


class TranscriptRevisionReport(Contract):
    format_version: Literal["1.0.0"] = CORRECTION_FORMAT_VERSION
    report_id: str = Field(pattern=r"^txrevisionreport_[a-f0-9]{32}$")
    revision_id: str = Field(pattern=r"^txrevision_[a-f0-9]{32}$")
    base_version_id: str = Field(pattern=r"^txversion_[a-f0-9]{32}$")
    resulting_version_id: str = Field(pattern=r"^txversion_[a-f0-9]{32}$")
    generated_at: datetime
    correction_count: int = Field(ge=1)
    human_correction_count: int = Field(ge=0)
    automated_correction_count: int = Field(ge=0)
    affected_duration_microseconds: int = Field(ge=0)
    correction_types: tuple[tuple[CorrectionType, int], ...]
    original_segment_count: int = Field(ge=0)
    corrected_segment_count: int = Field(ge=0)
    status: TranscriptAssemblyStatus
    validation_findings: tuple[str, ...] = ()


CORRECTION_CONTRACT_MODELS = (
    TranscriptSegmentState,
    TranscriptSegmentProposal,
    CorrectionActor,
    CorrectionPolicy,
    TranscriptCorrectionDraft,
    TranscriptCorrectionBatch,
    TranscriptCorrection,
    TranscriptView,
    TranscriptDifferenceEntry,
    TranscriptDifferenceReport,
    CorrectionHistory,
    TranscriptRevision,
    TranscriptRevisionReport,
)
