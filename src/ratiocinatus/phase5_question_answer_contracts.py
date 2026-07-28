"""Question artifacts and bounded answer-relation contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract, Sha256
from .phase2_contracts import ConfidenceMeasure
from .phase5_contracts import (
    FAMILY_TYPES,
    PHASE5_FORMAT_VERSION,
    DiscourseActFamily,
    DiscourseActType,
    DiscourseEvidenceSpan,
    DiscourseReviewStatus,
    DiscourseTargetStatus,
)

QUESTION_ANSWER_POLICY_VERSION = "1.0.0"


class QuestionRequestedForm(str, Enum):
    INFORMATION = "information"
    BOOLEAN_DECISION = "boolean_decision"
    EXPLICIT_ALTERNATIVE = "explicit_alternative"
    CLARIFICATION = "clarification"
    CONFIRMATION = "confirmation"
    CHALLENGE = "challenge"
    RHETORICAL_FORM = "rhetorical_form"
    FOLLOW_UP = "follow_up"
    PROCEDURAL = "procedural"
    EMBEDDED_OR_QUOTED = "embedded_or_quoted"
    UNRESOLVED = "unresolved"


class QuestionDomain(str, Enum):
    SUBSTANTIVE = "substantive"
    PROCEDURAL = "procedural"
    EMBEDDED_OR_QUOTED = "embedded_or_quoted"
    UNRESOLVED = "unresolved"


class AddresseeStatus(str, Enum):
    IDENTIFIED = "identified"
    MULTIPLE_CANDIDATES = "multiple_candidates"
    IMPLICIT = "implicit"
    UNRESOLVED = "unresolved"


class AnswerExplicitness(str, Enum):
    EXPLICIT = "explicit"
    PARTIAL = "partial"
    QUALIFIED = "qualified"
    INDIRECT = "indirect"
    UNRESOLVED = "unresolved"


class AnswerPolarity(str, Enum):
    AFFIRMATIVE = "affirmative"
    NEGATIVE = "negative"
    MIXED = "mixed"
    NOT_APPLICABLE = "not_applicable"
    UNRESOLVED = "unresolved"


class QuestionAnswerPolicy(Contract):
    policy_version: Literal["1.0.0"] = QUESTION_ANSWER_POLICY_VERSION
    context_window_kind: Literal["bounded_temporal_window"] = (
        "bounded_temporal_window"
    )
    maximum_previous_question_candidates: int = Field(
        default=5, ge=1, le=20
    )
    exact_relation_targets_take_precedence: Literal[True] = True
    temporal_link_is_probable_not_identified: Literal[True] = True
    unresolved_target_is_valid: Literal[True] = True
    answer_before_question_requires_explicit_target: Literal[True] = True
    adequacy_scoring: Literal[False] = False
    completeness_scoring: Literal[False] = False
    evasion_scoring: Literal[False] = False
    loadedness_inference: Literal["prohibited"] = "prohibited"
    fairness_inference: Literal["prohibited"] = "prohibited"
    answerability_inference: Literal["prohibited"] = "prohibited"


class QuestionArtifact(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    question_id: str = Field(pattern=r"^question_[a-f0-9]{32}$")
    discourse_corpus_id: str = Field(
        pattern=r"^discoursecorpus_[a-f0-9]{32}$"
    )
    source_act_id: str = Field(pattern=r"^discourseact_[a-f0-9]{32}$")
    utterance_id: str = Field(pattern=r"^utterance_[a-f0-9]{32}$")
    question_type: DiscourseActType
    question_spans: tuple[DiscourseEvidenceSpan, ...] = Field(min_length=1)
    requested_form: QuestionRequestedForm
    requested_information_or_decision: str | None = None
    explicit_alternatives: tuple[str, ...] = ()
    presupposition_markers: tuple[str, ...] = ()
    addressee_status: AddresseeStatus
    addressee_ids: tuple[str, ...] = ()
    candidate_addressee_ids: tuple[str, ...] = ()
    domain: QuestionDomain
    scope_span_ids: tuple[str, ...] = Field(min_length=1)
    confidence: ConfidenceMeasure
    review_status: DiscourseReviewStatus
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def question_is_coherent(self) -> "QuestionArtifact":
        if self.question_type not in FAMILY_TYPES[DiscourseActFamily.QUESTION]:
            raise ValueError("question artifact requires a question act type")
        span_ids = [item.span_id for item in self.question_spans]
        if len(span_ids) != len(set(span_ids)):
            raise ValueError("question spans must be unique")
        if not set(self.scope_span_ids).issubset(span_ids):
            raise ValueError("question scope references an unknown span")
        for values in (
            self.explicit_alternatives,
            self.presupposition_markers,
            self.addressee_ids,
            self.candidate_addressee_ids,
            self.scope_span_ids,
        ):
            if len(values) != len(set(values)):
                raise ValueError("question references must be unique")
        if (
            self.addressee_status == AddresseeStatus.IDENTIFIED
            and not self.addressee_ids
        ):
            raise ValueError("identified addressee status requires an id")
        if (
            self.addressee_status == AddresseeStatus.MULTIPLE_CANDIDATES
            and len(self.candidate_addressee_ids) < 2
        ):
            raise ValueError("multiple addressees require candidates")
        if self.addressee_status in {
            AddresseeStatus.IMPLICIT,
            AddresseeStatus.UNRESOLVED,
        } and (self.addressee_ids or self.candidate_addressee_ids):
            raise ValueError("implicit or unresolved addressee cannot force ids")

        return self


class AnswerRelation(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    answer_relation_id: str = Field(
        pattern=r"^answerrelation_[a-f0-9]{32}$"
    )
    discourse_corpus_id: str = Field(
        pattern=r"^discoursecorpus_[a-f0-9]{32}$"
    )
    answer_act_id: str = Field(pattern=r"^discourseact_[a-f0-9]{32}$")
    answer_utterance_id: str = Field(pattern=r"^utterance_[a-f0-9]{32}$")
    target_status: DiscourseTargetStatus
    target_question_ids: tuple[str, ...]
    alternative_question_ids: tuple[str, ...] = ()
    answer_form: DiscourseActType
    explicitness: AnswerExplicitness
    polarity: AnswerPolarity
    qualification_act_ids: tuple[str, ...] = ()
    rejects_presupposition: bool
    deferred: bool
    refused: bool
    inability: bool
    co_answer_act_ids: tuple[str, ...] = ()
    evidence_span_ids: tuple[str, ...] = Field(min_length=1)
    context_window_id: str | None = Field(
        default=None, pattern=r"^contextwindow_[a-f0-9]{32}$"
    )
    temporal_distance_microseconds: int | None = None
    confidence: ConfidenceMeasure
    review_status: DiscourseReviewStatus
    basis: tuple[str, ...] = Field(min_length=1)
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def answer_is_coherent(self) -> "AnswerRelation":
        if self.answer_form not in FAMILY_TYPES[DiscourseActFamily.ANSWER]:
            raise ValueError("answer relation requires an answer act type")
        for values in (
            self.target_question_ids,
            self.alternative_question_ids,
            self.qualification_act_ids,
            self.co_answer_act_ids,
            self.evidence_span_ids,
        ):
            if len(values) != len(set(values)):
                raise ValueError("answer relation references must be unique")
        if set(self.target_question_ids).intersection(
            self.alternative_question_ids
        ):
            raise ValueError("question cannot be target and alternative")
        if self.target_status in {
            DiscourseTargetStatus.IDENTIFIED,
            DiscourseTargetStatus.PROBABLE,
        } and not self.target_question_ids:
            raise ValueError("identified or probable answer requires a target")
        if (
            self.target_status
            == DiscourseTargetStatus.MULTIPLE_CANDIDATES
            and len(self.alternative_question_ids) < 2
        ):
            raise ValueError("ambiguous answer requires alternative questions")
        if self.target_status in {
            DiscourseTargetStatus.IMPLICIT,
            DiscourseTargetStatus.UNRESOLVED,
        } and self.target_question_ids:
            raise ValueError("unresolved answer cannot force a target")
        if self.answer_form == DiscourseActType.ANSWER_DEFERRED and not self.deferred:
            raise ValueError("deferred answer form requires deferred state")
        if self.answer_form == DiscourseActType.REFUSAL_TO_ANSWER and not self.refused:
            raise ValueError("refusal form requires refused state")
        if self.answer_form == DiscourseActType.INABILITY_TO_ANSWER and not self.inability:
            raise ValueError("inability form requires inability state")
        return self


class QuestionAnswerRun(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    question_answer_run_id: str = Field(
        pattern=r"^questionanswerrun_[a-f0-9]{32}$"
    )
    discourse_corpus_id: str = Field(
        pattern=r"^discoursecorpus_[a-f0-9]{32}$"
    )
    discourse_corpus_sha256: Sha256
    context_bundle_id: str = Field(pattern=r"^contextbundle_[a-f0-9]{32}$")
    context_bundle_sha256: Sha256
    policy: QuestionAnswerPolicy
    configuration_hash: Sha256
    questions: tuple[QuestionArtifact, ...]
    answer_relations: tuple[AnswerRelation, ...]
    unlinked_answer_act_ids: tuple[str, ...]
    created_at: datetime
    complete: bool
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def children_are_coherent(self) -> "QuestionAnswerRun":
        question_ids = [item.question_id for item in self.questions]
        relation_ids = [
            item.answer_relation_id for item in self.answer_relations
        ]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("question ids must be unique")
        if len(relation_ids) != len(set(relation_ids)):
            raise ValueError("answer relation ids must be unique")
        known_questions = set(question_ids)
        if any(
            not (
                set(item.target_question_ids)
                | set(item.alternative_question_ids)
            ).issubset(known_questions)
            for item in self.answer_relations
        ):
            raise ValueError("answer relation references unknown question")
        answer_ids = [item.answer_act_id for item in self.answer_relations]
        if len(answer_ids) != len(set(answer_ids)):
            raise ValueError("one answer act requires one relation artifact")

        if len(self.unlinked_answer_act_ids) != len(
            set(self.unlinked_answer_act_ids)
        ):
            raise ValueError("unlinked answer ids must be unique")
        return self


class QuestionAnswerReport(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    report_id: str = Field(pattern=r"^questionanswerreport_[a-f0-9]{32}$")
    question_answer_run_id: str = Field(
        pattern=r"^questionanswerrun_[a-f0-9]{32}$"
    )
    generated_at: datetime
    question_count: int = Field(ge=0)
    procedural_question_count: int = Field(ge=0)
    substantive_question_count: int = Field(ge=0)
    answer_relation_count: int = Field(ge=0)
    identified_answer_count: int = Field(ge=0)
    probable_answer_count: int = Field(ge=0)
    ambiguous_answer_count: int = Field(ge=0)
    unresolved_answer_count: int = Field(ge=0)
    deferred_answer_count: int = Field(ge=0)
    refused_answer_count: int = Field(ge=0)
    inability_answer_count: int = Field(ge=0)
    premise_rejection_count: int = Field(ge=0)
    multi_question_answer_count: int = Field(ge=0)
    jointly_answered_question_count: int = Field(ge=0)
    limitations: tuple[str, ...] = Field(min_length=1)
    status: Literal["complete", "warning", "failed"]
    integrity_sha256: Sha256


PHASE5_QUESTION_ANSWER_CONTRACT_MODELS = (
    QuestionAnswerPolicy,
    QuestionArtifact,
    AnswerRelation,
    QuestionAnswerRun,
    QuestionAnswerReport,
)
