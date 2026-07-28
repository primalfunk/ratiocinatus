"""Creation, lifecycle, persistence, and reporting for voice references."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .addressing_contracts import MediaInterval
from .identity_contracts import IdentityFoundationRun
from .kernel import canonical_bytes, load_contract, typed_id
from .phase3_contracts import IdentityScope
from .reference_enrollment import (
    ReferenceEnrollmentIntegrityError,
    _atomic,
    _build_run,
    _seal,
    _validation_findings,
    _validate_foundation_identity,
    validate_reference_enrollment,
)
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


def enroll_reference_voice(
    foundation: IdentityFoundationRun,
    *,
    identity_id: str,
    source_reference: str,
    license_status: ReferenceLicenseStatus,
    lawful_use_status: ReferenceLawfulUseStatus,
    rights_basis_reference: str,
    recording_provenance_references: tuple[str, ...],
    source_interval: MediaInterval,
    audio_quality: ReferenceAudioQuality,
    speech_duration_microseconds: int,
    contamination: ReferenceContamination,
    extraction_provider: str,
    model_space_id: str,
    model_fingerprint: str,
    representation_reference: str,
    representation_sha256: str,
    enrollment_scope: IdentityScope,
    predecessor: ReferenceEnrollmentRun | None = None,
    replaces_reference_id: str | None = None,
    expires_at: datetime | None = None,
    policy: ReferenceEnrollmentPolicy | None = None,
    created_at: datetime | None = None,
) -> tuple[ReferenceEnrollmentRun, ReferenceVoiceEnrollment]:
    _validate_foundation_identity(foundation, identity_id)
    policy = policy or (
        predecessor.policy if predecessor else ReferenceEnrollmentPolicy()
    )
    if predecessor is not None:
        validate_reference_enrollment(predecessor, foundation)
    if not recording_provenance_references:
        raise ValueError("reference recording provenance is required")
    if replaces_reference_id is not None:
        replaced = (
            next(
                (
                    item
                    for item in predecessor.enrollments
                    if item.reference_id == replaces_reference_id
                ),
                None,
            )
            if predecessor
            else None
        )
        if replaced is None or replaced.identity_id != identity_id:
            raise ReferenceEnrollmentIntegrityError(
                "replacement reference is unknown or belongs to another identity"
            )
        if replaces_reference_id in {
            item.reference_id for item in predecessor.lifecycle_events
        }:
            raise ReferenceEnrollmentIntegrityError(
                "replacement reference is already terminal"
            )
    timestamp = created_at or datetime.now(timezone.utc)
    result, findings = _validation_findings(
        policy=policy,
        license_status=license_status,
        lawful_use_status=lawful_use_status,
        audio_quality=audio_quality,
        speech_duration_microseconds=speech_duration_microseconds,
        contamination=contamination,
    )
    if replaces_reference_id is not None and result == ReferenceValidationResult.INVALID:
        raise ReferenceEnrollmentIntegrityError(
            "replacement reference did not pass enrollment validation"
        )
    reference_id = typed_id(
        "voiceref",
        foundation.foundation_id,
        identity_id,
        source_reference,
        source_interval.model_dump(mode="json"),
        model_space_id,
        model_fingerprint,
        representation_sha256,
        replaces_reference_id,
    )
    existing = predecessor.enrollments if predecessor else ()
    if any(item.reference_id == reference_id for item in existing):
        raise ReferenceEnrollmentIntegrityError(
            "reference voice is already enrolled"
        )
    enrollment = _seal(
        ReferenceVoiceEnrollment,
        {
            "reference_id": reference_id,
            "identity_id": identity_id,
            "identity_foundation_id": foundation.foundation_id,
            "source_reference": source_reference,
            "license_status": license_status,
            "lawful_use_status": lawful_use_status,
            "rights_basis_reference": rights_basis_reference,
            "recording_provenance_references": recording_provenance_references,
            "source_interval": source_interval,
            "audio_quality": audio_quality,
            "speech_duration_microseconds": speech_duration_microseconds,
            "contamination": contamination,
            "extraction_provider": extraction_provider,
            "model_space_id": model_space_id,
            "model_fingerprint": model_fingerprint,
            "representation_reference": representation_reference,
            "representation_sha256": representation_sha256,
            "enrollment_scope": enrollment_scope,
            "expires_at": expires_at,
            "replaces_reference_id": replaces_reference_id,
            "disposition": (
                ReferenceEnrollmentDisposition.REJECTED
                if result == ReferenceValidationResult.INVALID
                else ReferenceEnrollmentDisposition.ACCEPTED
            ),
            "validation_result": result,
            "validation_findings": findings,
            "created_at": timestamp,
        },
    )
    events = predecessor.lifecycle_events if predecessor else ()
    if replaces_reference_id is not None:
        events = (
            *events,
            _seal(
                ReferenceLifecycleEvent,
                {
                    "event_id": typed_id(
                        "voicerefevent",
                        replaces_reference_id,
                        reference_id,
                        "replaced",
                    ),
                    "reference_id": replaces_reference_id,
                    "action": ReferenceLifecycleAction.REPLACED,
                    "replacement_reference_id": reference_id,
                    "authority_reference": rights_basis_reference,
                    "rationale": "Reference replaced by a validated successor.",
                    "occurred_at": timestamp,
                },
            ),
        )
    run = _build_run(
        foundation,
        predecessor=predecessor,
        enrollments=(*existing, enrollment),
        lifecycle_events=events,
        policy=policy,
        created_at=timestamp,
    )
    validate_reference_enrollment(run, foundation, predecessor=predecessor)
    return run, enrollment


def revoke_reference_voice(
    predecessor: ReferenceEnrollmentRun,
    foundation: IdentityFoundationRun,
    *,
    reference_id: str,
    authority_reference: str,
    rationale: str,
    occurred_at: datetime | None = None,
) -> tuple[ReferenceEnrollmentRun, ReferenceLifecycleEvent]:
    validate_reference_enrollment(predecessor, foundation)
    if reference_id not in {
        item.reference_id for item in predecessor.enrollments
    }:
        raise ReferenceEnrollmentIntegrityError(
            "revocation references unknown enrollment"
        )
    if reference_id in {
        item.reference_id for item in predecessor.lifecycle_events
    }:
        raise ReferenceEnrollmentIntegrityError(
            "reference enrollment is already terminal"
        )
    timestamp = occurred_at or datetime.now(timezone.utc)
    event = _seal(
        ReferenceLifecycleEvent,
        {
            "event_id": typed_id(
                "voicerefevent", reference_id, "revoked", authority_reference
            ),
            "reference_id": reference_id,
            "action": ReferenceLifecycleAction.REVOKED,
            "replacement_reference_id": None,
            "authority_reference": authority_reference,
            "rationale": rationale,
            "occurred_at": timestamp,
        },
    )
    run = _build_run(
        foundation,
        predecessor=predecessor,
        enrollments=predecessor.enrollments,
        lifecycle_events=(*predecessor.lifecycle_events, event),
        policy=predecessor.policy,
        created_at=timestamp,
    )
    validate_reference_enrollment(run, foundation, predecessor=predecessor)
    return run, event


def reference_enrollment_report(
    run: ReferenceEnrollmentRun,
) -> ReferenceEnrollmentReport:
    terminal = {
        item.reference_id: item.action for item in run.lifecycle_events
    }
    rejected = sum(
        item.disposition == ReferenceEnrollmentDisposition.REJECTED
        for item in run.enrollments
    )
    warnings = sum(
        item.validation_result == ReferenceValidationResult.WARNING
        for item in run.enrollments
    )
    findings = tuple(
        finding
        for item in run.enrollments
        for finding in item.validation_findings
        if item.validation_result != ReferenceValidationResult.VALID
    )
    return _seal(
        ReferenceEnrollmentReport,
        {
            "report_id": typed_id("voicerefreport", run.run_id),
            "run_id": run.run_id,
            "identity_foundation_id": run.identity_foundation_id,
            "generated_at": run.created_at,
            "enrollment_count": len(run.enrollments),
            "active_count": sum(
                item.disposition == ReferenceEnrollmentDisposition.ACCEPTED
                and item.reference_id not in terminal
                for item in run.enrollments
            ),
            "rejected_count": rejected,
            "revoked_count": sum(
                action == ReferenceLifecycleAction.REVOKED
                for action in terminal.values()
            ),
            "replaced_count": sum(
                action == ReferenceLifecycleAction.REPLACED
                for action in terminal.values()
            ),
            "warning_count": warnings,
            "findings": findings,
            "limitations": (
                "Enrollment validates bounded reference evidence only.",
                "Enrollment does not compare a voice or bind an identity.",
                "Representation values remain outside portable contracts.",
            ),
            "status": "warning" if rejected or warnings else "complete",
        },
    )


def persist_reference_enrollment(
    run: ReferenceEnrollmentRun,
    foundation: IdentityFoundationRun,
    destination: Path,
    *,
    predecessor: ReferenceEnrollmentRun | None = None,
) -> tuple[
    ReferenceEnrollmentRun, ReferenceEnrollmentReport, Path, bool
]:
    destination = destination.expanduser().resolve()
    validate_reference_enrollment(run, foundation, predecessor=predecessor)
    root = destination / "reference-enrollments" / run.run_id
    run_path = root / "enrollment.json"
    report_path = root / "report.json"
    existing = (run_path.exists(), report_path.exists())
    if any(existing) and not all(existing):
        raise ReferenceEnrollmentIntegrityError(
            "cached reference enrollment is incomplete"
        )
    expected_report = reference_enrollment_report(run)
    if all(existing):
        stored, report = load_reference_enrollment(root)
        validate_reference_enrollment(
            stored, foundation, predecessor=predecessor, report=report
        )
        if stored != run or report != expected_report:
            raise ReferenceEnrollmentIntegrityError(
                "cached reference enrollment is incompatible"
            )
        return stored, report, root, True
    _atomic(run_path, canonical_bytes(run))
    _atomic(report_path, canonical_bytes(expected_report))
    return run, expected_report, root, False


def load_reference_enrollment(
    root: Path,
) -> tuple[ReferenceEnrollmentRun, ReferenceEnrollmentReport]:
    root = root.expanduser().resolve(strict=True)
    return (
        load_contract(
            (root / "enrollment.json").read_bytes(),
            ReferenceEnrollmentRun,
        ),
        load_contract(
            (root / "report.json").read_bytes(),
            ReferenceEnrollmentReport,
        ),
    )
