"""Phase 3 stage-local cache, resume, and recovery evidence contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract, Sha256

PHASE3_RECOVERY_FORMAT_VERSION = "1.0.0"
PHASE3_RECOVERY_POLICY_VERSION = "1.0.0"


class Phase3RecoveryStage(str, Enum):
    DIARIZATION_PROVIDER_RESPONSE = "diarization_provider_response"
    DIARIZATION_NORMALIZED_OBSERVATIONS = "diarization_normalized_observations"
    SPEAKER_EMBEDDINGS = "speaker_embeddings"
    CLUSTERING = "clustering"
    REFERENCE_ENROLLMENTS = "reference_enrollments"
    REFERENCE_COMPARISONS = "reference_comparisons"
    IDENTITY_HYPOTHESES = "identity_hypotheses"
    IDENTITY_BINDINGS = "identity_bindings"
    IDENTITY_VIEWS = "identity_views"
    SPEAKER_TRANSCRIPT = "speaker_transcript"
    PARTICIPANT_SUBTITLES = "participant_subtitles"


class Phase3RecoveryAction(str, Enum):
    REUSED_VALID = "reused_valid"
    RESUMED_MISSING = "resumed_missing"
    QUARANTINED_AND_REBUILT = "quarantined_and_rebuilt"
    INVALIDATED_AND_REBUILT = "invalidated_and_rebuilt"


class Phase3RecoveryPolicy(Contract):
    policy_version: Literal["1.0.0"] = PHASE3_RECOVERY_POLICY_VERSION
    invalid_cache_action: Literal["quarantine_and_rebuild"] = (
        "quarantine_and_rebuild"
    )
    incomplete_cache_action: Literal["resume_or_rebuild"] = "resume_or_rebuild"
    validate_before_reuse: Literal[True] = True
    preserve_quarantine: Literal[True] = True
    downstream_only_invalidation: Literal[True] = True
    provider_reuse_preferred: Literal[True] = True


class Phase3RecoveryFingerprint(Contract):
    label: str = Field(min_length=1)
    content_sha256: Sha256


class Phase3InvalidationPlan(Contract):
    changed_stages: tuple[Phase3RecoveryStage, ...] = Field(min_length=1)
    invalidated_stages: tuple[Phase3RecoveryStage, ...]
    preserved_stages: tuple[Phase3RecoveryStage, ...]
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def stages_are_disjoint(self) -> "Phase3InvalidationPlan":
        changed = set(self.changed_stages)
        invalidated = set(self.invalidated_stages)
        preserved = set(self.preserved_stages)
        if changed & invalidated:
            raise ValueError("changed stages cannot also be downstream invalidations")
        if (changed | invalidated) & preserved:
            raise ValueError("preserved stages must be disjoint from affected stages")
        if (
            len(changed) != len(self.changed_stages)
            or len(invalidated) != len(self.invalidated_stages)
            or len(preserved) != len(self.preserved_stages)
        ):
            raise ValueError("recovery stage collections must be unique")
        return self


class Phase3RecoveryRecord(Contract):
    stage: Phase3RecoveryStage
    artifact_id: str = Field(min_length=1)
    action: Phase3RecoveryAction
    detected_failure: str | None = None
    quarantine_relative_path: str | None = None
    upstream_artifact_ids: tuple[str, ...] = ()
    provider_invoked: bool
    validated_after_recovery: Literal[True] = True

    @model_validator(mode="after")
    def action_is_consistent(self) -> "Phase3RecoveryRecord":
        quarantined = self.action in {
            Phase3RecoveryAction.QUARANTINED_AND_REBUILT,
            Phase3RecoveryAction.INVALIDATED_AND_REBUILT,
        }
        if quarantined != (self.quarantine_relative_path is not None):
            raise ValueError(
                "quarantine path must identify preserved invalidated evidence"
            )
        if (
            self.action == Phase3RecoveryAction.REUSED_VALID
            and self.detected_failure is not None
        ):
            raise ValueError("reused evidence cannot claim a failure")
        return self


class Phase3RecoveryReport(Contract):
    format_version: Literal["1.0.0"] = PHASE3_RECOVERY_FORMAT_VERSION
    report_id: str = Field(pattern=r"^phase3recovery_[a-f0-9]{32}$")
    generated_at: datetime
    policy: Phase3RecoveryPolicy
    records: tuple[Phase3RecoveryRecord, ...] = Field(min_length=1)
    invalidation_plans: tuple[Phase3InvalidationPlan, ...]
    protected_before: tuple[Phase3RecoveryFingerprint, ...]
    protected_after: tuple[Phase3RecoveryFingerprint, ...]
    interruption_boundaries: tuple[Phase3RecoveryStage, ...]
    negative_proofs: tuple[tuple[str, bool], ...]
    findings: tuple[str, ...]
    status: Literal["passed", "failed"]
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def evidence_is_consistent(self) -> "Phase3RecoveryReport":
        if tuple(item.label for item in self.protected_before) != tuple(
            item.label for item in self.protected_after
        ):
            raise ValueError("protected recovery fingerprint labels disagree")
        if len(self.records) != len({item.stage for item in self.records}):
            raise ValueError("a recovery report may record each stage only once")
        return self


PHASE3_RECOVERY_CONTRACT_MODELS = (
    Phase3RecoveryPolicy,
    Phase3RecoveryFingerprint,
    Phase3InvalidationPlan,
    Phase3RecoveryRecord,
    Phase3RecoveryReport,
)
