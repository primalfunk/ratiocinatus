"""Bounded reference-voice enrollment and lifecycle contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .addressing_contracts import MediaInterval, TimeDomain
from .contracts import Contract, Sha256
from .phase3_contracts import IdentityScope

REFERENCE_ENROLLMENT_FORMAT_VERSION = "1.0.0"
REFERENCE_ENROLLMENT_POLICY_VERSION = "1.0.0"


class ReferenceLicenseStatus(str, Enum):
    LICENSED = "licensed"
    PERMISSION_GRANTED = "permission_granted"
    PUBLIC_DOMAIN = "public_domain"
    RESTRICTED = "restricted"
    UNKNOWN = "unknown"


class ReferenceLawfulUseStatus(str, Enum):
    CONSENT_RECORDED = "consent_recorded"
    LAWFUL_BASIS_RECORDED = "lawful_basis_recorded"
    PENDING_REVIEW = "pending_review"
    NOT_RECORDED = "not_recorded"
    REVOKED = "revoked"


class ReferenceAudioQuality(str, Enum):
    ACCEPTABLE = "acceptable"
    MARGINAL = "marginal"
    UNUSABLE = "unusable"


class ReferenceContamination(str, Enum):
    CLEAN = "clean"
    POSSIBLE = "possible"
    CONTAMINATED = "contaminated"
    UNKNOWN = "unknown"


class ReferenceEnrollmentDisposition(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ReferenceValidationResult(str, Enum):
    VALID = "valid"
    WARNING = "warning"
    INVALID = "invalid"


class ReferenceLifecycleAction(str, Enum):
    REVOKED = "revoked"
    REPLACED = "replaced"


class ReferenceEnrollmentPolicy(Contract):
    policy_version: Literal["1.0.0"] = REFERENCE_ENROLLMENT_POLICY_VERSION
    minimum_speech_duration_microseconds: int = Field(
        default=2_000_000, gt=0
    )
    explicit_provenance_required: Literal[True] = True
    explicit_rights_basis_required: Literal[True] = True
    identity_binding_from_enrollment: Literal["prohibited"] = "prohibited"
    portable_embedding_values: Literal["prohibited"] = "prohibited"


class ReferenceVoiceEnrollment(Contract):
    format_version: Literal["1.0.0"] = REFERENCE_ENROLLMENT_FORMAT_VERSION
    reference_id: str = Field(pattern=r"^voiceref_[a-f0-9]{32}$")
    identity_id: str = Field(pattern=r"^identity_[a-f0-9]{32}$")
    identity_foundation_id: str = Field(
        pattern=r"^identityfoundation_[a-f0-9]{32}$"
    )
    source_reference: str = Field(min_length=1)
    license_status: ReferenceLicenseStatus
    lawful_use_status: ReferenceLawfulUseStatus
    rights_basis_reference: str = Field(min_length=1)
    recording_provenance_references: tuple[str, ...] = Field(min_length=1)
    source_interval: MediaInterval
    audio_quality: ReferenceAudioQuality
    speech_duration_microseconds: int = Field(gt=0)
    contamination: ReferenceContamination
    extraction_provider: str = Field(min_length=1)
    model_space_id: str = Field(pattern=r"^[a-z][a-z0-9_.:-]+$")
    model_fingerprint: Sha256
    representation_reference: str = Field(min_length=1)
    representation_sha256: Sha256
    enrollment_scope: IdentityScope
    expires_at: datetime | None = None
    replaces_reference_id: str | None = Field(
        default=None, pattern=r"^voiceref_[a-f0-9]{32}$"
    )
    disposition: ReferenceEnrollmentDisposition
    validation_result: ReferenceValidationResult
    validation_findings: tuple[str, ...]
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def interval_and_duration_are_bounded(self) -> "ReferenceVoiceEnrollment":
        if self.source_interval.domain != TimeDomain.SOURCE_MEDIA:
            raise ValueError("reference enrollment requires source-media time")
        if (
            self.speech_duration_microseconds
            > self.source_interval.duration_microseconds
        ):
            raise ValueError(
                "reference speech duration exceeds its source interval"
            )
        if self.replaces_reference_id == self.reference_id:
            raise ValueError("reference enrollment cannot replace itself")
        accepted = self.disposition == ReferenceEnrollmentDisposition.ACCEPTED
        usable = self.validation_result in {
            ReferenceValidationResult.VALID,
            ReferenceValidationResult.WARNING,
        }
        if accepted != usable:
            raise ValueError(
                "reference disposition and validation result disagree"
            )
        return self


class ReferenceLifecycleEvent(Contract):
    event_id: str = Field(pattern=r"^voicerefevent_[a-f0-9]{32}$")
    reference_id: str = Field(pattern=r"^voiceref_[a-f0-9]{32}$")
    action: ReferenceLifecycleAction
    replacement_reference_id: str | None = Field(
        default=None, pattern=r"^voiceref_[a-f0-9]{32}$"
    )
    authority_reference: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    occurred_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def replacement_is_explicit(self) -> "ReferenceLifecycleEvent":
        replacement = self.replacement_reference_id is not None
        if (self.action == ReferenceLifecycleAction.REPLACED) != replacement:
            raise ValueError(
                "replacement lifecycle event requires a replacement reference"
            )
        if self.replacement_reference_id == self.reference_id:
            raise ValueError("reference cannot be replaced by itself")
        return self


class ReferenceEnrollmentRun(Contract):
    format_version: Literal["1.0.0"] = REFERENCE_ENROLLMENT_FORMAT_VERSION
    run_id: str = Field(pattern=r"^voicerefrun_[a-f0-9]{32}$")
    predecessor_run_id: str | None = Field(
        default=None, pattern=r"^voicerefrun_[a-f0-9]{32}$"
    )
    identity_foundation_id: str = Field(
        pattern=r"^identityfoundation_[a-f0-9]{32}$"
    )
    identity_foundation_integrity_sha256: Sha256
    policy: ReferenceEnrollmentPolicy
    configuration_hash: Sha256
    enrollments: tuple[ReferenceVoiceEnrollment, ...]
    lifecycle_events: tuple[ReferenceLifecycleEvent, ...]
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def identifiers_are_unique(self) -> "ReferenceEnrollmentRun":
        reference_ids = [item.reference_id for item in self.enrollments]
        event_ids = [item.event_id for item in self.lifecycle_events]
        if len(reference_ids) != len(set(reference_ids)):
            raise ValueError("reference enrollment identifiers must be unique")
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("reference lifecycle event identifiers must be unique")
        if self.run_id == self.predecessor_run_id:
            raise ValueError("reference enrollment run cannot precede itself")
        return self


class ReferenceEnrollmentReport(Contract):
    format_version: Literal["1.0.0"] = REFERENCE_ENROLLMENT_FORMAT_VERSION
    report_id: str = Field(pattern=r"^voicerefreport_[a-f0-9]{32}$")
    run_id: str = Field(pattern=r"^voicerefrun_[a-f0-9]{32}$")
    identity_foundation_id: str = Field(
        pattern=r"^identityfoundation_[a-f0-9]{32}$"
    )
    generated_at: datetime
    enrollment_count: int = Field(ge=0)
    active_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    revoked_count: int = Field(ge=0)
    replaced_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    findings: tuple[str, ...]
    limitations: tuple[str, ...]
    status: Literal["complete", "warning", "blocked"]
    integrity_sha256: Sha256


REFERENCE_ENROLLMENT_CONTRACT_MODELS = (
    ReferenceEnrollmentPolicy,
    ReferenceVoiceEnrollment,
    ReferenceLifecycleEvent,
    ReferenceEnrollmentRun,
    ReferenceEnrollmentReport,
)
