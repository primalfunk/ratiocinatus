"""Controlled Phase 5 discourse-evaluation contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract, Sha256
from .phase5_contracts import (
    PHASE5_FORMAT_VERSION,
    DiscourseActFamily,
    DiscourseActType,
)

PHASE5_EVALUATION_POLICY_VERSION = "1.0.0"


class Phase5EvaluationMetricKind(str, Enum):
    ACT_FAMILY_PRECISION = "act_family_precision"
    ACT_FAMILY_RECALL = "act_family_recall"
    ACT_FAMILY_F1 = "act_family_f1"
    ACT_TYPE_PRECISION = "act_type_precision"
    ACT_TYPE_RECALL = "act_type_recall"
    ACT_TYPE_F1 = "act_type_f1"
    MULTI_LABEL_EXACT_MATCH = "multi_label_exact_match"
    MULTI_LABEL_PARTIAL_MATCH = "multi_label_partial_match"
    EVIDENCE_SPAN_PRECISION = "evidence_span_precision"
    EVIDENCE_SPAN_RECALL = "evidence_span_recall"
    EVIDENCE_SPAN_OVERLAP = "evidence_span_overlap"
    RELATION_TARGET_ACCURACY = "relation_target_accuracy"
    QUESTION_TYPE_ACCURACY = "question_type_accuracy"
    ANSWER_LINK_ACCURACY = "answer_link_accuracy"
    OBJECTION_TARGET_ACCURACY = "objection_target_accuracy"
    REBUTTAL_TARGET_ACCURACY = "rebuttal_target_accuracy"
    CONCESSION_SCOPE_ACCURACY = "concession_scope_accuracy"
    QUALIFICATION_SCOPE_ACCURACY = "qualification_scope_accuracy"
    DEFINITION_SPAN_ACCURACY = "definition_span_accuracy"
    EXAMPLE_TARGET_ACCURACY = "example_target_accuracy"
    QUOTATION_USE_ACCURACY = "quotation_use_accuracy"
    PROCEDURAL_ACT_ACCURACY = "procedural_act_accuracy"
    ALTERNATIVE_CANDIDATE_RECALL = "alternative_candidate_recall"
    CONFIDENCE_RELIABILITY = "confidence_reliability"
    UNKNOWN_STATE_APPROPRIATENESS = "unknown_state_appropriateness"
    CORRECTION_PROPAGATION_COMPLETENESS = (
        "correction_propagation_completeness"
    )
    UNAFFECTED_ARTIFACT_STABILITY = "unaffected_artifact_stability"
    HUMAN_REVIEW_IMPACT = "human_review_impact"


class Phase5EvaluationStratum(str, Enum):
    CLEAN = "clean"
    MULTI_LABEL = "multi_label"
    UNRESOLVED = "unresolved"
    QUESTION_ANSWER = "question_answer"
    ARGUMENT_RELATION = "argument_relation"
    LEXICAL = "lexical"
    QUOTATION = "quotation"
    PROCEDURAL = "procedural"
    CORRECTION_AFFECTED = "correction_affected"
    HUMAN_REVIEWED = "human_reviewed"
    OVERLAP = "overlap"
    INCOMPLETE_UTTERANCE = "incomplete_utterance"


class Phase5EvaluationMetricStatus(str, Enum):
    MEASURED = "measured"
    NOT_APPLICABLE = "not_applicable"


class Phase5EvaluationPolicy(Contract):
    policy_version: Literal["1.0.0"] = PHASE5_EVALUATION_POLICY_VERSION
    minimum_span_iou: float = Field(default=0.5, gt=0.0, le=1.0)
    compatible_multi_label_treatment: Literal["set_membership"] = (
        "set_membership"
    )
    nested_act_treatment: Literal["score_independently"] = (
        "score_independently"
    )
    unresolved_target_treatment: Literal["valid_reference_outcome"] = (
        "valid_reference_outcome"
    )
    rhetorical_question_treatment: Literal["score_declared_type"] = (
        "score_declared_type"
    )
    incomplete_utterance_treatment: Literal["score_when_source_grounded"] = (
        "score_when_source_grounded"
    )
    overlap_treatment: Literal["score_each_owned_utterance"] = (
        "score_each_owned_utterance"
    )
    human_review_treatment: Literal["separate_machine_and_reviewed_views"] = (
        "separate_machine_and_reviewed_views"
    )
    confidence_bin_count: int = Field(default=10, ge=2, le=100)
    synthetic_mechanics_not_performance_claim: Literal[True] = True


class Phase5ReferenceSpan(Contract):
    reference_span_id: str = Field(pattern=r"^refdiscoursespan_[a-f0-9]{32}$")
    utterance_id: str = Field(pattern=r"^utterance_[a-f0-9]{32}$")
    start_text_offset: int = Field(ge=0)
    end_text_offset: int = Field(gt=0)
    exact_displayed_text: str = Field(min_length=1)

    @model_validator(mode="after")
    def offsets_are_ordered(self) -> "Phase5ReferenceSpan":
        if self.end_text_offset <= self.start_text_offset:
            raise ValueError("reference span offsets must be ordered")
        return self


class Phase5ReferenceAct(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    reference_act_id: str = Field(pattern=r"^refdiscourseact_[a-f0-9]{32}$")
    utterance_id: str = Field(pattern=r"^utterance_[a-f0-9]{32}$")
    act_family: DiscourseActFamily
    act_type: DiscourseActType
    evidence_spans: tuple[Phase5ReferenceSpan, ...] = Field(min_length=1)
    target_ids: tuple[str, ...] = ()
    alternative_act_types: tuple[DiscourseActType, ...] = ()
    unresolved_expected: bool = False
    strata: tuple[Phase5EvaluationStratum, ...] = Field(min_length=1)
    evidence_references: tuple[str, ...] = Field(min_length=1)
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def references_are_unique(self) -> "Phase5ReferenceAct":
        for values in (
            self.target_ids,
            self.alternative_act_types,
            self.strata,
            self.evidence_references,
        ):
            if len(values) != len(set(values)):
                raise ValueError("reference act values must be unique")
        return self


class Phase5ControlledReference(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    reference_id: str = Field(pattern=r"^phase5reference_[a-f0-9]{32}$")
    phase4_utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    acts: tuple[Phase5ReferenceAct, ...] = Field(min_length=1)
    prepared_by: str = Field(min_length=1)
    prepared_at: datetime
    preparation_method: str = Field(min_length=1)
    independent_of_system_output: bool
    evidence_class: Literal["controlled_reference", "synthetic_mechanics"]
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def act_ids_are_unique(self) -> "Phase5ControlledReference":
        ids = [item.reference_act_id for item in self.acts]
        if len(ids) != len(set(ids)):
            raise ValueError("reference act identifiers must be unique")
        return self


class Phase5EvaluationMetric(Contract):
    kind: Phase5EvaluationMetricKind
    status: Phase5EvaluationMetricStatus
    numerator: float = Field(ge=0)
    denominator: int = Field(ge=0)
    value: float | None = Field(default=None, ge=0.0, le=1.0)
    basis: str = Field(min_length=1)
    evidence_references: tuple[str, ...]

    @model_validator(mode="after")
    def value_is_coherent(self) -> "Phase5EvaluationMetric":
        if self.status == Phase5EvaluationMetricStatus.MEASURED:
            if self.denominator == 0 or self.value is None:
                raise ValueError("measured metric requires a value")
        elif self.denominator != 0 or self.value is not None:
            raise ValueError("not-applicable metric cannot claim a value")
        return self


class Phase5StratumEvaluation(Contract):
    stratum: Phase5EvaluationStratum
    reference_act_count: int = Field(ge=0)
    system_act_count: int = Field(ge=0)
    exact_type_match_count: int = Field(ge=0)


class Phase5DiscourseEvaluation(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    evaluation_id: str = Field(pattern=r"^phase5evaluation_[a-f0-9]{32}$")
    discourse_corpus_id: str = Field(pattern=r"^discoursecorpus_[a-f0-9]{32}$")
    controlled_reference_id: str = Field(
        pattern=r"^phase5reference_[a-f0-9]{32}$"
    )
    policy: Phase5EvaluationPolicy
    metrics: tuple[Phase5EvaluationMetric, ...] = Field(min_length=28)
    strata: tuple[Phase5StratumEvaluation, ...]
    generated_at: datetime
    evidence_class: Literal["measured_evaluation", "synthetic_mechanics"]
    limitations: tuple[str, ...] = Field(min_length=1)
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def inventory_is_complete(self) -> "Phase5DiscourseEvaluation":
        kinds = [item.kind for item in self.metrics]
        if set(kinds) != set(Phase5EvaluationMetricKind):
            raise ValueError("evaluation requires every declared metric")
        if len(kinds) != len(set(kinds)):
            raise ValueError("evaluation metrics must be unique")
        strata = [item.stratum for item in self.strata]
        if len(strata) != len(set(strata)):
            raise ValueError("evaluation strata must be unique")
        return self


class Phase5EvaluationReport(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    report_id: str = Field(pattern=r"^phase5evaluationreport_[a-f0-9]{32}$")
    evaluation_id: str = Field(pattern=r"^phase5evaluation_[a-f0-9]{32}$")
    generated_at: datetime
    reference_act_count: int = Field(ge=0)
    system_act_count: int = Field(ge=0)
    measured_metric_count: int = Field(ge=0)
    not_applicable_metric_count: int = Field(ge=0)
    status: Literal["complete", "warning", "failed"]
    integrity_sha256: Sha256


PHASE5_EVALUATION_CONTRACT_MODELS = (
    Phase5EvaluationPolicy,
    Phase5ReferenceSpan,
    Phase5ReferenceAct,
    Phase5ControlledReference,
    Phase5EvaluationMetric,
    Phase5StratumEvaluation,
    Phase5DiscourseEvaluation,
    Phase5EvaluationReport,
)
