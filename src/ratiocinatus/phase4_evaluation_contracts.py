"""Controlled Phase 4 utterance-evaluation contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .addressing_contracts import MediaInterval, TimeDomain
from .contracts import Contract, Sha256
from .phase4_contracts import (
    PHASE4_FORMAT_VERSION,
    UtteranceAttributionStatus,
    UtteranceCompletenessClassification,
)
from .quotation_contracts import SpokenQuotationType

PHASE4_EVALUATION_POLICY_VERSION = "1.0.0"


class Phase4EvaluationMetricKind(str, Enum):
    BOUNDARY_PRECISION = "utterance_boundary_precision"
    BOUNDARY_RECALL = "utterance_boundary_recall"
    BOUNDARY_TIMING_ERROR = "boundary_timing_error_microseconds"
    SEGMENTATION_SIMILARITY = "utterance_segmentation_similarity"
    SPEAKER_ATTRIBUTION_ACCURACY = "speaker_attribution_accuracy"
    UNKNOWN_ATTRIBUTION_APPROPRIATENESS = (
        "unknown_attribution_appropriateness"
    )
    INTERRUPTION_PRECISION = "interruption_detection_precision"
    INTERRUPTION_RECALL = "interruption_detection_recall"
    CONTINUATION_LINK_ACCURACY = "continuation_link_accuracy"
    INCOMPLETE_CLASSIFICATION_ACCURACY = (
        "incomplete_utterance_classification_accuracy"
    )
    OVERLAP_PRESERVATION_ACCURACY = "overlap_preservation_accuracy"
    SELF_REPAIR_DETECTION_ACCURACY = "self_repair_detection_accuracy"
    QUOTATION_SPAN_ACCURACY = "quotation_span_accuracy"
    QUOTATION_TYPE_ACCURACY = "quotation_type_accuracy"
    QUOTED_SPEAKER_ATTRIBUTION_ACCURACY = (
        "quoted_speaker_attribution_accuracy"
    )
    CORRECTION_PROPAGATION_COMPLETENESS = (
        "correction_propagation_completeness"
    )
    UNAFFECTED_ARTIFACT_STABILITY = "unaffected_artifact_stability"
    CONTEXT_WINDOW_REPRODUCIBILITY = "context_window_reproducibility"
    CONTEXT_TRUNCATION_CORRECTNESS = "context_truncation_correctness"
    MANUAL_REVIEW_IMPACT = "manual_review_impact"


class Phase4EvaluationStratum(str, Enum):
    CLEAN_SPEECH = "clean_speech"
    RAPID_EXCHANGE = "rapid_exchange"
    INTERRUPTION = "interruption"
    OVERLAP = "overlap"
    INCOMPLETE_SPEECH = "incomplete_speech"
    CORRECTION_AFFECTED = "correction_affected_speech"
    QUOTATION = "quotation"
    EMBEDDED_SPEECH = "embedded_speech"
    CHUNK_BOUNDARY = "chunk_boundary"


class EvaluationMetricStatus(str, Enum):
    MEASURED = "measured"
    NOT_APPLICABLE = "not_applicable"


class Phase4EvaluationPolicy(Contract):
    policy_version: Literal["1.0.0"] = PHASE4_EVALUATION_POLICY_VERSION
    boundary_collar_microseconds: int = Field(default=250_000, ge=0)
    punctuation_treatment: Literal["preserve_reference"] = "preserve_reference"
    backchannel_treatment: Literal["independent_when_referenced"] = (
        "independent_when_referenced"
    )
    filler_treatment: Literal["retain_audible"] = "retain_audible"
    overlap_treatment: Literal["preserve_parallel_utterances"] = (
        "preserve_parallel_utterances"
    )
    resumed_utterance_treatment: Literal["score_declared_links"] = (
        "score_declared_links"
    )
    unknown_speaker_treatment: Literal["valid_reference_outcome"] = (
        "valid_reference_outcome"
    )
    nonlexical_treatment: Literal["score_when_source_addressed"] = (
        "score_when_source_addressed"
    )
    require_independent_source_addressing: Literal[True] = True
    synthetic_mechanics_not_performance_claim: Literal[True] = True


class Phase4ReferenceUtterance(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    reference_utterance_id: str = Field(
        pattern=r"^refutterance_[a-f0-9]{32}$"
    )
    source_intervals: tuple[MediaInterval, ...] = Field(min_length=1)
    transcript_word_ids: tuple[str, ...]
    reference_text: str
    attribution_status: UtteranceAttributionStatus
    speaker_target_id: str | None = None
    completeness: UtteranceCompletenessClassification
    overlap_expected: bool = False
    self_repair_expected: bool = False
    quotation_type: SpokenQuotationType | None = None
    quoted_text: str | None = None
    quoted_speaker_target_id: str | None = None
    correction_affected: bool = False
    review_action_expected: bool = False
    strata: tuple[Phase4EvaluationStratum, ...] = Field(min_length=1)
    evidence_references: tuple[str, ...] = Field(min_length=1)
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def reference_is_source_addressed(self) -> "Phase4ReferenceUtterance":
        if any(
            item.domain != TimeDomain.SOURCE_MEDIA
            for item in self.source_intervals
        ):
            raise ValueError("reference utterance must use source-media time")
        unresolved = self.attribution_status in {
            UtteranceAttributionStatus.UNKNOWN,
            UtteranceAttributionStatus.CONFLICTING,
        }
        if unresolved != (self.speaker_target_id is None):
            raise ValueError(
                "reference attribution target disagrees with status"
            )
        if (self.quotation_type is None) != (self.quoted_text is None):
            raise ValueError("quotation type and quoted text must agree")
        if len(self.transcript_word_ids) != len(
            set(self.transcript_word_ids)
        ):
            raise ValueError("reference word identifiers must be unique")
        if len(self.strata) != len(set(self.strata)):
            raise ValueError("reference strata must be unique")
        return self


class Phase4ReferenceRelation(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    reference_relation_id: str = Field(
        pattern=r"^refutterancerelation_[a-f0-9]{32}$"
    )
    kind: Literal["interruption", "continuation"]
    predecessor_reference_utterance_id: str = Field(
        pattern=r"^refutterance_[a-f0-9]{32}$"
    )
    successor_reference_utterance_id: str = Field(
        pattern=r"^refutterance_[a-f0-9]{32}$"
    )
    evidence_references: tuple[str, ...] = Field(min_length=1)
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def relation_endpoints_are_distinct(self) -> "Phase4ReferenceRelation":
        if (
            self.predecessor_reference_utterance_id
            == self.successor_reference_utterance_id
        ):
            raise ValueError("reference relation requires distinct endpoints")
        return self


class Phase4ControlledReference(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    reference_id: str = Field(pattern=r"^phase4reference_[a-f0-9]{32}$")
    source_id: str = Field(pattern=r"^src_[a-f0-9]{32}$")
    utterances: tuple[Phase4ReferenceUtterance, ...] = Field(min_length=1)
    relations: tuple[Phase4ReferenceRelation, ...] = ()
    prepared_by: str = Field(min_length=1)
    prepared_at: datetime
    preparation_method: str = Field(min_length=1)
    independent_of_system_output: bool
    evidence_class: Literal[
        "controlled_reference", "synthetic_mechanics"
    ]
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def identifiers_and_relations_are_valid(self) -> "Phase4ControlledReference":
        identifiers = [item.reference_utterance_id for item in self.utterances]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("reference utterance identifiers must be unique")
        known = set(identifiers)
        if any(
            {
                item.predecessor_reference_utterance_id,
                item.successor_reference_utterance_id,
            }
            - known
            for item in self.relations
        ):
            raise ValueError("reference relation uses an unknown utterance")
        return self


class Phase4EvaluationMetric(Contract):
    kind: Phase4EvaluationMetricKind
    status: EvaluationMetricStatus
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    value: float | None = Field(default=None, ge=0)
    unit: str = Field(min_length=1)
    basis: str = Field(min_length=1)
    evidence_references: tuple[str, ...]

    @model_validator(mode="after")
    def metric_value_is_coherent(self) -> "Phase4EvaluationMetric":
        if self.status == EvaluationMetricStatus.MEASURED:
            if self.denominator == 0 or self.value is None:
                raise ValueError("measured metric requires denominator and value")
        elif self.denominator != 0 or self.value is not None:
            raise ValueError("not-applicable metric cannot claim a value")
        return self


class Phase4StratumEvaluation(Contract):
    stratum: Phase4EvaluationStratum
    reference_utterance_count: int = Field(ge=0)
    matched_utterance_count: int = Field(ge=0)
    metrics: tuple[Phase4EvaluationMetric, ...]


class Phase4UtteranceEvaluation(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    evaluation_id: str = Field(pattern=r"^phase4evaluation_[a-f0-9]{32}$")
    utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    controlled_reference_id: str = Field(
        pattern=r"^phase4reference_[a-f0-9]{32}$"
    )
    policy: Phase4EvaluationPolicy
    metrics: tuple[Phase4EvaluationMetric, ...] = Field(min_length=20)
    strata: tuple[Phase4StratumEvaluation, ...]
    matched_reference_count: int = Field(ge=0)
    unmatched_reference_count: int = Field(ge=0)
    unmatched_system_count: int = Field(ge=0)
    generated_at: datetime
    evidence_class: Literal[
        "measured_evaluation", "synthetic_mechanics"
    ]
    limitations: tuple[str, ...]
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def metric_inventory_is_complete(self) -> "Phase4UtteranceEvaluation":
        kinds = [item.kind for item in self.metrics]
        if set(kinds) != set(Phase4EvaluationMetricKind):
            raise ValueError("evaluation requires every declared metric")
        if len(kinds) != len(set(kinds)):
            raise ValueError("evaluation metric kinds must be unique")
        stratum_ids = [item.stratum for item in self.strata]
        if len(stratum_ids) != len(set(stratum_ids)):
            raise ValueError("evaluation strata must be unique")
        return self


class Phase4EvaluationReport(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    report_id: str = Field(pattern=r"^phase4evaluationreport_[a-f0-9]{32}$")
    evaluation_id: str = Field(pattern=r"^phase4evaluation_[a-f0-9]{32}$")
    generated_at: datetime
    measured_metric_count: int = Field(ge=0)
    not_applicable_metric_count: int = Field(ge=0)
    reference_utterance_count: int = Field(ge=0)
    matched_reference_count: int = Field(ge=0)
    status: Literal["complete", "warning", "failed"]
    integrity_sha256: Sha256


PHASE4_EVALUATION_CONTRACT_MODELS = (
    Phase4EvaluationPolicy,
    Phase4ReferenceUtterance,
    Phase4ReferenceRelation,
    Phase4ControlledReference,
    Phase4EvaluationMetric,
    Phase4StratumEvaluation,
    Phase4UtteranceEvaluation,
    Phase4EvaluationReport,
)
