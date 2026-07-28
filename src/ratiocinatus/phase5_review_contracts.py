"""Append-only discourse review and Phase 4 correction-propagation contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract, Sha256
from .phase5_contracts import (
    PHASE5_FORMAT_VERSION,
    DiscourseCorrectionPropagationPolicy,
    DiscourseReviewStatus,
)

PHASE5_REVIEW_POLICY_VERSION = "1.0.0"


class DiscourseReviewActionKind(str, Enum):
    APPROVE_ACT = "approve_act"
    REJECT_ACT = "reject_act"
    ADD_ACT = "add_act"
    CHANGE_ACT_TYPE = "change_act_type"
    CHANGE_EVIDENCE_SPAN = "change_evidence_span"
    ADD_ALTERNATIVE = "add_alternative"
    REMOVE_ALTERNATIVE = "remove_alternative"
    CHANGE_RELATION_TARGET = "change_relation_target"
    MARK_TARGET_UNRESOLVED = "mark_target_unresolved"
    LINK_ANSWER = "link_answer_to_question"
    UNLINK_ANSWER = "unlink_answer"
    LINK_OBJECTION_OR_REBUTTAL = "link_objection_or_rebuttal"
    REVISE_CONCESSION_SCOPE = "revise_concession_scope"
    REVISE_QUALIFICATION_SCOPE = "revise_qualification_scope"
    REVISE_DEFINITION = "revise_definition"
    REVISE_EXAMPLE_TARGET = "revise_example_target"
    REVISE_PROCEDURAL_ACT = "revise_procedural_act"
    DEFER_DECISION = "defer_decision"


class DiscourseReviewQueueKind(str, Enum):
    LOW_CONFIDENCE_ACT = "low_confidence_act"
    INCOMPATIBLE_CANDIDATES = "multiple_incompatible_candidates"
    ACT_WITHOUT_EVIDENCE = "act_without_evidence_span"
    RELATION_WITHOUT_TARGET = "relation_without_target"
    UNRESOLVED_ANSWER = "answer_with_unresolved_question"
    MULTIPLE_ANSWER_CANDIDATES = "question_with_multiple_answer_candidates"
    AMBIGUOUS_OBJECTION_TARGET = "objection_with_ambiguous_target"
    MISSING_REBUTTAL_TARGET = "rebuttal_with_missing_target"
    UNCLEAR_CONCESSION_SCOPE = "concession_with_unclear_scope"
    UNCLEAR_QUALIFICATION_TARGET = "qualification_with_unclear_modifier_target"
    DEFINITION_MISSING_TERM = "definition_with_missing_term"
    UNRESOLVED_EXAMPLE = "example_with_unresolved_generalization"
    QUOTATION_INCONSISTENCY = "quotation_inconsistency"
    PROCEDURAL_STATE_CONFLICT = "procedural_state_conflict"
    CORRECTION_AFFECTED_ACT = "correction_affected_act"
    INTEGRITY_WARNING = "integrity_warning"


class Phase5ChangeKind(str, Enum):
    ADDED_UTTERANCE = "added_utterance"
    REMOVED_UTTERANCE = "removed_utterance"
    TEXT = "utterance_text"
    BOUNDARY = "utterance_boundary"
    SPEAKER_ATTRIBUTION = "speaker_attribution"
    DISPLAY_LABEL_ONLY = "display_label_only"
    QUOTATION_STRUCTURE = "quotation_structure"
    INTERRUPTION_OR_CONTINUATION = "interruption_or_continuation"


class DiscourseReviewStateEntry(Contract):
    key: str = Field(min_length=1)
    value: str


class DiscourseReviewAction(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    review_id: str = Field(pattern=r"^discoursereview_[a-f0-9]{32}$")
    predecessor_review_id: str | None = Field(
        default=None, pattern=r"^discoursereview_[a-f0-9]{32}$"
    )
    action: DiscourseReviewActionKind
    target_artifact_ids: tuple[str, ...] = Field(min_length=1)
    prior_state: tuple[DiscourseReviewStateEntry, ...] = Field(min_length=1)
    proposed_state: tuple[DiscourseReviewStateEntry, ...] = Field(min_length=1)
    author: str = Field(min_length=1)
    reviewed_at: datetime
    rationale: str = Field(min_length=1)
    evidence_references: tuple[str, ...] = Field(min_length=1)
    certainty: float = Field(ge=0.0, le=1.0)
    resulting_discourse_view_version: str = Field(
        pattern=r"^discourseview_[a-f0-9]{32}$"
    )
    resulting_review_status: DiscourseReviewStatus
    phase4_utterance_corpus_modified: Literal[False] = False
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def references_are_unique(self) -> "DiscourseReviewAction":
        for values in (self.target_artifact_ids, self.evidence_references):
            if len(values) != len(set(values)):
                raise ValueError("review references must be unique")
        if (self.action == DiscourseReviewActionKind.DEFER_DECISION) != (
            self.resulting_review_status == DiscourseReviewStatus.DEFERRED
        ):
            raise ValueError("defer action and review status must agree")
        return self


class DiscourseReviewLedger(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    ledger_id: str = Field(pattern=r"^discourseledger_[a-f0-9]{32}$")
    predecessor_ledger_id: str | None = Field(
        default=None, pattern=r"^discourseledger_[a-f0-9]{32}$"
    )
    discourse_corpus_id: str = Field(pattern=r"^discoursecorpus_[a-f0-9]{32}$")
    phase4_utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    ledger_version: int = Field(ge=0)
    actions: tuple[DiscourseReviewAction, ...]
    current_discourse_view_version: str = Field(
        pattern=r"^discourseview_[a-f0-9]{32}$"
    )
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def history_is_append_only(self) -> "DiscourseReviewLedger":
        ids = [item.review_id for item in self.actions]
        if len(ids) != len(set(ids)) or self.ledger_version != len(ids):
            raise ValueError("review ledger inventory is invalid")
        for index, item in enumerate(self.actions):
            expected = None if index == 0 else ids[index - 1]
            if item.predecessor_review_id != expected:
                raise ValueError("review predecessor chain is invalid")
        if self.actions and self.current_discourse_view_version != (
            self.actions[-1].resulting_discourse_view_version
        ):
            raise ValueError("current discourse view must match latest review")
        return self


class DiscourseReviewQueueItem(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    item_id: str = Field(pattern=r"^discoursereviewqueue_[a-f0-9]{32}$")
    kind: DiscourseReviewQueueKind
    target_artifact_ids: tuple[str, ...] = Field(min_length=1)
    utterance_ids: tuple[str, ...] = Field(min_length=1)
    source_interval_references: tuple[str, ...] = Field(min_length=1)
    utterance_text: str
    speaker_attribution: str = Field(min_length=1)
    local_context_references: tuple[str, ...] = Field(min_length=1)
    proposed_act_ids: tuple[str, ...] = ()
    evidence_span_ids: tuple[str, ...] = ()
    relation_target_ids: tuple[str, ...] = ()
    alternatives: tuple[str, ...] = ()
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    proposed_actions: tuple[DiscourseReviewActionKind, ...] = Field(min_length=1)
    evidence_references: tuple[str, ...] = Field(min_length=1)
    integrity_sha256: Sha256


class DiscourseReviewQueue(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    queue_id: str = Field(pattern=r"^discoursequeue_[a-f0-9]{32}$")
    discourse_corpus_id: str = Field(pattern=r"^discoursecorpus_[a-f0-9]{32}$")
    ledger_id: str = Field(pattern=r"^discourseledger_[a-f0-9]{32}$")
    generated_at: datetime
    items: tuple[DiscourseReviewQueueItem, ...]
    queue_kind_counts: tuple[str, ...]
    unresolved_item_count: int = Field(ge=0)
    integrity_sha256: Sha256


class UtteranceDiscourseImpact(Contract):
    impact_id: str = Field(pattern=r"^discourseimpact_[a-f0-9]{32}$")
    predecessor_utterance_ids: tuple[str, ...]
    successor_utterance_ids: tuple[str, ...]
    change_kinds: tuple[Phase5ChangeKind, ...] = Field(min_length=1)
    invalidated_observation_ids: tuple[str, ...]
    invalidated_candidate_set_ids: tuple[str, ...]
    invalidated_act_ids: tuple[str, ...]
    preserved_act_ids: tuple[str, ...]
    rebuild_relation_target_act_ids: tuple[str, ...]
    identity_specific_context_used: bool
    explanation: str = Field(min_length=1)
    integrity_sha256: Sha256


class DiscoursePropagationRun(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    propagation_run_id: str = Field(
        pattern=r"^discoursepropagation_[a-f0-9]{32}$"
    )
    predecessor_phase4_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    successor_phase4_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    predecessor_discourse_corpus_id: str = Field(
        pattern=r"^discoursecorpus_[a-f0-9]{32}$"
    )
    policy: DiscourseCorrectionPropagationPolicy
    configuration_hash: Sha256
    impacts: tuple[UtteranceDiscourseImpact, ...]
    invalidated_observation_ids: tuple[str, ...]
    invalidated_candidate_set_ids: tuple[str, ...]
    invalidated_act_ids: tuple[str, ...]
    preserved_act_ids: tuple[str, ...]
    rebuild_relation_target_act_ids: tuple[str, ...]
    rebuild_procedural_state: bool
    rebuild_review_queues: bool
    created_at: datetime
    complete: bool
    integrity_sha256: Sha256


class DiscoursePropagationReport(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    report_id: str = Field(pattern=r"^discoursepropagationreport_[a-f0-9]{32}$")
    propagation_run_id: str = Field(
        pattern=r"^discoursepropagation_[a-f0-9]{32}$"
    )
    generated_at: datetime
    changed_utterance_count: int = Field(ge=0)
    invalidated_observation_count: int = Field(ge=0)
    invalidated_act_count: int = Field(ge=0)
    preserved_act_count: int = Field(ge=0)
    relation_rebuild_count: int = Field(ge=0)
    display_label_only_change_count: int = Field(ge=0)
    status: Literal["complete", "warning", "failed"]
    limitations: tuple[str, ...] = Field(min_length=1)
    integrity_sha256: Sha256


PHASE5_REVIEW_CONTRACT_MODELS = (
    DiscourseReviewStateEntry,
    DiscourseReviewAction,
    DiscourseReviewLedger,
    DiscourseReviewQueueItem,
    DiscourseReviewQueue,
    UtteranceDiscourseImpact,
    DiscoursePropagationRun,
    DiscoursePropagationReport,
)
