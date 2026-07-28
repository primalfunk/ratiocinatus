"""Phase 4 stage-local recovery and typed negative-proof contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract, Sha256
from .phase4_contracts import PHASE4_FORMAT_VERSION

PHASE4_RECOVERY_POLICY_VERSION = "1.0.0"


class Phase4RecoveryStage(str, Enum):
    INITIAL_ALIGNMENT = "initial_alignment"
    UTTERANCE_SEGMENTATION = "utterance_segmentation"
    COMPLETENESS_ANALYSIS = "completeness_analysis"
    TEMPORAL_RELATIONS = "temporal_relations"
    TURN_REPAIR = "turn_repair"
    QUOTATION = "quotation"
    ATTRIBUTED_TRANSCRIPT = "attributed_transcript"
    CONTEXT_WINDOWS = "context_windows"
    CORRECTION_PROPAGATION = "correction_propagation"
    CORPUS_EXPORT = "corpus_export"


class Phase4RecoveryAction(str, Enum):
    REUSED_VALID = "reused_valid"
    RESUMED_MISSING = "resumed_missing"
    QUARANTINED_AND_REBUILT = "quarantined_and_rebuilt"
    INVALIDATED_AND_REBUILT = "invalidated_and_rebuilt"


class Phase4NegativeProofKind(str, Enum):
    UNSUPPORTED_PRIOR_FORMAT = "unsupported_prior_phase_format"
    MISSING_TRANSCRIPT_VIEW = "missing_transcript_view"
    MISSING_IDENTITY_VIEW = "missing_identity_view"
    INCOMPATIBLE_LINEAGE = "incompatible_transcript_identity_lineage"
    CORRUPTED_SOURCE_MAPPING = "corrupted_source_mapping"
    DUPLICATE_WORD_OWNERSHIP = "duplicate_word_ownership"
    WORD_OUTSIDE_SOURCE = "transcript_word_outside_source_bounds"
    TURN_OUTSIDE_SOURCE = "speaker_turn_outside_source_bounds"
    COMPONENT_ORDER = "invalid_utterance_component_order"
    IMPOSSIBLE_INTERRUPTION = "impossible_interruption_relation"
    CONTINUATION_CYCLE = "continuation_cycle"
    INCOMPATIBLE_MERGE = "merge_incompatible_simultaneous_speakers"
    QUOTATION_OUTSIDE = "quotation_span_outside_utterance"
    QUOTED_ACOUSTIC_CONFLATION = "quoted_acoustic_speaker_conflation"
    INVALID_REPAIR_TARGET = "invalid_turn_repair_target"
    STALE_PROPAGATION = "stale_correction_propagation"
    UNKNOWN_REVIEW_TARGET = "manual_review_unknown_utterance"
    MIXED_CONTEXT_CORPUS = "context_window_mixed_corpus_versions"
    UNDISCLOSED_TRUNCATION = "undisclosed_context_truncation"
    UNSUPPORTED_SCHEMA = "unsupported_schema_version"
    OPTIONAL_ANALYZER_FAILURE = "optional_analyzer_failure"
    CORRUPTED_CACHE = "corrupted_cache_artifact"


class Phase4RecoveryPolicy(Contract):
    policy_version: Literal["1.0.0"] = PHASE4_RECOVERY_POLICY_VERSION
    validate_before_reuse: Literal[True] = True
    invalid_cache_action: Literal["quarantine_and_rebuild"] = (
        "quarantine_and_rebuild"
    )
    incomplete_cache_action: Literal["resume_or_rebuild"] = "resume_or_rebuild"
    preserve_quarantine: Literal[True] = True
    downstream_only_invalidation: Literal[True] = True
    optional_analyzer_failure_action: Literal["conservative_degradation"] = (
        "conservative_degradation"
    )
    source_evidence_mutation: Literal["prohibited"] = "prohibited"


class Phase4RecoveryFingerprint(Contract):
    label: str = Field(min_length=1)
    content_sha256: Sha256


class Phase4RecoveryRecord(Contract):
    stage: Phase4RecoveryStage
    artifact_id: str = Field(min_length=1)
    action: Phase4RecoveryAction
    detected_failure: str | None = None
    quarantine_relative_path: str | None = None
    upstream_artifact_ids: tuple[str, ...] = ()
    optional_analyzer_invoked: bool
    validated_after_recovery: Literal[True] = True

    @model_validator(mode="after")
    def action_is_coherent(self) -> "Phase4RecoveryRecord":
        quarantined = self.action in {
            Phase4RecoveryAction.QUARANTINED_AND_REBUILT,
            Phase4RecoveryAction.INVALIDATED_AND_REBUILT,
        }
        if quarantined != (self.quarantine_relative_path is not None):
            raise ValueError("quarantine path must match recovery action")
        if (
            self.action == Phase4RecoveryAction.REUSED_VALID
            and self.detected_failure is not None
        ):
            raise ValueError("valid cache reuse cannot claim a failure")
        return self


class Phase4NegativeProof(Contract):
    kind: Phase4NegativeProofKind
    passed: bool
    failure_type: str = Field(min_length=1)
    message: str = Field(min_length=1)
    typed_refusal: bool
    conservative_degradation: bool
    source_evidence_preserved: bool
    evidence_references: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def proof_pass_is_justified(self) -> "Phase4NegativeProof":
        justified = (
            (self.typed_refusal or self.conservative_degradation)
            and self.source_evidence_preserved
        )
        if self.passed != justified:
            raise ValueError("negative-proof status is not justified")
        return self


class Phase4RecoveryReport(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    report_id: str = Field(pattern=r"^phase4recovery_[a-f0-9]{32}$")
    generated_at: datetime
    policy: Phase4RecoveryPolicy
    records: tuple[Phase4RecoveryRecord, ...] = Field(min_length=1)
    protected_before: tuple[Phase4RecoveryFingerprint, ...]
    protected_after: tuple[Phase4RecoveryFingerprint, ...]
    interruption_boundaries: tuple[Phase4RecoveryStage, ...]
    negative_proofs: tuple[Phase4NegativeProof, ...]
    findings: tuple[str, ...]
    status: Literal["passed", "failed"]
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def recovery_evidence_is_complete(self) -> "Phase4RecoveryReport":
        if tuple(item.label for item in self.protected_before) != tuple(
            item.label for item in self.protected_after
        ):
            raise ValueError("protected recovery fingerprint labels disagree")
        if len(self.records) != len({item.stage for item in self.records}):
            raise ValueError("recovery stage records must be unique")
        proof_kinds = [item.kind for item in self.negative_proofs]
        if set(proof_kinds) != set(Phase4NegativeProofKind):
            raise ValueError("every required negative proof must be present")
        if len(proof_kinds) != len(set(proof_kinds)):
            raise ValueError("negative-proof kinds must be unique")
        passed = (
            all(item.passed for item in self.negative_proofs)
            and self.protected_before == self.protected_after
            and set(self.interruption_boundaries) == set(Phase4RecoveryStage)
        )
        if (self.status == "passed") != passed:
            raise ValueError("recovery status disagrees with evidence")
        return self


PHASE4_RECOVERY_CONTRACT_MODELS = (
    Phase4RecoveryPolicy,
    Phase4RecoveryFingerprint,
    Phase4RecoveryRecord,
    Phase4NegativeProof,
    Phase4RecoveryReport,
)
