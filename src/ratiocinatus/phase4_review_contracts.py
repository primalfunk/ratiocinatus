"""Phase 4 correction-propagation and append-only review contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .addressing_contracts import MediaInterval, TimeDomain
from .contracts import Contract, Sha256
from .phase4_contracts import PHASE4_FORMAT_VERSION, UtteranceReviewStatus

PHASE4_PROPAGATION_POLICY_VERSION = "1.0.0"
PHASE4_REVIEW_POLICY_VERSION = "1.0.0"


class Phase4ChangeKind(str, Enum):
    TEXT_ONLY = "text_only"
    TIMING = "timing"
    SPEAKER_ATTRIBUTION = "speaker_attribution"
    SEGMENTATION = "segmentation"
    DISPLAY_LABEL = "display_label"
    SOURCE_LINEAGE = "source_lineage"


class Phase4InvalidationKind(str, Enum):
    UTTERANCE = "utterance"
    STRUCTURAL_ANALYSIS = "structural_analysis"
    TEMPORAL_RELATIONS = "temporal_relations"
    TURN_REPAIR = "turn_repair"
    QUOTATION = "quotation"
    TRANSCRIPT_VIEWS = "transcript_views"
    CONTEXT_WINDOWS = "context_windows"


class UtteranceMappingDisposition(str, Enum):
    UNCHANGED_EQUIVALENT = "unchanged_equivalent"
    REBUILT_ONE_TO_ONE = "rebuilt_one_to_one"
    SPLIT = "split"
    MERGED = "merged"
    REMOVED = "removed"
    ADDED = "added"
    UNRESOLVED = "unresolved"


class ReviewActionKind(str, Enum):
    APPROVE_UTTERANCE = "approve_utterance"
    SPLIT_UTTERANCE = "split_utterance"
    MERGE_UTTERANCES = "merge_utterances"
    MOVE_BOUNDARY = "move_boundary"
    CHANGE_COMPLETENESS = "change_completeness_classification"
    MARK_INTERRUPTION = "mark_interruption"
    REMOVE_INTERRUPTION = "remove_incorrect_interruption"
    LINK_CONTINUATION = "link_continuation"
    UNLINK_CONTINUATION = "unlink_continuation"
    MARK_QUOTATION = "mark_quotation"
    REVISE_QUOTATION_SPAN = "revise_quotation_span"
    CHANGE_QUOTATION_TYPE = "change_quotation_type"
    FLAG_UNCERTAIN_TEXT = "flag_uncertain_text"
    FLAG_UNCERTAIN_SPEAKER = "flag_uncertain_speaker_attribution"
    DEFER_DECISION = "defer_decision"


class ReviewActionDisposition(str, Enum):
    APPLIED = "applied"
    DEFERRED = "deferred"


class ReviewerCertainty(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ReviewQueueKind(str, Enum):
    LOW_CONFIDENCE_SEGMENTATION = "low_confidence_segmentation"
    UNCERTAIN_SPEAKER_BOUNDARY = "uncertain_speaker_boundary"
    WORD_CROSSING_SPEAKER_BOUNDARY = "word_crossing_speaker_boundary"
    LONG_UTTERANCE = "long_utterance"
    VERY_SHORT_FRAGMENT = "very_short_fragment"
    UNRESOLVED_INTERRUPTION = "unresolved_interruption"
    UNRESOLVED_CONTINUATION = "unresolved_continuation"
    UNCERTAIN_OVERLAP_ATTRIBUTION = "uncertain_overlap_attribution"
    LIKELY_TURN_REPAIR = "likely_turn_repair"
    PROBABLE_SELF_REPAIR = "probable_self_repair"
    UNCERTAIN_QUOTATION = "uncertain_quotation"
    CONFLICTING_SPEAKER_ATTRIBUTION = "conflicting_speaker_attribution"
    CORRECTION_AFFECTED = "correction_affected_utterance"
    INTEGRITY_WARNING = "integrity_warning"


class Phase4PropagationPolicy(Contract):
    policy_version: Literal["1.0.0"] = PHASE4_PROPAGATION_POLICY_VERSION
    temporal_mapping_tolerance_microseconds: int = Field(
        default=250_000, ge=0
    )
    preserve_unaffected_predecessor_evidence: Literal[True] = True
    display_label_change_requires_resegmentation: Literal[False] = False
    boundary_crossing_requires_segmentation_review: Literal[True] = True
    rebuild_transcript_views: Literal[True] = True
    rebuild_context_windows: Literal[True] = True
    stale_successor_artifacts: Literal["prohibited"] = "prohibited"


class UtterancePropagationImpact(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    impact_id: str = Field(pattern=r"^propagationimpact_[a-f0-9]{32}$")
    predecessor_utterance_ids: tuple[str, ...]
    successor_utterance_ids: tuple[str, ...]
    disposition: UtteranceMappingDisposition
    change_kinds: tuple[Phase4ChangeKind, ...]
    invalidated_artifact_kinds: tuple[Phase4InvalidationKind, ...]
    affected: bool
    segmentation_review_required: bool
    predecessor_identifier_preserved: bool
    predecessor_evidence_preserved: Literal[True] = True
    explanation: str = Field(min_length=1)
    evidence_references: tuple[str, ...] = Field(min_length=1)
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def mapping_is_coherent(self) -> "UtterancePropagationImpact":
        for values in (
            self.predecessor_utterance_ids,
            self.successor_utterance_ids,
            self.change_kinds,
            self.invalidated_artifact_kinds,
        ):
            if len(values) != len(set(values)):
                raise ValueError("propagation impact values must be unique")
        if self.affected != bool(self.change_kinds):
            raise ValueError("affected state must match detected changes")
        if self.predecessor_identifier_preserved and (
            self.predecessor_utterance_ids != self.successor_utterance_ids
        ):
            raise ValueError("preserved identifier must be unchanged")
        if self.disposition == UtteranceMappingDisposition.ADDED and (
            self.predecessor_utterance_ids or not self.successor_utterance_ids
        ):
            raise ValueError("added impact has only successor utterances")
        if self.disposition == UtteranceMappingDisposition.REMOVED and (
            not self.predecessor_utterance_ids or self.successor_utterance_ids
        ):
            raise ValueError("removed impact has only predecessor utterances")
        return self


class Phase4PropagationRun(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    propagation_run_id: str = Field(
        pattern=r"^phase4propagation_[a-f0-9]{32}$"
    )
    predecessor_utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    successor_utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    predecessor_transcript_view_bundle_id: str = Field(
        pattern=r"^utteranceviewbundle_[a-f0-9]{32}$"
    )
    successor_transcript_view_bundle_id: str = Field(
        pattern=r"^utteranceviewbundle_[a-f0-9]{32}$"
    )
    predecessor_context_bundle_id: str = Field(
        pattern=r"^contextbundle_[a-f0-9]{32}$"
    )
    successor_context_bundle_id: str = Field(
        pattern=r"^contextbundle_[a-f0-9]{32}$"
    )
    policy: Phase4PropagationPolicy
    configuration_hash: Sha256
    impacts: tuple[UtterancePropagationImpact, ...]
    changed_predecessor_utterance_ids: tuple[str, ...]
    unaffected_predecessor_utterance_ids: tuple[str, ...]
    rebuilt_transcript_views: Literal[True] = True
    rebuilt_context_windows: Literal[True] = True
    predecessor_artifacts_preserved: Literal[True] = True
    created_at: datetime
    complete: bool
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def impact_partition_is_valid(self) -> "Phase4PropagationRun":
        if set(self.changed_predecessor_utterance_ids).intersection(
            self.unaffected_predecessor_utterance_ids
        ):
            raise ValueError("changed and unaffected utterances must be disjoint")
        mapped = {
            utterance_id
            for item in self.impacts
            for utterance_id in item.predecessor_utterance_ids
        }
        if mapped != set(self.changed_predecessor_utterance_ids).union(
            self.unaffected_predecessor_utterance_ids
        ):
            raise ValueError("propagation impacts must partition predecessors")
        return self


class Phase4PropagationReport(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    report_id: str = Field(pattern=r"^phase4propagationreport_[a-f0-9]{32}$")
    propagation_run_id: str = Field(
        pattern=r"^phase4propagation_[a-f0-9]{32}$"
    )
    created_at: datetime
    predecessor_utterance_count: int = Field(ge=0)
    successor_utterance_count: int = Field(ge=0)
    changed_utterance_count: int = Field(ge=0)
    unaffected_utterance_count: int = Field(ge=0)
    added_utterance_count: int = Field(ge=0)
    removed_utterance_count: int = Field(ge=0)
    segmentation_review_count: int = Field(ge=0)
    change_kind_counts: tuple[str, ...]
    status: Literal["complete", "warning", "failed"]
    limitations: tuple[str, ...] = ()
    integrity_sha256: Sha256


class ReviewStateEntry(Contract):
    key: str = Field(min_length=1)
    value: str


class UtteranceReviewAction(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    review_action_id: str = Field(pattern=r"^utterancereview_[a-f0-9]{32}$")
    predecessor_review_action_id: str | None = Field(
        default=None, pattern=r"^utterancereview_[a-f0-9]{32}$"
    )
    action: ReviewActionKind
    disposition: ReviewActionDisposition
    target_artifact_ids: tuple[str, ...] = Field(min_length=1)
    target_utterance_ids: tuple[str, ...] = Field(min_length=1)
    prior_state: tuple[ReviewStateEntry, ...] = Field(min_length=1)
    proposed_state: tuple[ReviewStateEntry, ...] = Field(min_length=1)
    author: str = Field(min_length=1)
    reviewed_at: datetime
    rationale: str = Field(min_length=1)
    evidence_references: tuple[str, ...] = Field(min_length=1)
    reviewer_certainty: ReviewerCertainty
    resulting_utterance_view_version: str = Field(
        pattern=r"^utterancereviewview_[a-f0-9]{32}$"
    )
    machine_proposal_preserved: Literal[True] = True
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def review_shape_is_valid(self) -> "UtteranceReviewAction":
        for values in (
            self.target_artifact_ids,
            self.target_utterance_ids,
            self.evidence_references,
        ):
            if len(values) != len(set(values)):
                raise ValueError("review references must be unique")
        if self.action == ReviewActionKind.MERGE_UTTERANCES and len(
            self.target_utterance_ids
        ) < 2:
            raise ValueError("merge review requires at least two utterances")
        if self.action != ReviewActionKind.MERGE_UTTERANCES and len(
            self.target_utterance_ids
        ) != 1:
            raise ValueError("review action requires exactly one utterance")
        if (
            self.action == ReviewActionKind.DEFER_DECISION
        ) != (self.disposition == ReviewActionDisposition.DEFERRED):
            raise ValueError("defer action and disposition must agree")
        return self


class UtteranceReviewLedger(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    review_ledger_id: str = Field(pattern=r"^reviewledger_[a-f0-9]{32}$")
    predecessor_review_ledger_id: str | None = Field(
        default=None, pattern=r"^reviewledger_[a-f0-9]{32}$"
    )
    utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    transcript_view_bundle_id: str = Field(
        pattern=r"^utteranceviewbundle_[a-f0-9]{32}$"
    )
    ledger_version: int = Field(ge=0)
    actions: tuple[UtteranceReviewAction, ...]
    current_utterance_view_version: str = Field(
        pattern=r"^utterancereviewview_[a-f0-9]{32}$"
    )
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def history_is_append_only(self) -> "UtteranceReviewLedger":
        identifiers = [item.review_action_id for item in self.actions]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("review action identifiers must be unique")
        for index, item in enumerate(self.actions):
            expected = None if index == 0 else identifiers[index - 1]
            if item.predecessor_review_action_id != expected:
                raise ValueError("review action predecessor chain is invalid")
        if self.ledger_version != len(self.actions):
            raise ValueError("review ledger version must equal action count")
        if self.actions and self.current_utterance_view_version != (
            self.actions[-1].resulting_utterance_view_version
        ):
            raise ValueError("review view version must match latest action")
        return self


class ReviewQueueItem(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    review_queue_item_id: str = Field(pattern=r"^reviewqueue_[a-f0-9]{32}$")
    kind: ReviewQueueKind
    utterance_ids: tuple[str, ...] = Field(min_length=1)
    source_intervals: tuple[MediaInterval, ...] = Field(min_length=1)
    media_reference: str = Field(min_length=1)
    extraction_command: str = Field(min_length=1)
    local_context_window_ids: tuple[str, ...] = Field(min_length=1)
    speaker_evidence_references: tuple[str, ...] = Field(min_length=1)
    proposed_actions: tuple[ReviewActionKind, ...] = Field(min_length=1)
    competing_alternatives: tuple[str, ...] = Field(min_length=1)
    current_review_status: UtteranceReviewStatus
    evidence_references: tuple[str, ...] = Field(min_length=1)
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def queue_addressing_is_valid(self) -> "ReviewQueueItem":
        if any(
            item.domain != TimeDomain.SOURCE_MEDIA
            for item in self.source_intervals
        ):
            raise ValueError("review queue intervals must use source time")
        return self


class ReviewQueueReport(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    report_id: str = Field(pattern=r"^reviewqueuereport_[a-f0-9]{32}$")
    utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    review_ledger_id: str = Field(pattern=r"^reviewledger_[a-f0-9]{32}$")
    generated_at: datetime
    items: tuple[ReviewQueueItem, ...]
    queue_kind_counts: tuple[str, ...]
    unresolved_item_count: int = Field(ge=0)
    integrity_sha256: Sha256


PHASE4_REVIEW_CONTRACT_MODELS = (
    Phase4PropagationPolicy,
    UtterancePropagationImpact,
    Phase4PropagationRun,
    Phase4PropagationReport,
    ReviewStateEntry,
    UtteranceReviewAction,
    UtteranceReviewLedger,
    ReviewQueueItem,
    ReviewQueueReport,
)
