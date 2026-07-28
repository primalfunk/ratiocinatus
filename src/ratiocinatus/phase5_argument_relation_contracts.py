"""Bounded challenge, rebuttal, concession, and qualification contracts."""

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
    DiscourseReviewStatus,
    DiscourseTargetStatus,
)

ARGUMENT_RELATION_POLICY_VERSION = "1.0.0"


class ChallengeDimension(str, Enum):
    CONTENT = "content"
    EVIDENCE = "evidence"
    WORDING = "wording"
    DEFINITION = "definition"
    PROCEDURE = "procedure"
    ATTRIBUTION = "attribution"
    PREMISE = "premise"
    RELEVANCE = "relevance"
    GENERAL = "general"
    UNRESOLVED = "unresolved"


class RebuttalMethod(str, Enum):
    DIRECT = "direct"
    DENIAL = "denial"
    COUNTEREVIDENCE = "counterevidence"
    COUNTEREXAMPLE = "counterexample"
    ALTERNATIVE_EXPLANATION = "alternative_explanation"
    QUALIFICATION = "qualification"
    SCOPE_CORRECTION = "scope_correction"
    CAUSAL_CHALLENGE = "causal_challenge"
    UNRESOLVED = "unresolved"


class QualificationDimension(str, Enum):
    SCOPE = "scope"
    TEMPORAL = "temporal"
    CONDITIONAL = "conditional"
    PROBABILISTIC = "probabilistic"
    EXCEPTION = "exception"
    LIMITATION = "limitation"
    HEDGING = "hedging"
    PRECISION = "precision"
    CATEGORY = "category"
    THRESHOLD = "threshold"
    UNRESOLVED = "unresolved"


class ArgumentRelationPolicy(Contract):
    policy_version: Literal["1.0.0"] = ARGUMENT_RELATION_POLICY_VERSION
    context_window_kind: Literal["bounded_temporal_window"] = (
        "bounded_temporal_window"
    )
    maximum_alternative_targets: int = Field(default=8, ge=1, le=50)
    exact_relation_targets_take_precedence: Literal[True] = True
    same_utterance_modifier_targets_take_precedence: Literal[True] = True
    temporal_target_is_probable_not_identified: Literal[True] = True
    preserve_target_ambiguity: Literal[True] = True
    unresolved_target_is_valid: Literal[True] = True
    rebuttal_success_assessment: Literal[False] = False
    factual_adjudication: Literal[False] = False
    intent_inference: Literal["prohibited"] = "prohibited"


class ChallengeRebuttalRelation(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    relation_id: str = Field(
        pattern=r"^challengerelation_[a-f0-9]{32}$"
    )
    discourse_corpus_id: str = Field(
        pattern=r"^discoursecorpus_[a-f0-9]{32}$"
    )
    source_act_id: str = Field(pattern=r"^discourseact_[a-f0-9]{32}$")
    source_utterance_id: str = Field(
        pattern=r"^utterance_[a-f0-9]{32}$"
    )
    source_family: Literal[
        DiscourseActFamily.OBJECTION,
        DiscourseActFamily.REBUTTAL,
    ]
    source_act_type: DiscourseActType
    challenge_dimension: ChallengeDimension | None = None
    rebuttal_method: RebuttalMethod | None = None
    target_status: DiscourseTargetStatus
    target_act_ids: tuple[str, ...]
    target_utterance_ids: tuple[str, ...]
    alternative_target_act_ids: tuple[str, ...] = ()
    challenged_span_ids: tuple[str, ...] = ()
    supporting_evidence_span_ids: tuple[str, ...] = Field(min_length=1)
    qualification_act_ids: tuple[str, ...] = ()
    context_window_id: str | None = Field(
        default=None, pattern=r"^contextwindow_[a-f0-9]{32}$"
    )
    temporal_distance_microseconds: int | None = None
    confidence: ConfidenceMeasure
    review_status: DiscourseReviewStatus
    unresolved_issues: tuple[str, ...] = ()
    rebuttal_success_assessed: Literal[False] = False
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def relation_is_coherent(self) -> "ChallengeRebuttalRelation":
        expected = FAMILY_TYPES[self.source_family]
        if self.source_act_type not in expected:
            raise ValueError("relation source type does not match its family")
        if self.source_family == DiscourseActFamily.OBJECTION:
            if self.challenge_dimension is None or self.rebuttal_method is not None:
                raise ValueError("objection requires challenge dimension only")
        if self.source_family == DiscourseActFamily.REBUTTAL:
            if self.rebuttal_method is None or self.challenge_dimension is not None:
                raise ValueError("rebuttal requires rebuttal method only")
        for values in (
            self.target_act_ids,
            self.target_utterance_ids,
            self.alternative_target_act_ids,
            self.challenged_span_ids,
            self.supporting_evidence_span_ids,
            self.qualification_act_ids,
            self.unresolved_issues,
        ):
            if len(values) != len(set(values)):
                raise ValueError("relation references must be unique")
        if set(self.target_act_ids).intersection(
            self.alternative_target_act_ids
        ):
            raise ValueError("target cannot also be an alternative")
        if self.target_status in {
            DiscourseTargetStatus.IDENTIFIED,
            DiscourseTargetStatus.PROBABLE,
        } and not self.target_act_ids:
            raise ValueError("resolved relation requires a target")
        if (
            self.target_status
            == DiscourseTargetStatus.MULTIPLE_CANDIDATES
            and len(self.alternative_target_act_ids) < 2
        ):
            raise ValueError("ambiguous relation requires alternatives")
        if self.target_status in {
            DiscourseTargetStatus.IMPLICIT,
            DiscourseTargetStatus.UNRESOLVED,
        } and self.target_act_ids:
            raise ValueError("unresolved relation cannot force a target")
        return self


class ConcessionStructure(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    concession_id: str = Field(pattern=r"^concession_[a-f0-9]{32}$")
    discourse_corpus_id: str = Field(
        pattern=r"^discoursecorpus_[a-f0-9]{32}$"
    )
    conceding_act_id: str = Field(pattern=r"^discourseact_[a-f0-9]{32}$")
    utterance_id: str = Field(pattern=r"^utterance_[a-f0-9]{32}$")
    concession_type: DiscourseActType
    target_status: DiscourseTargetStatus
    target_act_ids: tuple[str, ...]
    alternative_target_act_ids: tuple[str, ...] = ()
    conceded_content: tuple[str, ...] = Field(min_length=1)
    retained_disagreement: tuple[str, ...] = ()
    qualification_act_ids: tuple[str, ...] = ()
    scope_span_ids: tuple[str, ...] = Field(min_length=1)
    condition_text: tuple[str, ...] = ()
    exception_text: tuple[str, ...] = ()
    context_window_id: str | None = Field(
        default=None, pattern=r"^contextwindow_[a-f0-9]{32}$"
    )
    confidence: ConfidenceMeasure
    review_status: DiscourseReviewStatus
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def concession_is_coherent(self) -> "ConcessionStructure":
        if self.concession_type not in FAMILY_TYPES[DiscourseActFamily.CONCESSION]:
            raise ValueError("concession structure requires concession act")
        if (
            self.target_status
            == DiscourseTargetStatus.MULTIPLE_CANDIDATES
            and len(self.alternative_target_act_ids) < 2
        ):
            raise ValueError("ambiguous concession requires alternatives")
        return self


class QualificationStructure(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    qualification_id: str = Field(
        pattern=r"^qualification_[a-f0-9]{32}$"
    )
    discourse_corpus_id: str = Field(
        pattern=r"^discoursecorpus_[a-f0-9]{32}$"
    )
    qualifying_act_id: str = Field(pattern=r"^discourseact_[a-f0-9]{32}$")
    utterance_id: str = Field(pattern=r"^utterance_[a-f0-9]{32}$")
    qualification_type: DiscourseActType
    dimension: QualificationDimension
    target_status: DiscourseTargetStatus
    target_act_ids: tuple[str, ...]
    alternative_target_act_ids: tuple[str, ...] = ()
    target_span_ids: tuple[str, ...] = ()
    scope_text: tuple[str, ...] = Field(min_length=1)
    condition_text: tuple[str, ...] = ()
    exception_text: tuple[str, ...] = ()
    context_window_id: str | None = Field(
        default=None, pattern=r"^contextwindow_[a-f0-9]{32}$"
    )
    confidence: ConfidenceMeasure
    review_status: DiscourseReviewStatus
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def qualification_is_coherent(self) -> "QualificationStructure":
        if self.qualification_type not in FAMILY_TYPES[
            DiscourseActFamily.QUALIFICATION
        ]:
            raise ValueError("qualification structure requires qualification act")
        if (
            self.target_status
            == DiscourseTargetStatus.MULTIPLE_CANDIDATES
            and len(self.alternative_target_act_ids) < 2
        ):
            raise ValueError("ambiguous qualification requires alternatives")
        return self


class ArgumentRelationRun(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    argument_relation_run_id: str = Field(
        pattern=r"^argumentrelationrun_[a-f0-9]{32}$"
    )
    discourse_corpus_id: str = Field(
        pattern=r"^discoursecorpus_[a-f0-9]{32}$"
    )
    discourse_corpus_sha256: Sha256
    context_bundle_id: str = Field(pattern=r"^contextbundle_[a-f0-9]{32}$")
    context_bundle_sha256: Sha256
    policy: ArgumentRelationPolicy
    configuration_hash: Sha256
    challenge_rebuttal_relations: tuple[ChallengeRebuttalRelation, ...]
    concessions: tuple[ConcessionStructure, ...]
    qualifications: tuple[QualificationStructure, ...]
    unresolved_source_act_ids: tuple[str, ...]
    created_at: datetime
    complete: bool
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def children_are_unique(self) -> "ArgumentRelationRun":
        for values in (
            tuple(item.relation_id for item in self.challenge_rebuttal_relations),
            tuple(item.concession_id for item in self.concessions),
            tuple(item.qualification_id for item in self.qualifications),
            self.unresolved_source_act_ids,
        ):
            if len(values) != len(set(values)):
                raise ValueError("argument relation child ids must be unique")
        return self


class ArgumentRelationReport(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    report_id: str = Field(
        pattern=r"^argumentrelationreport_[a-f0-9]{32}$"
    )
    argument_relation_run_id: str = Field(
        pattern=r"^argumentrelationrun_[a-f0-9]{32}$"
    )
    generated_at: datetime
    objection_relation_count: int = Field(ge=0)
    rebuttal_relation_count: int = Field(ge=0)
    concession_count: int = Field(ge=0)
    qualification_count: int = Field(ge=0)
    identified_target_count: int = Field(ge=0)
    probable_target_count: int = Field(ge=0)
    ambiguous_target_count: int = Field(ge=0)
    unresolved_target_count: int = Field(ge=0)
    retained_disagreement_count: int = Field(ge=0)
    qualified_concession_count: int = Field(ge=0)
    limitations: tuple[str, ...] = Field(min_length=1)
    status: Literal["complete", "warning", "failed"]
    integrity_sha256: Sha256


PHASE5_ARGUMENT_RELATION_CONTRACT_MODELS = (
    ArgumentRelationPolicy,
    ChallengeRebuttalRelation,
    ConcessionStructure,
    QualificationStructure,
    ArgumentRelationRun,
    ArgumentRelationReport,
)
