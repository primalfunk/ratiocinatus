"""Phase 5 stage-local recovery and typed negative-proof contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract, Sha256
from .phase5_contracts import PHASE5_FORMAT_VERSION

PHASE5_RECOVERY_POLICY_VERSION = "1.0.0"


class Phase5RecoveryStage(str, Enum):
    DETERMINISTIC_CLASSIFICATION = "deterministic_classification"
    PROVIDER_ANALYSIS = "provider_analysis"
    EVIDENCE_SPAN_NORMALIZATION = "evidence_span_normalization"
    CANDIDATE_CONSOLIDATION = "candidate_consolidation"
    QUESTION_CONSTRUCTION = "question_construction"
    ANSWER_LINKING = "answer_linking"
    OBJECTION_REBUTTAL_LINKING = "objection_rebuttal_linking"
    CONCESSION_QUALIFICATION = "concession_qualification_construction"
    DEFINITION_EXAMPLE = "definition_example_construction"
    PROCEDURAL_STATE = "procedural_state_assembly"
    REVIEW_ASSEMBLY = "review_assembly"
    CORRECTION_PROPAGATION = "correction_propagation"
    CONTROLLED_EVALUATION = "controlled_evaluation"
    CORPUS_EXPORT = "corpus_export"


class Phase5RecoveryAction(str, Enum):
    REUSED_VALID = "reused_valid"
    RESUMED_MISSING = "resumed_missing"
    QUARANTINED_AND_REBUILT = "quarantined_and_rebuilt"
    INVALIDATED_AND_REBUILT = "invalidated_and_rebuilt"


class Phase5NegativeProofKind(str, Enum):
    UNSUPPORTED_PHASE4_FORMAT = "unsupported_phase4_format"
    MISSING_UTTERANCE_CORPUS = "missing_utterance_corpus"
    CORRUPTED_UTTERANCE_LINEAGE = "corrupted_utterance_lineage"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    MODEL_UNAVAILABLE = "model_unavailable"
    PROVIDER_TIMEOUT = "provider_timeout"
    MALFORMED_STRUCTURED_OUTPUT = "malformed_structured_output"
    UNSUPPORTED_ACT_TYPE = "unsupported_act_type"
    EVIDENCE_SPAN_OUTSIDE_UTTERANCE = "evidence_span_outside_utterance"
    INVALID_WORD_REFERENCE = "invalid_word_reference"
    CONFIDENCE_OUTSIDE_RANGE = "confidence_outside_allowed_range"
    ANSWER_UNKNOWN_QUESTION = "answer_linked_to_unknown_question"
    OBJECTION_UNKNOWN_TARGET = "objection_linked_to_unknown_target"
    REBUTTAL_CYCLE = "rebuttal_relation_cycle"
    CONCESSION_WITHOUT_CONTENT = "concession_without_content"
    QUALIFICATION_WITHOUT_SCOPE = "qualification_without_scope"
    DEFINITION_WITHOUT_TERM = "definition_without_term"
    QUOTATION_PHASE4_INCOMPATIBLE = "quotation_incompatible_with_phase4"
    IMPOSSIBLE_PROCEDURAL_TRANSITION = "impossible_procedural_transition"
    INCOMPATIBLE_SELECTED_ALTERNATIVES = (
        "incompatible_selected_alternatives"
    )
    STALE_REVIEW_ACTION = "stale_review_action"
    WRONG_VERSION_PROPAGATION = "propagation_from_wrong_utterance_version"
    MIXED_VERSION_EXPORT = "export_with_mixed_corpus_versions"
    UNSUPPORTED_SCHEMA_VERSION = "unsupported_schema_version"
    CORRUPTED_CACHE_ENTRY = "corrupted_cache_entry"


class Phase5RecoveryPolicy(Contract):
    policy_version: Literal["1.0.0"] = PHASE5_RECOVERY_POLICY_VERSION
    validate_before_reuse: Literal[True] = True
    invalid_cache_action: Literal["quarantine_and_rebuild"] = (
        "quarantine_and_rebuild"
    )
    incomplete_cache_action: Literal["resume_or_rebuild"] = "resume_or_rebuild"
    preserve_quarantine: Literal[True] = True
    downstream_only_invalidation: Literal[True] = True
    provider_reinvocation_when_valid: Literal[False] = False
    source_evidence_mutation: Literal["prohibited"] = "prohibited"


class Phase5RecoveryFingerprint(Contract):
    label: str = Field(min_length=1)
    content_sha256: Sha256


class Phase5RecoveryRecord(Contract):
    stage: Phase5RecoveryStage
    artifact_id: str = Field(min_length=1)
    action: Phase5RecoveryAction
    detected_failure: str | None = None
    quarantine_relative_path: str | None = None
    upstream_artifact_ids: tuple[str, ...] = ()
    provider_invoked: bool
    validated_after_recovery: Literal[True] = True

    @model_validator(mode="after")
    def action_is_coherent(self) -> "Phase5RecoveryRecord":
        quarantined = self.action in {
            Phase5RecoveryAction.QUARANTINED_AND_REBUILT,
            Phase5RecoveryAction.INVALIDATED_AND_REBUILT,
        }
        if quarantined != (self.quarantine_relative_path is not None):
            raise ValueError("quarantine path must match recovery action")
        if (
            self.action == Phase5RecoveryAction.REUSED_VALID
            and self.detected_failure is not None
        ):
            raise ValueError("valid reuse cannot claim a failure")
        return self


class Phase5NegativeProof(Contract):
    kind: Phase5NegativeProofKind
    passed: bool
    failure_type: str = Field(min_length=1)
    message: str = Field(min_length=1)
    typed_refusal: bool
    conservative_degradation: bool
    source_evidence_preserved: bool
    evidence_references: tuple[str, ...] = Field(min_length=1)


class Phase5RecoveryReport(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    report_id: str = Field(pattern=r"^phase5recovery_[a-f0-9]{32}$")
    generated_at: datetime
    policy: Phase5RecoveryPolicy
    records: tuple[Phase5RecoveryRecord, ...]
    protected_before: tuple[Phase5RecoveryFingerprint, ...]
    protected_after: tuple[Phase5RecoveryFingerprint, ...]
    interruption_boundaries: tuple[Phase5RecoveryStage, ...]
    negative_proofs: tuple[Phase5NegativeProof, ...]
    findings: tuple[str, ...]
    status: Literal["passed", "failed"]
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def inventory_is_complete(self) -> "Phase5RecoveryReport":
        stages = [item.stage for item in self.records]
        if set(stages) != set(Phase5RecoveryStage) or len(stages) != len(
            set(stages)
        ):
            raise ValueError("recovery requires every stage exactly once")
        proofs = [item.kind for item in self.negative_proofs]
        if set(proofs) != set(Phase5NegativeProofKind) or len(proofs) != len(
            set(proofs)
        ):
            raise ValueError("recovery requires every negative proof")
        if self.interruption_boundaries != tuple(Phase5RecoveryStage):
            raise ValueError("interruption boundary inventory is incomplete")
        if self.status == "passed" and (
            self.protected_before != self.protected_after
            or not all(item.passed for item in self.negative_proofs)
        ):
            raise ValueError("passing recovery report has failed evidence")
        return self


PHASE5_RECOVERY_CONTRACT_MODELS = (
    Phase5RecoveryPolicy,
    Phase5RecoveryFingerprint,
    Phase5RecoveryRecord,
    Phase5NegativeProof,
    Phase5RecoveryReport,
)
