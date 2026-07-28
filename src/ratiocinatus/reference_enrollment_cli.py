"""CLI integration for bounded reference-voice enrollment."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .addressing_contracts import MediaInterval, TimeDomain
from .identity import load_identity_foundation
from .phase3_contracts import IdentityScope, IdentityScopeKind
from .reference_enrollment import validate_reference_enrollment
from .reference_enrollment_contracts import (
    ReferenceAudioQuality,
    ReferenceContamination,
    ReferenceLawfulUseStatus,
    ReferenceLicenseStatus,
)
from .reference_enrollment_operations import (
    enroll_reference_voice,
    load_reference_enrollment,
    persist_reference_enrollment,
    revoke_reference_voice,
)

REFERENCE_ACTIONS = {
    "reference-enroll",
    "reference-revoke",
    "reference-inspect",
    "reference-validate",
    "reference-list",
    "reference-history",
}


def add_reference_enrollment_parsers(diasub) -> None:
    enroll = diasub.add_parser("reference-enroll")
    enroll.add_argument("foundation_root", type=Path)
    enroll.add_argument("destination", type=Path)
    enroll.add_argument("--predecessor", type=Path)
    enroll.add_argument("--replaces")
    enroll.add_argument("--identity", required=True)
    enroll.add_argument("--source", required=True)
    enroll.add_argument("--license-status", required=True)
    enroll.add_argument("--lawful-use-status", required=True)
    enroll.add_argument("--rights-basis", required=True)
    enroll.add_argument("--provenance", action="append", required=True)
    enroll.add_argument("--source-start-us", type=int, required=True)
    enroll.add_argument("--source-duration-us", type=int, required=True)
    enroll.add_argument("--speech-duration-us", type=int, required=True)
    enroll.add_argument("--audio-quality", required=True)
    enroll.add_argument("--contamination", required=True)
    enroll.add_argument("--extraction-provider", required=True)
    enroll.add_argument("--model-space", required=True)
    enroll.add_argument("--model-fingerprint", required=True)
    enroll.add_argument("--representation-reference", required=True)
    enroll.add_argument("--representation-sha256", required=True)
    enroll.add_argument("--scope-kind", required=True)
    enroll.add_argument("--scope-target", required=True)
    enroll.add_argument("--scope-explanation", required=True)
    enroll.add_argument("--expires-at", type=datetime.fromisoformat)

    revoke = diasub.add_parser("reference-revoke")
    revoke.add_argument("enrollment_root", type=Path)
    revoke.add_argument("foundation_root", type=Path)
    revoke.add_argument("destination", type=Path)
    revoke.add_argument("--reference", required=True)
    revoke.add_argument("--authority", required=True)
    revoke.add_argument("--rationale", required=True)

    validate = diasub.add_parser("reference-validate")
    validate.add_argument("enrollment_root", type=Path)
    validate.add_argument("foundation_root", type=Path)
    validate.add_argument("--predecessor", type=Path)

    for action in (
        "reference-inspect",
        "reference-list",
        "reference-history",
    ):
        parser = diasub.add_parser(action)
        parser.add_argument("enrollment_root", type=Path)


def run_reference_enrollment_command(args, emit, structured: bool):
    if args.action not in REFERENCE_ACTIONS:
        return None
    if args.action in {
        "reference-inspect",
        "reference-list",
        "reference-history",
    }:
        run, report = load_reference_enrollment(args.enrollment_root)
        if args.action == "reference-list":
            emit(run.enrollments, structured)
        elif args.action == "reference-history":
            emit(run.lifecycle_events, structured)
        else:
            emit(
                {
                    "enrollment": run.model_dump(mode="json"),
                    "report": report.model_dump(mode="json"),
                },
                structured,
            )
        return 0

    foundation, _ = load_identity_foundation(args.foundation_root)
    if args.action == "reference-validate":
        run, report = load_reference_enrollment(args.enrollment_root)
        predecessor = (
            load_reference_enrollment(args.predecessor)[0]
            if args.predecessor
            else None
        )
        validate_reference_enrollment(
            run, foundation, predecessor=predecessor, report=report
        )
        emit(
            {
                "valid": True,
                "run_id": run.run_id,
                "report_id": report.report_id,
            },
            structured,
        )
        return 0

    destination = args.destination.expanduser().resolve()
    if args.action == "reference-revoke":
        predecessor, _ = load_reference_enrollment(args.enrollment_root)
        run, event = revoke_reference_voice(
            predecessor,
            foundation,
            reference_id=args.reference,
            authority_reference=args.authority,
            rationale=args.rationale,
        )
        persisted = persist_reference_enrollment(
            run, foundation, destination, predecessor=predecessor
        )
        emit(
            {
                "event": event.model_dump(mode="json"),
                "run": persisted[0].model_dump(mode="json"),
                "report": persisted[1].model_dump(mode="json"),
                "enrollment_root": str(persisted[2]),
                "reused": persisted[3],
            },
            structured,
        )
        return 0

    predecessor = (
        load_reference_enrollment(args.predecessor)[0]
        if args.predecessor
        else None
    )
    scope = IdentityScope(
        kind=IdentityScopeKind(args.scope_kind),
        target_id=args.scope_target,
        explanation=args.scope_explanation,
    )
    run, enrollment = enroll_reference_voice(
        foundation,
        identity_id=args.identity,
        source_reference=args.source,
        license_status=ReferenceLicenseStatus(args.license_status),
        lawful_use_status=ReferenceLawfulUseStatus(args.lawful_use_status),
        rights_basis_reference=args.rights_basis,
        recording_provenance_references=tuple(args.provenance),
        source_interval=MediaInterval(
            domain=TimeDomain.SOURCE_MEDIA,
            start_microseconds=args.source_start_us,
            duration_microseconds=args.source_duration_us,
        ),
        audio_quality=ReferenceAudioQuality(args.audio_quality),
        speech_duration_microseconds=args.speech_duration_us,
        contamination=ReferenceContamination(args.contamination),
        extraction_provider=args.extraction_provider,
        model_space_id=args.model_space,
        model_fingerprint=args.model_fingerprint,
        representation_reference=args.representation_reference,
        representation_sha256=args.representation_sha256,
        enrollment_scope=scope,
        predecessor=predecessor,
        replaces_reference_id=args.replaces,
        expires_at=args.expires_at,
    )
    persisted = persist_reference_enrollment(
        run, foundation, destination, predecessor=predecessor
    )
    emit(
        {
            "reference": enrollment.model_dump(mode="json"),
            "run": persisted[0].model_dump(mode="json"),
            "report": persisted[1].model_dump(mode="json"),
            "enrollment_root": str(persisted[2]),
            "reused": persisted[3],
        },
        structured,
    )
    return 0
