"""Compatible, calibrated, and explicitly non-binding voice comparisons."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract, Sha256
from .phase2_contracts import ConfidenceMeasure
from .reference_enrollment_contracts import ReferenceAudioQuality

REFERENCE_COMPARISON_FORMAT_VERSION = "1.0.0"
REFERENCE_COMPARISON_POLICY_VERSION = "1.0.0"


class VoiceComparisonTargetKind(str, Enum):
    OBSERVATION = "observation"
    CLUSTER = "cluster"


class VoiceComparisonResult(str, Enum):
    SUPPORTS_HYPOTHESIS = "supports_hypothesis"
    WEAKLY_SUPPORTS_HYPOTHESIS = "weakly_supports_hypothesis"
    INCONCLUSIVE = "inconclusive"
    WEAKLY_CONTRADICTS_HYPOTHESIS = "weakly_contradicts_hypothesis"
    CONTRADICTS_HYPOTHESIS = "contradicts_hypothesis"
    COMPARISON_INVALID = "comparison_invalid"


class CalibrationStatus(str, Enum):
    CALIBRATED = "calibrated"
    COHORT_ONLY = "cohort_only"
    UNAVAILABLE = "unavailable"


class ChannelCompatibility(str, Enum):
    COMPATIBLE = "compatible"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"
    INCOMPATIBLE = "incompatible"


class ReferenceComparisonThresholdPolicy(Contract):
    policy_version: Literal["1.0.0"] = REFERENCE_COMPARISON_POLICY_VERSION
    score_minimum: float
    score_maximum: float
    contradict_maximum: float
    weakly_contradict_maximum: float
    weakly_support_minimum: float
    support_minimum: float
    higher_score_is_more_similar: Literal[True] = True
    automatic_identity_binding: Literal["prohibited"] = "prohibited"

    @model_validator(mode="after")
    def thresholds_are_strictly_ordered(
        self,
    ) -> "ReferenceComparisonThresholdPolicy":
        if not (
            self.score_minimum
            <= self.contradict_maximum
            < self.weakly_contradict_maximum
            < self.weakly_support_minimum
            < self.support_minimum
            <= self.score_maximum
        ):
            raise ValueError("reference comparison thresholds are not ordered")
        return self


class VoiceCalibrationContext(Contract):
    status: CalibrationStatus
    cohort_reference: str | None = None
    calibration_dataset_reference: str | None = None
    operating_point_reference: str | None = None
    estimated_false_accept_rate: float | None = Field(
        default=None, ge=0.0, le=1.0
    )
    estimated_false_reject_rate: float | None = Field(
        default=None, ge=0.0, le=1.0
    )
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def calibration_claim_has_evidence(self) -> "VoiceCalibrationContext":
        if self.status == CalibrationStatus.CALIBRATED and (
            self.calibration_dataset_reference is None
            or self.operating_point_reference is None
        ):
            raise ValueError(
                "calibrated comparison requires dataset and operating point"
            )
        if self.status == CalibrationStatus.COHORT_ONLY and (
            self.cohort_reference is None
        ):
            raise ValueError("cohort comparison requires a cohort reference")
        if self.status == CalibrationStatus.UNAVAILABLE and any(
            item is not None
            for item in (
                self.calibration_dataset_reference,
                self.operating_point_reference,
                self.estimated_false_accept_rate,
                self.estimated_false_reject_rate,
            )
        ):
            raise ValueError(
                "unavailable calibration cannot carry calibrated estimates"
            )
        return self


class TargetVoiceRepresentation(Contract):
    target_kind: VoiceComparisonTargetKind
    target_artifact_id: str
    representation_reference: str = Field(min_length=1)
    representation_sha256: Sha256
    model_space_id: str = Field(pattern=r"^[a-z][a-z0-9_.:-]+$")
    model_fingerprint: Sha256
    extraction_provider: str = Field(min_length=1)
    speech_duration_microseconds: int = Field(gt=0)
    audio_quality: ReferenceAudioQuality
    channel_compatibility: ChannelCompatibility
    overlap_present: bool
    provenance_references: tuple[str, ...] = Field(min_length=1)


class ReferenceVoiceComparison(Contract):
    format_version: Literal["1.0.0"] = REFERENCE_COMPARISON_FORMAT_VERSION
    comparison_id: str = Field(pattern=r"^voicecomparison_[a-f0-9]{32}$")
    clustering_run_id: str = Field(pattern=r"^clusterrun_[a-f0-9]{32}$")
    diarization_run_id: str = Field(pattern=r"^diarun_[a-f0-9]{32}$")
    enrollment_run_id: str = Field(pattern=r"^voicerefrun_[a-f0-9]{32}$")
    target: TargetVoiceRepresentation
    reference_id: str = Field(pattern=r"^voiceref_[a-f0-9]{32}$")
    proposed_identity_id: str = Field(pattern=r"^identity_[a-f0-9]{32}$")
    comparison_provider: str = Field(min_length=1)
    comparison_method: str = Field(min_length=1)
    compatible_model_space: bool
    score: float | None = None
    threshold_policy: ReferenceComparisonThresholdPolicy
    calibration: VoiceCalibrationContext
    reference_audio_quality: ReferenceAudioQuality
    quality_findings: tuple[str, ...]
    supporting_evidence_references: tuple[str, ...]
    contrary_evidence_references: tuple[str, ...]
    uncertainty: ConfidenceMeasure
    result: VoiceComparisonResult
    limitations: tuple[str, ...]
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def interpreted_scores_are_compatible(self) -> "ReferenceVoiceComparison":
        invalid = self.result == VoiceComparisonResult.COMPARISON_INVALID
        if not invalid and (
            not self.compatible_model_space or self.score is None
        ):
            raise ValueError(
                "interpreted comparison requires compatible scored evidence"
            )
        if self.score is not None and not (
            self.threshold_policy.score_minimum
            <= self.score
            <= self.threshold_policy.score_maximum
        ):
            raise ValueError("comparison score is outside its declared scale")
        return self


class ReferenceComparisonRun(Contract):
    format_version: Literal["1.0.0"] = REFERENCE_COMPARISON_FORMAT_VERSION
    run_id: str = Field(pattern=r"^voicecomparisonrun_[a-f0-9]{32}$")
    clustering_run_id: str = Field(pattern=r"^clusterrun_[a-f0-9]{32}$")
    diarization_run_id: str = Field(pattern=r"^diarun_[a-f0-9]{32}$")
    enrollment_run_id: str = Field(pattern=r"^voicerefrun_[a-f0-9]{32}$")
    identity_foundation_id: str = Field(
        pattern=r"^identityfoundation_[a-f0-9]{32}$"
    )
    comparisons: tuple[ReferenceVoiceComparison, ...] = Field(min_length=1)
    configuration_hash: Sha256
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def comparisons_are_unique(self) -> "ReferenceComparisonRun":
        identifiers = [item.comparison_id for item in self.comparisons]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("reference comparison identifiers must be unique")
        return self


class ReferenceComparisonReport(Contract):
    format_version: Literal["1.0.0"] = REFERENCE_COMPARISON_FORMAT_VERSION
    report_id: str = Field(pattern=r"^voicecomparisonreport_[a-f0-9]{32}$")
    run_id: str = Field(pattern=r"^voicecomparisonrun_[a-f0-9]{32}$")
    generated_at: datetime
    comparison_count: int = Field(ge=1)
    valid_comparison_count: int = Field(ge=0)
    invalid_comparison_count: int = Field(ge=0)
    calibrated_comparison_count: int = Field(ge=0)
    result_counts: dict[VoiceComparisonResult, int]
    findings: tuple[str, ...]
    limitations: tuple[str, ...]
    status: Literal["complete", "warning", "blocked"]
    integrity_sha256: Sha256


REFERENCE_COMPARISON_CONTRACT_MODELS = (
    ReferenceComparisonThresholdPolicy,
    VoiceCalibrationContext,
    TargetVoiceRepresentation,
    ReferenceVoiceComparison,
    ReferenceComparisonRun,
    ReferenceComparisonReport,
)
