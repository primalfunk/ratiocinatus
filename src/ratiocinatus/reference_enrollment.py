"""Append-only bounded reference-voice enrollment and validation."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .addressing_contracts import MediaInterval
from .identity_contracts import IdentityFoundationRun
from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase3_contracts import IdentityScope
from .reference_enrollment_contracts import (
    ReferenceAudioQuality,
    ReferenceContamination,
    ReferenceEnrollmentDisposition,
    ReferenceEnrollmentPolicy,
    ReferenceEnrollmentReport,
    ReferenceEnrollmentRun,
    ReferenceLawfulUseStatus,
    ReferenceLicenseStatus,
    ReferenceLifecycleAction,
    ReferenceLifecycleEvent,
    ReferenceValidationResult,
    ReferenceVoiceEnrollment,
)


class ReferenceEnrollmentIntegrityError(RuntimeError):
    """Reference enrollment violates lineage, rights, or lifecycle rules."""


def _atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.partial-{uuid.uuid4().hex}")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _seal(model, payload: dict):
    provisional = model(**payload, integrity_sha256="0" * 64)
    integrity = canonical_hash(
        provisional.model_dump(mode="json", exclude={"integrity_sha256"})
    )
    return model(**payload, integrity_sha256=integrity)


def _payload(item) -> dict:
    value = item.model_dump(mode="json")
    value.pop("integrity_sha256", None)
    return value


def _validate_foundation_identity(
    foundation: IdentityFoundationRun, identity_id: str
) -> None:
    if canonical_hash(_payload(foundation)) != foundation.integrity_sha256:
        raise ReferenceEnrollmentIntegrityError(
            "identity foundation integrity is invalid"
        )
    if identity_id not in {item.identity_id for item in foundation.identities}:
        raise ReferenceEnrollmentIntegrityError(
            "reference enrollment names an unknown identity"
        )


def _validation_findings(
    *,
    policy: ReferenceEnrollmentPolicy,
    license_status: ReferenceLicenseStatus,
    lawful_use_status: ReferenceLawfulUseStatus,
    audio_quality: ReferenceAudioQuality,
    speech_duration_microseconds: int,
    contamination: ReferenceContamination,
) -> tuple[ReferenceValidationResult, tuple[str, ...]]:
    invalid: list[str] = []
    warnings: list[str] = []
    if license_status in {
        ReferenceLicenseStatus.RESTRICTED,
        ReferenceLicenseStatus.UNKNOWN,
    }:
        invalid.append("Reference licensing does not authorize enrollment.")
    if lawful_use_status not in {
        ReferenceLawfulUseStatus.CONSENT_RECORDED,
        ReferenceLawfulUseStatus.LAWFUL_BASIS_RECORDED,
    }:
        invalid.append("Consent or another lawful-use basis is not recorded.")
    if audio_quality == ReferenceAudioQuality.UNUSABLE:
        invalid.append("Reference audio is unusable.")
    elif audio_quality == ReferenceAudioQuality.MARGINAL:
        warnings.append("Reference audio quality is marginal.")
    if speech_duration_microseconds < (
        policy.minimum_speech_duration_microseconds
    ):
        invalid.append("Reference speech is shorter than the policy minimum.")
    if contamination == ReferenceContamination.CONTAMINATED:
        invalid.append("Reference audio is contaminated.")
    elif contamination in {
        ReferenceContamination.POSSIBLE,
        ReferenceContamination.UNKNOWN,
    }:
        warnings.append("Reference contamination is not ruled out.")
    if invalid:
        return ReferenceValidationResult.INVALID, tuple((*invalid, *warnings))
    if warnings:
        return ReferenceValidationResult.WARNING, tuple(warnings)
    return ReferenceValidationResult.VALID, (
        "Reference provenance, rights, duration, quality, and contamination "
        "controls passed.",
    )


def _build_run(
    foundation: IdentityFoundationRun,
    *,
    predecessor: ReferenceEnrollmentRun | None,
    enrollments: tuple[ReferenceVoiceEnrollment, ...],
    lifecycle_events: tuple[ReferenceLifecycleEvent, ...],
    policy: ReferenceEnrollmentPolicy,
    created_at: datetime,
) -> ReferenceEnrollmentRun:
    configuration_hash = canonical_hash(
        {
            "operation": "participant.reference_voice.enrollment",
            "identity_foundation_id": foundation.foundation_id,
            "identity_foundation_integrity_sha256": foundation.integrity_sha256,
            "policy": policy.model_dump(mode="json"),
        }
    )
    run_id = typed_id(
        "voicerefrun",
        foundation.foundation_id,
        predecessor.run_id if predecessor else None,
        [item.model_dump(mode="json") for item in enrollments],
        [item.model_dump(mode="json") for item in lifecycle_events],
        configuration_hash,
    )
    return _seal(
        ReferenceEnrollmentRun,
        {
            "run_id": run_id,
            "predecessor_run_id": predecessor.run_id if predecessor else None,
            "identity_foundation_id": foundation.foundation_id,
            "identity_foundation_integrity_sha256": (
                foundation.integrity_sha256
            ),
            "policy": policy,
            "configuration_hash": configuration_hash,
            "enrollments": enrollments,
            "lifecycle_events": lifecycle_events,
            "created_at": created_at,
        },
    )


def validate_reference_enrollment(
    run: ReferenceEnrollmentRun,
    foundation: IdentityFoundationRun,
    *,
    predecessor: ReferenceEnrollmentRun | None = None,
    report: ReferenceEnrollmentReport | None = None,
) -> None:
    if canonical_hash(_payload(run)) != run.integrity_sha256:
        raise ReferenceEnrollmentIntegrityError(
            "reference enrollment run integrity is invalid"
        )
    if (
        run.identity_foundation_id != foundation.foundation_id
        or run.identity_foundation_integrity_sha256
        != foundation.integrity_sha256
    ):
        raise ReferenceEnrollmentIntegrityError(
            "reference enrollment identity lineage is incompatible"
        )
    references = {item.reference_id: item for item in run.enrollments}
    for enrollment in run.enrollments:
        _validate_foundation_identity(foundation, enrollment.identity_id)
        if canonical_hash(_payload(enrollment)) != enrollment.integrity_sha256:
            raise ReferenceEnrollmentIntegrityError(
                "reference enrollment integrity is invalid"
            )
        identity = next(
            item
            for item in foundation.identities
            if item.identity_id == enrollment.identity_id
        )
        if (
            enrollment.identity_foundation_id != foundation.foundation_id
            or enrollment.enrollment_scope != identity.scope
        ):
            raise ReferenceEnrollmentIntegrityError(
                "reference enrollment scope is incompatible"
            )
        if enrollment.replaces_reference_id is not None:
            replaced = references.get(enrollment.replaces_reference_id)
            if replaced is None or replaced.identity_id != enrollment.identity_id:
                raise ReferenceEnrollmentIntegrityError(
                    "replacement references unknown or different identity evidence"
                )
    for event in run.lifecycle_events:
        if canonical_hash(_payload(event)) != event.integrity_sha256:
            raise ReferenceEnrollmentIntegrityError(
                "reference lifecycle integrity is invalid"
            )
        if event.reference_id not in references:
            raise ReferenceEnrollmentIntegrityError(
                "reference lifecycle event names unknown evidence"
            )
        if (
            event.replacement_reference_id is not None
            and (
                event.replacement_reference_id not in references
                or references[
                    event.replacement_reference_id
                ].replaces_reference_id
                != event.reference_id
            )
        ):
            raise ReferenceEnrollmentIntegrityError(
                "replacement lifecycle lineage is invalid"
            )
    terminal = [item.reference_id for item in run.lifecycle_events]
    if len(terminal) != len(set(terminal)):
        raise ReferenceEnrollmentIntegrityError(
            "reference has multiple terminal lifecycle events"
        )
    if predecessor is not None:
        validate_reference_enrollment(predecessor, foundation)
        if run.predecessor_run_id != predecessor.run_id:
            raise ReferenceEnrollmentIntegrityError(
                "reference enrollment predecessor lineage is invalid"
            )
        if (
            run.enrollments[: len(predecessor.enrollments)]
            != predecessor.enrollments
            or run.lifecycle_events[: len(predecessor.lifecycle_events)]
            != predecessor.lifecycle_events
        ):
            raise ReferenceEnrollmentIntegrityError(
                "reference enrollment successor rewrites prior evidence"
            )
    if report is not None:
        from .reference_enrollment_operations import (
            reference_enrollment_report,
        )
        invalid_report = (
            canonical_hash(_payload(report)) != report.integrity_sha256
            or report.run_id != run.run_id
            or report.identity_foundation_id != foundation.foundation_id
            or report != reference_enrollment_report(run)
        )
    else:
        invalid_report = False
    if invalid_report:
        raise ReferenceEnrollmentIntegrityError(
            "reference enrollment report integrity or lineage is invalid"
        )
