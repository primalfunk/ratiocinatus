"""Phase 2 cache quarantine and recovery evidence contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract, Sha256

RECOVERY_FORMAT_VERSION = "1.0.0"
RECOVERY_POLICY_VERSION = "1.0.0"


class Phase2RecoveryStage(str, Enum):
    SPEECH_ACTIVITY = "speech_activity"
    TRANSCRIPTION_RESPONSE = "transcription_response"
    TRANSCRIPTION_REPORT = "transcription_report"
    TRANSCRIPT_ASSEMBLY = "transcript_assembly"
    TRANSCRIPT_CORRECTION = "transcript_correction"
    SUBTITLE_EXPORT = "subtitle_export"
    TRANSCRIPT_EVALUATION = "transcript_evaluation"


class RecoveryAction(str, Enum):
    REUSED_VALID = "reused_valid"
    RESUMED_MISSING = "resumed_missing"
    REPAIRED_WITHOUT_PROVIDER = "repaired_without_provider"
    QUARANTINED_AND_REBUILT = "quarantined_and_rebuilt"
    REFUSED = "refused"


class Phase2RecoveryPolicy(Contract):
    policy_version: Literal["1.0.0"] = RECOVERY_POLICY_VERSION
    invalid_cache_action: Literal["quarantine_and_rebuild"] = (
        "quarantine_and_rebuild"
    )
    incomplete_cache_action: Literal["resume_or_rebuild"] = (
        "resume_or_rebuild"
    )
    preserve_quarantine: Literal[True] = True
    validate_before_reuse: Literal[True] = True
    downstream_only_invalidation: Literal[True] = True


class RecoveryArtifactFingerprint(Contract):
    label: str = Field(min_length=1)
    content_sha256: Sha256


class Phase2RecoveryRecord(Contract):
    stage: Phase2RecoveryStage
    artifact_id: str = Field(min_length=1)
    action: RecoveryAction
    detected_failure: str | None = None
    quarantine_relative_path: str | None = None
    upstream_artifact_ids: tuple[str, ...] = ()
    provider_invoked: bool
    validated_after_recovery: bool

    @model_validator(mode="after")
    def action_is_consistent(self) -> "Phase2RecoveryRecord":
        quarantined = self.action in {
            RecoveryAction.QUARANTINED_AND_REBUILT,
            RecoveryAction.REPAIRED_WITHOUT_PROVIDER,
        }
        if quarantined != (self.quarantine_relative_path is not None):
            raise ValueError(
                "quarantine path must match a recovery that preserved invalid output"
            )
        if self.action == RecoveryAction.REUSED_VALID and (
            self.detected_failure is not None
        ):
            raise ValueError("reused artifact cannot claim a failure")
        if self.action == RecoveryAction.REFUSED and self.validated_after_recovery:
            raise ValueError("refused recovery cannot validate successfully")
        return self


class Phase2RecoveryReport(Contract):
    format_version: Literal["1.0.0"] = RECOVERY_FORMAT_VERSION
    report_id: str = Field(pattern=r"^phase2recovery_[a-f0-9]{32}$")
    generated_at: datetime
    policy: Phase2RecoveryPolicy
    records: tuple[Phase2RecoveryRecord, ...] = Field(min_length=1)
    protected_before: tuple[RecoveryArtifactFingerprint, ...]
    protected_after: tuple[RecoveryArtifactFingerprint, ...]
    interruption_boundaries: tuple[Phase2RecoveryStage, ...]
    negative_proofs: tuple[tuple[str, bool], ...]
    findings: tuple[str, ...]
    status: Literal["passed", "failed"]
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def protected_artifacts_are_stable(self) -> "Phase2RecoveryReport":
        if tuple(item.label for item in self.protected_before) != tuple(
            item.label for item in self.protected_after
        ):
            raise ValueError("protected recovery fingerprint labels disagree")
        return self


RECOVERY_CONTRACT_MODELS = (
    Phase2RecoveryPolicy,
    RecoveryArtifactFingerprint,
    Phase2RecoveryRecord,
    Phase2RecoveryReport,
)
