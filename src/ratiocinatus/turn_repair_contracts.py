"""Phase 4 bounded, non-destructive turn-repair contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .addressing_contracts import MediaInterval, TimeDomain
from .contracts import Contract, Sha256
from .phase2_contracts import ConfidenceMeasure
from .phase4_contracts import PHASE4_FORMAT_VERSION, UtteranceReviewStatus

TURN_REPAIR_POLICY_VERSION = "1.0.0"


class TurnRepairConflictKind(str, Enum):
    BOUNDARY_INSIDE_TRANSCRIPT_WORD = "boundary_inside_transcript_word"
    BOUNDARY_INSIDE_SPEAKER_TURN = "boundary_inside_speaker_turn"
    TRANSCRIPT_SEGMENT_SPANS_SPEAKERS = "transcript_segment_spans_speakers"
    WORD_CROSSES_SPEAKER_BOUNDARY = "word_crosses_speaker_boundary"
    UNATTRIBUTED_TRANSCRIPT_WORDS = "unattributed_transcript_words"
    MIXED_SPEAKER_INTERVAL = "mixed_speaker_interval"
    TEMPORAL_MISMATCH = "temporal_mismatch"
    UNRESOLVED = "unresolved"


class TurnRepairActionKind(str, Enum):
    SPLIT_TURN = "split_turn"
    MERGE_ADJACENT_TURNS = "merge_adjacent_turns"
    MOVE_BOUNDARY = "move_boundary"
    REASSIGN_TRANSCRIPT_WORDS = "reassign_transcript_words"
    DETACH_TRANSCRIPT_WORDS = "detach_incorrectly_associated_words"
    ASSIGN_UNATTRIBUTED_WORDS = "assign_previously_unattributed_words"
    PRESERVE_MIXED_SPEAKER_INTERVAL = "preserve_mixed_speaker_interval"
    MARK_UNRESOLVED = "mark_unresolved"


class TurnRepairCreationProcess(str, Enum):
    AUTOMATED_RULE = "automated_rule"
    MANUAL_REVIEW = "manual_review"


class TurnRepairProposalDisposition(str, Enum):
    PROPOSED = "proposed"
    DEFERRED = "deferred"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    UNRESOLVED = "unresolved"


class TurnRepairDecisionDisposition(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DEFERRED = "deferred"


class TurnRepairPolicy(Contract):
    policy_version: Literal["1.0.0"] = TURN_REPAIR_POLICY_VERSION
    boundary_word_edge_tolerance_microseconds: int = Field(
        default=150_000, ge=0
    )
    split_turn_minimum_side_microseconds: int = Field(
        default=100_000, ge=1
    )
    automatic_word_reassignment: Literal["prohibited"] = "prohibited"
    automatic_source_mutation: Literal["prohibited"] = "prohibited"
    mixed_speaker_preservation: Literal["required"] = "required"
    accepted_repairs_require_successor: Literal["required"] = "required"


class TurnRepairConflict(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    conflict_id: str = Field(pattern=r"^turnconflict_[a-f0-9]{32}$")
    utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    kind: TurnRepairConflictKind
    source_interval: MediaInterval
    normalized_audio_interval: MediaInterval
    affected_artifact_ids: tuple[str, ...] = Field(min_length=1)
    transcript_word_ids: tuple[str, ...] = ()
    speaker_turn_ids: tuple[str, ...] = ()
    speaker_boundary_ids: tuple[str, ...] = ()
    utterance_ids: tuple[str, ...] = ()
    evidence_basis: tuple[str, ...] = Field(min_length=1)
    contrary_evidence: tuple[str, ...] = Field(min_length=1)
    review_status: UtteranceReviewStatus
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def addressing_and_references_are_valid(self) -> "TurnRepairConflict":
        if (
            self.source_interval.domain != TimeDomain.SOURCE_MEDIA
            or self.normalized_audio_interval.domain
            != TimeDomain.NORMALIZED_CORPUS
            or self.source_interval.duration_microseconds
            != self.normalized_audio_interval.duration_microseconds
        ):
            raise ValueError("turn conflict intervals are not mapped")
        for values in (
            self.affected_artifact_ids,
            self.transcript_word_ids,
            self.speaker_turn_ids,
            self.speaker_boundary_ids,
            self.utterance_ids,
        ):
            if len(values) != len(set(values)):
                raise ValueError("turn conflict references must be unique")
        return self


class TurnRepairProposedChange(Contract):
    action: TurnRepairActionKind
    source_turn_ids: tuple[str, ...] = ()
    source_boundary_ids: tuple[str, ...] = ()
    source_utterance_ids: tuple[str, ...] = ()
    source_transcript_word_ids: tuple[str, ...] = ()
    proposed_boundary_normalized_microseconds: int | None = Field(
        default=None, ge=0
    )
    proposed_speaker_target_id: str | None = None
    preserves_all_source_intervals: bool = True
    description: str = Field(min_length=1)

    @model_validator(mode="after")
    def action_has_required_inputs(self) -> "TurnRepairProposedChange":
        if (
            self.action == TurnRepairActionKind.MOVE_BOUNDARY
            and (
                len(self.source_boundary_ids) != 1
                or self.proposed_boundary_normalized_microseconds is None
            )
        ):
            raise ValueError("boundary move requires one boundary and position")
        if (
            self.action == TurnRepairActionKind.SPLIT_TURN
            and (
                len(self.source_turn_ids) != 1
                or self.proposed_boundary_normalized_microseconds is None
            )
        ):
            raise ValueError("turn split requires one turn and split position")
        if (
            self.action == TurnRepairActionKind.MERGE_ADJACENT_TURNS
            and len(self.source_turn_ids) != 2
        ):
            raise ValueError("turn merge requires two source turns")
        if self.action in {
            TurnRepairActionKind.REASSIGN_TRANSCRIPT_WORDS,
            TurnRepairActionKind.DETACH_TRANSCRIPT_WORDS,
            TurnRepairActionKind.ASSIGN_UNATTRIBUTED_WORDS,
        } and not self.source_transcript_word_ids:
            raise ValueError("word repair requires transcript words")
        if not self.preserves_all_source_intervals:
            raise ValueError("turn repair cannot discard source intervals")
        return self


class TurnRepairProposal(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    proposal_id: str = Field(pattern=r"^turnproposal_[a-f0-9]{32}$")
    utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    conflict_ids: tuple[str, ...] = Field(min_length=1)
    proposed_change: TurnRepairProposedChange
    affected_artifact_ids: tuple[str, ...] = Field(min_length=1)
    evidence_basis: tuple[str, ...] = Field(min_length=1)
    contrary_evidence: tuple[str, ...] = Field(min_length=1)
    confidence: ConfidenceMeasure
    creation_process: TurnRepairCreationProcess
    disposition: TurnRepairProposalDisposition
    review_status: UtteranceReviewStatus
    policy_version: Literal["1.0.0"] = TURN_REPAIR_POLICY_VERSION
    created_at: datetime
    integrity_sha256: Sha256


class TurnRepairDecision(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    decision_id: str = Field(pattern=r"^turndecision_[a-f0-9]{32}$")
    proposal_id: str = Field(pattern=r"^turnproposal_[a-f0-9]{32}$")
    disposition: TurnRepairDecisionDisposition
    author: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    evidence_references: tuple[str, ...] = Field(min_length=1)
    decided_at: datetime
    successor_id: str | None = Field(
        default=None, pattern=r"^turnsuccessor_[a-f0-9]{32}$"
    )
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def accepted_decision_has_successor(self) -> "TurnRepairDecision":
        if (self.disposition == TurnRepairDecisionDisposition.ACCEPTED) != (
            self.successor_id is not None
        ):
            raise ValueError("accepted turn repair requires one successor")
        return self


class TurnRepairSuccessor(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    successor_id: str = Field(pattern=r"^turnsuccessor_[a-f0-9]{32}$")
    proposal_id: str = Field(pattern=r"^turnproposal_[a-f0-9]{32}$")
    decision_id: str = Field(pattern=r"^turndecision_[a-f0-9]{32}$")
    utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    source_artifact_ids: tuple[str, ...] = Field(min_length=1)
    projected_change: TurnRepairProposedChange
    predecessor_artifacts_preserved: Literal[True] = True
    applied_at: datetime
    integrity_sha256: Sha256


class TurnRepairRun(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    repair_run_id: str = Field(pattern=r"^turnrepairrun_[a-f0-9]{32}$")
    predecessor_repair_run_id: str | None = Field(
        default=None, pattern=r"^turnrepairrun_[a-f0-9]{32}$"
    )
    utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    utterance_run_id: str = Field(pattern=r"^utterancerun_[a-f0-9]{32}$")
    phase2_transcript_assembly_id: str = Field(
        pattern=r"^txassembly_[a-f0-9]{32}$"
    )
    phase3_diarization_run_id: str = Field(
        pattern=r"^diarun_[a-f0-9]{32}$"
    )
    phase3_speaker_transcript_view_id: str = Field(
        pattern=r"^speakertranscript_[a-f0-9]{32}$"
    )
    policy: TurnRepairPolicy
    configuration_hash: Sha256
    conflicts: tuple[TurnRepairConflict, ...]
    proposals: tuple[TurnRepairProposal, ...]
    decisions: tuple[TurnRepairDecision, ...] = ()
    successors: tuple[TurnRepairSuccessor, ...] = ()
    detected_at: datetime
    updated_at: datetime
    complete: bool
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def child_lineage_is_valid(self) -> "TurnRepairRun":
        collections = (
            tuple(item.conflict_id for item in self.conflicts),
            tuple(item.proposal_id for item in self.proposals),
            tuple(item.decision_id for item in self.decisions),
            tuple(item.successor_id for item in self.successors),
        )
        if any(len(values) != len(set(values)) for values in collections):
            raise ValueError("turn-repair child identifiers must be unique")
        conflict_ids = set(collections[0])
        proposal_ids = set(collections[1])
        decision_ids = set(collections[2])
        successor_ids = set(collections[3])
        if any(
            not set(item.conflict_ids).issubset(conflict_ids)
            for item in self.proposals
        ):
            raise ValueError("proposal references unknown conflict")
        if any(item.proposal_id not in proposal_ids for item in self.decisions):
            raise ValueError("decision references unknown proposal")
        if any(
            item.proposal_id not in proposal_ids
            or item.decision_id not in decision_ids
            for item in self.successors
        ):
            raise ValueError("successor references unknown proposal or decision")
        if any(
            item.successor_id is not None
            and item.successor_id not in successor_ids
            for item in self.decisions
        ):
            raise ValueError("decision references unknown successor")
        if self.updated_at < self.detected_at:
            raise ValueError("turn-repair run updates before detection")
        return self


class TurnRepairReport(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    report_id: str = Field(pattern=r"^turnrepairreport_[a-f0-9]{32}$")
    repair_run_id: str = Field(pattern=r"^turnrepairrun_[a-f0-9]{32}$")
    utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    generated_at: datetime
    conflict_count: int = Field(ge=0)
    proposal_count: int = Field(ge=0)
    accepted_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    deferred_count: int = Field(ge=0)
    unresolved_count: int = Field(ge=0)
    successor_count: int = Field(ge=0)
    review_required_count: int = Field(ge=0)
    limitations: tuple[str, ...] = ()
    status: Literal["complete", "warning", "failed"]
    integrity_sha256: Sha256


TURN_REPAIR_CONTRACT_MODELS = (
    TurnRepairPolicy,
    TurnRepairConflict,
    TurnRepairProposedChange,
    TurnRepairProposal,
    TurnRepairDecision,
    TurnRepairSuccessor,
    TurnRepairRun,
    TurnRepairReport,
)
