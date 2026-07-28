"""Phase 5 source-grounded discourse-act contract foundation."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .addressing_contracts import MediaInterval, TimeDomain
from .contracts import Contract, Severity, Sha256
from .phase2_contracts import ConfidenceMeasure

PHASE5_FORMAT_VERSION = "1.0.0"
DISCOURSE_VOCABULARY_VERSION = "1.0.0"
DISCOURSE_ANALYSIS_POLICY_VERSION = "1.0.0"
DISCOURSE_PROPAGATION_POLICY_VERSION = "1.0.0"


class DiscourseActFamily(str, Enum):
    ASSERTIVE = "assertive"
    QUESTION = "question"
    ANSWER = "answer"
    OBJECTION = "objection_and_challenge"
    REBUTTAL = "rebuttal"
    CONCESSION = "concession"
    QUALIFICATION = "qualification"
    DEFINITION = "definition"
    EXAMPLE = "example_and_illustration"
    QUOTATION = "quotation_and_attribution"
    PROCEDURAL = "procedural"
    OTHER = "other_conversational"
    UNKNOWN = "unknown"


class DiscourseActType(str, Enum):
    ASSERTION = "assertion"
    DENIAL = "denial"
    AFFIRMATION = "affirmation"
    PREDICTION = "prediction"
    REPORT = "report"
    DESCRIPTION = "description"
    ATTRIBUTION = "attribution"
    EVALUATION = "evaluation"
    ASSERTIVE_CORRECTION = "assertive_correction"
    RESTATEMENT = "restatement"
    SUMMARY = "summary"
    UNCERTAINTY_STATEMENT = "uncertainty_statement"
    INFORMATION_QUESTION = "information_question"
    YES_NO_QUESTION = "yes_or_no_question"
    ALTERNATIVE_QUESTION = "alternative_question"
    CLARIFICATION_QUESTION = "clarification_question"
    CONFIRMATION_QUESTION = "confirmation_question"
    CHALLENGE_QUESTION = "challenge_question"
    RHETORICAL_QUESTION = "rhetorical_question"
    FOLLOW_UP_QUESTION = "follow_up_question"
    PROCEDURAL_QUESTION = "procedural_question"
    EMBEDDED_OR_QUOTED_QUESTION = "embedded_or_quoted_question"
    DIRECT_ANSWER = "direct_answer"
    PARTIAL_ANSWER = "partial_answer"
    QUALIFIED_ANSWER = "qualified_answer"
    INDIRECT_ANSWER = "indirect_answer"
    NEGATIVE_ANSWER = "negative_answer"
    AFFIRMATIVE_ANSWER = "affirmative_answer"
    ANSWER_BY_CORRECTION = "answer_by_correction"
    ANSWER_BY_REJECTION_OF_PREMISE = "answer_by_rejection_of_premise"
    ANSWER_DEFERRED = "answer_deferred"
    REFUSAL_TO_ANSWER = "explicit_refusal_to_answer"
    INABILITY_TO_ANSWER = "inability_to_answer"
    UNRESOLVED_TARGET_ANSWER = "candidate_answer_with_unresolved_target"
    OBJECTION = "objection"
    CHALLENGE = "challenge"
    DISAGREEMENT = "disagreement"
    COUNTEREXAMPLE_PROPOSAL = "counterexample_proposal"
    PREMISE_CHALLENGE = "premise_challenge"
    RELEVANCE_CHALLENGE = "relevance_challenge"
    DEFINITION_CHALLENGE = "definition_challenge"
    EVIDENCE_CHALLENGE = "evidence_challenge"
    PROCEDURAL_OBJECTION = "procedural_objection"
    GENERALIZED_CHALLENGE = "unsupported_generalized_challenge"
    DIRECT_REBUTTAL = "direct_rebuttal"
    REBUTTAL_BY_DENIAL = "rebuttal_by_denial"
    REBUTTAL_BY_COUNTEREVIDENCE = "rebuttal_by_counterevidence"
    REBUTTAL_BY_COUNTEREXAMPLE = "rebuttal_by_counterexample"
    REBUTTAL_BY_ALTERNATIVE_EXPLANATION = (
        "rebuttal_by_alternative_explanation"
    )
    REBUTTAL_BY_QUALIFICATION = "rebuttal_by_qualification"
    REBUTTAL_BY_SCOPE_CORRECTION = "rebuttal_by_scope_correction"
    REBUTTAL_BY_CAUSAL_CHALLENGE = "rebuttal_by_causal_challenge"
    UNRESOLVED_TARGET_REBUTTAL = "purported_rebuttal_with_unresolved_target"
    FULL_CONCESSION = "full_concession"
    PARTIAL_CONCESSION = "partial_concession"
    TEMPORARY_CONCESSION = "temporary_concession"
    HYPOTHETICAL_CONCESSION = "hypothetical_concession"
    CONCESSION_FOR_ARGUMENT = "concession_for_argument"
    ACKNOWLEDGMENT_WITHOUT_AGREEMENT = "acknowledgment_without_agreement"
    UNCERTAIN_SCOPE_CONCESSION = "apparent_concession_with_uncertain_scope"
    SCOPE_QUALIFICATION = "scope_qualification"
    TEMPORAL_QUALIFICATION = "temporal_qualification"
    CONDITIONAL_QUALIFICATION = "conditional_qualification"
    PROBABILISTIC_QUALIFICATION = "probabilistic_qualification"
    EXCEPTION = "exception"
    LIMITATION = "limitation"
    HEDGING = "hedging"
    PRECISION_CORRECTION = "precision_correction"
    CATEGORY_RESTRICTION = "category_restriction"
    THRESHOLD_QUALIFICATION = "threshold_qualification"
    EXPLICIT_DEFINITION = "explicit_definition"
    OPERATIONAL_DEFINITION = "operational_definition"
    STIPULATIVE_DEFINITION = "stipulative_definition"
    LEXICAL_DEFINITION = "lexical_definition"
    CATEGORY_INCLUSION = "category_inclusion"
    CATEGORY_EXCLUSION = "category_exclusion"
    DISTINCTION = "distinction"
    TERM_CLARIFICATION = "term_clarification"
    DEFINITION_CHALLENGE_ACT = "definition_challenge_act"
    EXAMPLE = "example"
    COUNTEREXAMPLE = "counterexample"
    ANALOGY = "analogy"
    ILLUSTRATION = "illustration"
    ANECDOTAL_EXAMPLE = "anecdotal_example"
    HYPOTHETICAL_EXAMPLE = "hypothetical_example"
    CASE_CITATION = "case_citation"
    ENUMERATION = "enumeration"
    INCOMPLETE_EXAMPLE = "example_introduced_but_incomplete"
    DIRECT_QUOTATION = "direct_quotation"
    PARTIAL_QUOTATION = "partial_quotation"
    PARAPHRASE = "paraphrase"
    REPORTED_SPEECH = "reported_speech"
    ATTRIBUTED_POSITION = "attributed_position"
    SELF_QUOTATION = "self_quotation"
    PRIOR_UTTERANCE_CITATION = "citation_of_prior_utterance"
    QUOTATION_CHALLENGE = "quotation_challenge"
    QUOTATION_CORRECTION = "quotation_correction"
    UNCERTAIN_ATTRIBUTION = "uncertain_attribution"
    FLOOR_REQUEST = "floor_request"
    FLOOR_GRANT = "floor_grant"
    FLOOR_DENIAL = "floor_denial"
    TURN_YIELD = "turn_yield"
    TIME_WARNING = "time_warning"
    TIME_EXPIRED_NOTICE = "time_expired_notice"
    TOPIC_TRANSITION = "topic_transition"
    AGENDA_SETTING = "agenda_setting"
    REQUEST_TO_ANSWER = "request_to_answer"
    REQUEST_TO_CLARIFY = "request_to_clarify"
    REQUEST_TO_STOP = "request_to_stop"
    MODERATOR_INTERVENTION = "moderator_intervention"
    RULE_INVOCATION = "rule_invocation"
    RULE_EXPLANATION = "rule_explanation"
    PROCEDURE_ACKNOWLEDGMENT = "acknowledgment_of_procedure"
    INTRODUCTION = "introduction"
    CLOSING = "closing"
    GREETING = "greeting"
    THANKS = "thanks"
    APOLOGY = "apology"
    TECHNICAL_INTERRUPTION_NOTICE = "technical_interruption_notice"
    REQUEST = "request"
    COMMAND = "command"
    PROPOSAL = "proposal"
    OFFER = "offer"
    PROMISE = "promise"
    COMMITMENT = "commitment"
    WITHDRAWAL = "withdrawal"
    RETRACTION = "retraction"
    SELF_CORRECTION = "self_correction"
    ACKNOWLEDGMENT = "acknowledgment"
    AGREEMENT = "agreement"
    OTHER_DISAGREEMENT = "other_disagreement"
    BACKCHANNEL = "backchannel"
    ASSENT = "assent"
    DISSENT = "dissent"
    TOPIC_REDIRECTION = "topic_redirection"
    META_DISCOURSE = "meta_discourse"
    CEREMONIAL_OR_PHATIC = "ceremonial_or_phatic"
    NON_LEXICAL = "non_lexical"
    MIXED_OR_AMBIGUOUS = "mixed_or_ambiguous"
    INSUFFICIENT_CONTEXT = "insufficient_context"
    TRUNCATED_ACT = "truncated_act"
    UNINTELLIGIBLE_ACT = "unintelligible_act"
    UNSUPPORTED_ACT_TYPE = "unsupported_act_type"
    UNKNOWN = "unknown"
    OTHER = "other"


FAMILY_TYPES: dict[DiscourseActFamily, frozenset[DiscourseActType]] = {
    DiscourseActFamily.ASSERTIVE: frozenset({
        DiscourseActType.ASSERTION, DiscourseActType.DENIAL,
        DiscourseActType.AFFIRMATION, DiscourseActType.PREDICTION,
        DiscourseActType.REPORT, DiscourseActType.DESCRIPTION,
        DiscourseActType.ATTRIBUTION, DiscourseActType.EVALUATION,
        DiscourseActType.ASSERTIVE_CORRECTION, DiscourseActType.RESTATEMENT,
        DiscourseActType.SUMMARY, DiscourseActType.UNCERTAINTY_STATEMENT,
    }),
    DiscourseActFamily.QUESTION: frozenset({
        DiscourseActType.INFORMATION_QUESTION,
        DiscourseActType.YES_NO_QUESTION,
        DiscourseActType.ALTERNATIVE_QUESTION,
        DiscourseActType.CLARIFICATION_QUESTION,
        DiscourseActType.CONFIRMATION_QUESTION,
        DiscourseActType.CHALLENGE_QUESTION,
        DiscourseActType.RHETORICAL_QUESTION,
        DiscourseActType.FOLLOW_UP_QUESTION,
        DiscourseActType.PROCEDURAL_QUESTION,
        DiscourseActType.EMBEDDED_OR_QUOTED_QUESTION,
    }),
    DiscourseActFamily.ANSWER: frozenset({
        DiscourseActType.DIRECT_ANSWER, DiscourseActType.PARTIAL_ANSWER,
        DiscourseActType.QUALIFIED_ANSWER, DiscourseActType.INDIRECT_ANSWER,
        DiscourseActType.NEGATIVE_ANSWER, DiscourseActType.AFFIRMATIVE_ANSWER,
        DiscourseActType.ANSWER_BY_CORRECTION,
        DiscourseActType.ANSWER_BY_REJECTION_OF_PREMISE,
        DiscourseActType.ANSWER_DEFERRED,
        DiscourseActType.REFUSAL_TO_ANSWER,
        DiscourseActType.INABILITY_TO_ANSWER,
        DiscourseActType.UNRESOLVED_TARGET_ANSWER,
    }),
    DiscourseActFamily.OBJECTION: frozenset({
        DiscourseActType.OBJECTION, DiscourseActType.CHALLENGE,
        DiscourseActType.DISAGREEMENT,
        DiscourseActType.COUNTEREXAMPLE_PROPOSAL,
        DiscourseActType.PREMISE_CHALLENGE,
        DiscourseActType.RELEVANCE_CHALLENGE,
        DiscourseActType.DEFINITION_CHALLENGE,
        DiscourseActType.EVIDENCE_CHALLENGE,
        DiscourseActType.PROCEDURAL_OBJECTION,
        DiscourseActType.GENERALIZED_CHALLENGE,
    }),
    DiscourseActFamily.REBUTTAL: frozenset({
        DiscourseActType.DIRECT_REBUTTAL,
        DiscourseActType.REBUTTAL_BY_DENIAL,
        DiscourseActType.REBUTTAL_BY_COUNTEREVIDENCE,
        DiscourseActType.REBUTTAL_BY_COUNTEREXAMPLE,
        DiscourseActType.REBUTTAL_BY_ALTERNATIVE_EXPLANATION,
        DiscourseActType.REBUTTAL_BY_QUALIFICATION,
        DiscourseActType.REBUTTAL_BY_SCOPE_CORRECTION,
        DiscourseActType.REBUTTAL_BY_CAUSAL_CHALLENGE,
        DiscourseActType.UNRESOLVED_TARGET_REBUTTAL,
    }),
    DiscourseActFamily.CONCESSION: frozenset({
        DiscourseActType.FULL_CONCESSION,
        DiscourseActType.PARTIAL_CONCESSION,
        DiscourseActType.TEMPORARY_CONCESSION,
        DiscourseActType.HYPOTHETICAL_CONCESSION,
        DiscourseActType.CONCESSION_FOR_ARGUMENT,
        DiscourseActType.ACKNOWLEDGMENT_WITHOUT_AGREEMENT,
        DiscourseActType.UNCERTAIN_SCOPE_CONCESSION,
    }),
    DiscourseActFamily.QUALIFICATION: frozenset({
        DiscourseActType.SCOPE_QUALIFICATION,
        DiscourseActType.TEMPORAL_QUALIFICATION,
        DiscourseActType.CONDITIONAL_QUALIFICATION,
        DiscourseActType.PROBABILISTIC_QUALIFICATION,
        DiscourseActType.EXCEPTION, DiscourseActType.LIMITATION,
        DiscourseActType.HEDGING,
        DiscourseActType.PRECISION_CORRECTION,
        DiscourseActType.CATEGORY_RESTRICTION,
        DiscourseActType.THRESHOLD_QUALIFICATION,
    }),
    DiscourseActFamily.DEFINITION: frozenset({
        DiscourseActType.EXPLICIT_DEFINITION,
        DiscourseActType.OPERATIONAL_DEFINITION,
        DiscourseActType.STIPULATIVE_DEFINITION,
        DiscourseActType.LEXICAL_DEFINITION,
        DiscourseActType.CATEGORY_INCLUSION,
        DiscourseActType.CATEGORY_EXCLUSION,
        DiscourseActType.DISTINCTION,
        DiscourseActType.TERM_CLARIFICATION,
        DiscourseActType.DEFINITION_CHALLENGE_ACT,
    }),
    DiscourseActFamily.EXAMPLE: frozenset({
        DiscourseActType.EXAMPLE, DiscourseActType.COUNTEREXAMPLE,
        DiscourseActType.ANALOGY, DiscourseActType.ILLUSTRATION,
        DiscourseActType.ANECDOTAL_EXAMPLE,
        DiscourseActType.HYPOTHETICAL_EXAMPLE,
        DiscourseActType.CASE_CITATION, DiscourseActType.ENUMERATION,
        DiscourseActType.INCOMPLETE_EXAMPLE,
    }),
    DiscourseActFamily.QUOTATION: frozenset({
        DiscourseActType.DIRECT_QUOTATION,
        DiscourseActType.PARTIAL_QUOTATION,
        DiscourseActType.PARAPHRASE,
        DiscourseActType.REPORTED_SPEECH,
        DiscourseActType.ATTRIBUTED_POSITION,
        DiscourseActType.SELF_QUOTATION,
        DiscourseActType.PRIOR_UTTERANCE_CITATION,
        DiscourseActType.QUOTATION_CHALLENGE,
        DiscourseActType.QUOTATION_CORRECTION,
        DiscourseActType.UNCERTAIN_ATTRIBUTION,
    }),
    DiscourseActFamily.PROCEDURAL: frozenset({
        DiscourseActType.FLOOR_REQUEST, DiscourseActType.FLOOR_GRANT,
        DiscourseActType.FLOOR_DENIAL, DiscourseActType.TURN_YIELD,
        DiscourseActType.TIME_WARNING,
        DiscourseActType.TIME_EXPIRED_NOTICE,
        DiscourseActType.TOPIC_TRANSITION,
        DiscourseActType.AGENDA_SETTING,
        DiscourseActType.REQUEST_TO_ANSWER,
        DiscourseActType.REQUEST_TO_CLARIFY,
        DiscourseActType.REQUEST_TO_STOP,
        DiscourseActType.MODERATOR_INTERVENTION,
        DiscourseActType.RULE_INVOCATION,
        DiscourseActType.RULE_EXPLANATION,
        DiscourseActType.PROCEDURE_ACKNOWLEDGMENT,
        DiscourseActType.INTRODUCTION, DiscourseActType.CLOSING,
        DiscourseActType.GREETING, DiscourseActType.THANKS,
        DiscourseActType.APOLOGY,
        DiscourseActType.TECHNICAL_INTERRUPTION_NOTICE,
    }),
    DiscourseActFamily.OTHER: frozenset({
        DiscourseActType.REQUEST, DiscourseActType.COMMAND,
        DiscourseActType.PROPOSAL, DiscourseActType.OFFER,
        DiscourseActType.PROMISE, DiscourseActType.COMMITMENT,
        DiscourseActType.WITHDRAWAL, DiscourseActType.RETRACTION,
        DiscourseActType.SELF_CORRECTION,
        DiscourseActType.ACKNOWLEDGMENT, DiscourseActType.AGREEMENT,
        DiscourseActType.OTHER_DISAGREEMENT,
        DiscourseActType.BACKCHANNEL, DiscourseActType.ASSENT,
        DiscourseActType.DISSENT, DiscourseActType.TOPIC_REDIRECTION,
        DiscourseActType.META_DISCOURSE,
    }),
    DiscourseActFamily.UNKNOWN: frozenset({
        DiscourseActType.CEREMONIAL_OR_PHATIC,
        DiscourseActType.NON_LEXICAL,
        DiscourseActType.MIXED_OR_AMBIGUOUS,
        DiscourseActType.INSUFFICIENT_CONTEXT,
        DiscourseActType.TRUNCATED_ACT,
        DiscourseActType.UNINTELLIGIBLE_ACT,
        DiscourseActType.UNSUPPORTED_ACT_TYPE,
        DiscourseActType.UNKNOWN, DiscourseActType.OTHER,
    }),
}


class DiscourseRelationType(str, Enum):
    ANSWERS = "answers"
    RESPONDS_TO = "responds_to"
    CLARIFIES = "clarifies"
    CORRECTS = "corrects"
    OBJECTS_TO = "objects_to"
    CHALLENGES = "challenges"
    REBUTS = "rebuts"
    CONCEDES = "concedes"
    QUALIFIES = "qualifies"
    LIMITS = "limits"
    DEFINES = "defines"
    EXEMPLIFIES = "exemplifies"
    QUOTES = "quotes"
    ATTRIBUTES = "attributes"
    REPEATS = "repeats"
    SUMMARIZES = "summarizes"
    REDIRECTS_FROM = "redirects_from"
    REQUESTS_SUPPORT_FOR = "requests_support_for"
    INVOKES_PROCEDURE_AGAINST = "invokes_procedure_against"
    REQUESTS_CLARIFICATION_OF = "requests_clarification_of"
    UNRESOLVED = "unresolved_relation"


class DiscourseEvidenceSpanRole(str, Enum):
    ACT_TRIGGER = "act_trigger"
    ACT_CONTENT = "act_content"
    TARGET_REFERENCE = "target_reference"
    QUALIFICATION_MARKER = "qualification_marker"
    CONCESSION_MARKER = "concession_marker"
    NEGATION = "negation"
    QUOTATION = "quotation"
    PROCEDURAL_FORMULA = "procedural_formula"
    CONTEXTUAL_SUPPORT = "contextual_support"


class DiscourseTargetType(str, Enum):
    UTTERANCE = "utterance"
    DISCOURSE_ACT = "discourse_act"
    QUESTION = "question"
    PROPOSITION_LIKE_PLACEHOLDER = "proposition_like_placeholder"
    PROCEDURAL_STATE = "procedural_state"
    IMPLICIT = "implicit"
    UNRESOLVED = "unresolved"


class DiscourseTargetStatus(str, Enum):
    IDENTIFIED = "identified"
    PROBABLE = "probable"
    MULTIPLE_CANDIDATES = "multiple_candidate_targets"
    IMPLICIT = "implicit"
    UNRESOLVED = "unresolved"


class DiscourseAnalysisMethod(str, Enum):
    DETERMINISTIC_RULE = "deterministic_rule"
    PROVIDER_PROPOSAL = "provider_proposal"
    HYBRID_CONSOLIDATION = "hybrid_consolidation"
    HUMAN_REVIEW = "human_review"
    IMPORTED_REFERENCE = "imported_reference"


class DiscourseReviewStatus(str, Enum):
    UNREVIEWED = "unreviewed"
    REVIEW_REQUIRED = "review_required"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISED = "revised"
    DEFERRED = "deferred"
    CONFLICTED = "conflicted"


class CandidateDisposition(str, Enum):
    PROPOSED = "proposed"
    SELECTED = "selected"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    UNRESOLVED = "unresolved"


class DiscourseProviderCapability(str, Enum):
    MULTI_LABEL_CLASSIFICATION = "multi_label_classification"
    EVIDENCE_SPANS = "evidence_spans"
    RELATION_TARGETS = "relation_targets"
    ALTERNATIVES = "alternatives"
    STRUCTURED_OUTPUT = "structured_output"
    DETERMINISTIC_SEED = "deterministic_seed"


class DiscourseVocabularyPolicy(Contract):
    vocabulary_version: Literal["1.0.0"] = DISCOURSE_VOCABULARY_VERSION
    closed_vocabulary: Literal[True] = True
    multi_label_required: Literal[True] = True
    unknown_is_valid: Literal[True] = True
    assertion_implies_truth: Literal[False] = False
    answer_implies_adequacy: Literal[False] = False
    rebuttal_implies_success: Literal[False] = False
    procedure_implies_violation: Literal[False] = False
    intent_inference: Literal["prohibited"] = "prohibited"
    participant_scoring: Literal["prohibited"] = "prohibited"


class DiscourseAnalysisPolicy(Contract):
    policy_version: Literal["1.0.0"] = DISCOURSE_ANALYSIS_POLICY_VERSION
    phase4_text_view_kind: Literal["display"] = "display"
    context_window_policy_version: str = Field(min_length=1)
    maximum_context_utterances: int = Field(default=12, ge=1, le=100)
    maximum_context_tokens: int = Field(default=4096, ge=1)
    maximum_context_duration_microseconds: int = Field(
        default=120_000_000, ge=1
    )
    maximum_candidates_per_span: int = Field(default=5, ge=1, le=20)
    relation_search_window_utterances: int = Field(default=20, ge=1)
    deterministic_rule_version: str = Field(default="1.0.0", min_length=1)
    preserve_unknown: Literal[True] = True
    retain_raw_provider_evidence: Literal[True] = True
    schema_validation_required: Literal[True] = True
    timeout_seconds: int = Field(default=120, ge=1)
    maximum_retries: int = Field(default=1, ge=0, le=5)
    automatic_authority: Literal[False] = False


class DiscourseCorrectionPropagationPolicy(Contract):
    policy_version: Literal["1.0.0"] = (
        DISCOURSE_PROPAGATION_POLICY_VERSION
    )
    text_change_invalidates_spans: Literal[True] = True
    boundary_change_invalidates_spans: Literal[True] = True
    quotation_change_invalidates_quotation_use: Literal[True] = True
    relation_change_invalidates_targets: Literal[True] = True
    display_label_only_preserves_classification: Literal[True] = True
    preserve_unaffected_identifiers: Literal[True] = True
    rebuild_procedural_state: Literal[True] = True
    rebuild_review_queues: Literal[True] = True


class DiscourseProviderIdentity(Contract):
    provider_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    display_name: str = Field(min_length=1)
    provider_version: str = Field(min_length=1)
    model_id: str | None = None
    model_version: str | None = None
    model_fingerprint: Sha256 | None = None
    runtime_fingerprint: Sha256 | None = None
    local: bool


class DiscourseProviderCapabilities(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    identity: DiscourseProviderIdentity
    capabilities: tuple[DiscourseProviderCapability, ...]
    available: bool
    deterministic: bool
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def capabilities_are_unique(self) -> "DiscourseProviderCapabilities":
        if len(self.capabilities) != len(set(self.capabilities)):
            raise ValueError("provider capabilities must be unique")
        return self


class DiscourseConfidence(Contract):
    act_type: ConfidenceMeasure
    evidence_span: ConfidenceMeasure
    target_relation: ConfidenceMeasure
    selection: ConfidenceMeasure
    question_type: ConfidenceMeasure | None = None
    answer_link: ConfidenceMeasure | None = None
    quotation_use: ConfidenceMeasure | None = None
    procedural_state: ConfidenceMeasure | None = None
    derivation_method: str = Field(min_length=1)
    source_features: tuple[str, ...] = Field(min_length=1)
    limitations: tuple[str, ...] = Field(min_length=1)


class DiscourseEvidenceSpan(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    span_id: str = Field(pattern=r"^discoursespan_[a-f0-9]{32}$")
    utterance_id: str = Field(pattern=r"^utterance_[a-f0-9]{32}$")
    utterance_text_view_id: str = Field(
        pattern=r"^utterancetext_[a-f0-9]{32}$"
    )
    text_view_version: str = Field(min_length=1)
    start_text_offset: int = Field(ge=0)
    end_text_offset: int = Field(gt=0)
    transcript_word_ids: tuple[str, ...] = ()
    source_interval: MediaInterval
    exact_displayed_text: str = Field(min_length=1)
    role: DiscourseEvidenceSpanRole
    confidence: ConfidenceMeasure
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def span_addressing_is_coherent(self) -> "DiscourseEvidenceSpan":
        if self.end_text_offset <= self.start_text_offset:
            raise ValueError("evidence span offsets must be ordered")
        if self.source_interval.domain != TimeDomain.SOURCE_MEDIA:
            raise ValueError("evidence span requires source-media time")
        if len(self.transcript_word_ids) != len(set(self.transcript_word_ids)):
            raise ValueError("evidence span word references must be unique")
        return self


class DiscourseRelationTargetProposal(Contract):
    proposal_id: str = Field(pattern=r"^discoursetarget_[a-f0-9]{32}$")
    target_type: DiscourseTargetType
    target_status: DiscourseTargetStatus
    target_id: str | None = None
    alternative_target_ids: tuple[str, ...] = ()
    relation_type: DiscourseRelationType
    evidence_span_ids: tuple[str, ...] = Field(min_length=1)
    temporal_distance_microseconds: int | None = None
    context_window_id: str | None = Field(
        default=None, pattern=r"^contextwindow_[a-f0-9]{32}$"
    )
    confidence: ConfidenceMeasure
    basis: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def target_state_is_coherent(self) -> "DiscourseRelationTargetProposal":
        if self.target_status in {
            DiscourseTargetStatus.IDENTIFIED,
            DiscourseTargetStatus.PROBABLE,
        } and self.target_id is None:
            raise ValueError("identified or probable target requires an id")
        if self.target_status in {
            DiscourseTargetStatus.IMPLICIT,
            DiscourseTargetStatus.UNRESOLVED,
        } and self.target_id is not None:
            raise ValueError("implicit or unresolved target cannot force an id")
        if (
            self.target_status == DiscourseTargetStatus.MULTIPLE_CANDIDATES
            and len(self.alternative_target_ids) < 2
        ):
            raise ValueError("multiple targets require at least two candidates")
        if len(self.alternative_target_ids) != len(
            set(self.alternative_target_ids)
        ):
            raise ValueError("alternative target ids must be unique")
        return self


class DiscourseActObservation(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    observation_id: str = Field(pattern=r"^discourseobs_[a-f0-9]{32}$")
    discourse_run_id: str = Field(pattern=r"^discourserun_[a-f0-9]{32}$")
    phase4_utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    utterance_id: str = Field(pattern=r"^utterance_[a-f0-9]{32}$")
    evidence_spans: tuple[DiscourseEvidenceSpan, ...] = Field(min_length=1)
    act_family: DiscourseActFamily
    act_type: DiscourseActType
    act_modifiers: tuple[str, ...] = ()
    proposed_targets: tuple[DiscourseRelationTargetProposal, ...] = ()
    confidence: DiscourseConfidence
    analysis_method: DiscourseAnalysisMethod
    provider: DiscourseProviderIdentity | None = None
    raw_evidence_sha256: Sha256 | None = None
    alternative_observation_ids: tuple[str, ...] = ()
    contrary_evidence: tuple[str, ...] = ()
    context_window_id: str | None = Field(
        default=None, pattern=r"^contextwindow_[a-f0-9]{32}$"
    )
    review_status: DiscourseReviewStatus
    created_at: datetime
    vocabulary_version: Literal["1.0.0"] = DISCOURSE_VOCABULARY_VERSION
    policy_version: Literal["1.0.0"] = DISCOURSE_ANALYSIS_POLICY_VERSION
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def observation_is_coherent(self) -> "DiscourseActObservation":
        if self.act_type not in FAMILY_TYPES[self.act_family]:
            raise ValueError("act type does not belong to declared family")
        if any(item.utterance_id != self.utterance_id for item in self.evidence_spans):
            raise ValueError("observation spans target another utterance")
        span_ids = [item.span_id for item in self.evidence_spans]
        if len(span_ids) != len(set(span_ids)):
            raise ValueError("observation evidence spans must be unique")
        known = set(span_ids)
        if any(
            not set(item.evidence_span_ids).issubset(known)
            for item in self.proposed_targets
        ):
            raise ValueError("target proposal references unknown evidence span")
        if (
            self.analysis_method == DiscourseAnalysisMethod.PROVIDER_PROPOSAL
            and self.provider is None
        ):
            raise ValueError("provider proposal requires provider provenance")
        if (
            self.analysis_method != DiscourseAnalysisMethod.PROVIDER_PROPOSAL
            and self.provider is not None
        ):
            raise ValueError("non-provider observation cannot claim provider")
        return self


class DiscourseActCandidate(Contract):
    candidate_id: str = Field(pattern=r"^discoursecandidate_[a-f0-9]{32}$")
    observation_ids: tuple[str, ...] = Field(min_length=1)
    act_family: DiscourseActFamily
    act_type: DiscourseActType
    evidence_span_ids: tuple[str, ...] = Field(min_length=1)
    target_proposal_ids: tuple[str, ...] = ()
    compatible_candidate_ids: tuple[str, ...] = ()
    excludes_candidate_ids: tuple[str, ...] = ()
    disposition: CandidateDisposition
    selection_confidence: ConfidenceMeasure
    selection_rationale: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def candidate_is_coherent(self) -> "DiscourseActCandidate":
        if self.act_type not in FAMILY_TYPES[self.act_family]:
            raise ValueError("candidate type does not belong to family")
        if set(self.compatible_candidate_ids).intersection(
            self.excludes_candidate_ids
        ):
            raise ValueError("candidate cannot both allow and exclude a peer")
        for values in (
            self.observation_ids,
            self.evidence_span_ids,
            self.target_proposal_ids,
            self.compatible_candidate_ids,
            self.excludes_candidate_ids,
        ):
            if len(values) != len(set(values)):
                raise ValueError("candidate references must be unique")
        return self


class DiscourseActCandidateSet(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    candidate_set_id: str = Field(
        pattern=r"^discoursecandidates_[a-f0-9]{32}$"
    )
    utterance_id: str = Field(pattern=r"^utterance_[a-f0-9]{32}$")
    candidates: tuple[DiscourseActCandidate, ...] = Field(min_length=1)
    selection_policy_version: str = Field(min_length=1)
    unresolved: bool
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def selections_are_compatible(self) -> "DiscourseActCandidateSet":
        ids = [item.candidate_id for item in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("candidate ids must be unique")
        known = set(ids)
        if any(
            not (
                set(item.compatible_candidate_ids)
                | set(item.excludes_candidate_ids)
            ).issubset(known - {item.candidate_id})
            for item in self.candidates
        ):
            raise ValueError("candidate references unknown peer")
        selected = {
            item.candidate_id
            for item in self.candidates
            if item.disposition == CandidateDisposition.SELECTED
        }
        if any(
            selected.intersection(item.excludes_candidate_ids)
            for item in self.candidates
            if item.candidate_id in selected
        ):
            raise ValueError("selected candidates are incompatible")
        if not selected and not self.unresolved:
            raise ValueError("resolved candidate set requires selection")
        return self


class DiscourseAct(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    act_id: str = Field(pattern=r"^discourseact_[a-f0-9]{32}$")
    discourse_corpus_id: str = Field(
        pattern=r"^discoursecorpus_[a-f0-9]{32}$"
    )
    candidate_set_id: str = Field(
        pattern=r"^discoursecandidates_[a-f0-9]{32}$"
    )
    selected_candidate_id: str = Field(
        pattern=r"^discoursecandidate_[a-f0-9]{32}$"
    )
    source_observation_ids: tuple[str, ...] = Field(min_length=1)
    utterance_id: str = Field(pattern=r"^utterance_[a-f0-9]{32}$")
    act_family: DiscourseActFamily
    act_type: DiscourseActType
    evidence_spans: tuple[DiscourseEvidenceSpan, ...] = Field(min_length=1)
    relation_targets: tuple[DiscourseRelationTargetProposal, ...] = ()
    confidence: DiscourseConfidence
    review_status: DiscourseReviewStatus
    predecessor_act_ids: tuple[str, ...] = ()
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def selected_act_is_coherent(self) -> "DiscourseAct":
        if self.act_type not in FAMILY_TYPES[self.act_family]:
            raise ValueError("selected act type does not belong to family")
        if any(item.utterance_id != self.utterance_id for item in self.evidence_spans):
            raise ValueError("selected act spans target another utterance")
        return self


class DiscourseRun(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    run_id: str = Field(pattern=r"^discourserun_[a-f0-9]{32}$")
    discourse_corpus_id: str = Field(
        pattern=r"^discoursecorpus_[a-f0-9]{32}$"
    )
    phase4_utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    phase4_utterance_corpus_sha256: Sha256
    vocabulary: DiscourseVocabularyPolicy
    analysis_policy: DiscourseAnalysisPolicy
    propagation_policy: DiscourseCorrectionPropagationPolicy
    configuration_hash: Sha256
    observation_ids: tuple[str, ...]
    candidate_set_ids: tuple[str, ...]
    selected_act_ids: tuple[str, ...]
    created_at: datetime
    complete: bool
    integrity_sha256: Sha256


class DiscourseCorpus(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    corpus_id: str = Field(pattern=r"^discoursecorpus_[a-f0-9]{32}$")
    run_id: str = Field(pattern=r"^discourserun_[a-f0-9]{32}$")
    source_corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    source_id: str = Field(pattern=r"^src_[a-f0-9]{32}$")
    phase4_utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    phase4_utterance_corpus_sha256: Sha256
    observations: tuple[DiscourseActObservation, ...]
    candidate_sets: tuple[DiscourseActCandidateSet, ...]
    selected_acts: tuple[DiscourseAct, ...]
    unclassified_utterance_ids: tuple[str, ...]
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def corpus_references_are_coherent(self) -> "DiscourseCorpus":
        observation_ids = [item.observation_id for item in self.observations]
        candidate_set_ids = [item.candidate_set_id for item in self.candidate_sets]
        act_ids = [item.act_id for item in self.selected_acts]
        for values in (observation_ids, candidate_set_ids, act_ids):
            if len(values) != len(set(values)):
                raise ValueError("discourse corpus child ids must be unique")
        if len(self.unclassified_utterance_ids) != len(
            set(self.unclassified_utterance_ids)
        ):
            raise ValueError("unclassified utterance ids must be unique")
        if any(
            item.phase4_utterance_corpus_id
            != self.phase4_utterance_corpus_id
            for item in self.observations
        ):
            raise ValueError("observation uses incompatible Phase 4 lineage")
        if any(item.discourse_corpus_id != self.corpus_id for item in self.selected_acts):
            raise ValueError("selected act uses incompatible discourse lineage")
        known_observations = set(observation_ids)
        known_sets = set(candidate_set_ids)
        if any(
            not set(item.source_observation_ids).issubset(known_observations)
            or item.candidate_set_id not in known_sets
            for item in self.selected_acts
        ):
            raise ValueError("selected act references unknown foundation evidence")
        classified = {item.utterance_id for item in self.selected_acts}
        if classified.intersection(self.unclassified_utterance_ids):
            raise ValueError("utterance cannot be classified and unclassified")
        return self


class Phase5IntegrityFinding(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    finding_id: str = Field(pattern=r"^phase5finding_[a-f0-9]{32}$")
    code: str = Field(pattern=r"^phase5\.[a-z0-9_.-]+$")
    severity: Severity
    message: str = Field(min_length=1)
    artifact_ids: tuple[str, ...] = ()
    evidence_references: tuple[str, ...] = ()


class Phase5IntegrityResult(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    result_id: str = Field(pattern=r"^phase5integrity_[a-f0-9]{32}$")
    discourse_corpus_id: str = Field(
        pattern=r"^discoursecorpus_[a-f0-9]{32}$"
    )
    phase4_utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    checked_at: datetime
    findings: tuple[Phase5IntegrityFinding, ...] = ()
    valid: bool
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def validity_matches_findings(self) -> "Phase5IntegrityResult":
        blocking = any(
            item.severity in {Severity.ERROR, Severity.FATAL}
            for item in self.findings
        )
        if self.valid == blocking:
            raise ValueError("integrity validity disagrees with findings")
        return self


PHASE5_CONTRACT_MODELS = (
    DiscourseVocabularyPolicy,
    DiscourseAnalysisPolicy,
    DiscourseCorrectionPropagationPolicy,
    DiscourseProviderIdentity,
    DiscourseProviderCapabilities,
    DiscourseConfidence,
    DiscourseEvidenceSpan,
    DiscourseRelationTargetProposal,
    DiscourseActObservation,
    DiscourseActCandidate,
    DiscourseActCandidateSet,
    DiscourseAct,
    DiscourseRun,
    DiscourseCorpus,
    Phase5IntegrityFinding,
    Phase5IntegrityResult,
)
