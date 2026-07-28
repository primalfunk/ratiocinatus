"""Validation, reports, and persistence for voice-comparison evidence."""

from __future__ import annotations

from pathlib import Path

from .clustering import validate_clustering_run
from .clustering_contracts import ClusteringRun
from .identity_contracts import IdentityFoundationRun
from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase3_contracts import DiarizationRun
from .reference_comparison import (
    ReferenceComparisonIntegrityError,
    _atomic,
    _classify,
    _payload,
    _seal,
    _target_exists,
    _target_matches_identity_scope,
)
from .reference_comparison_contracts import (
    CalibrationStatus,
    ReferenceComparisonReport,
    ReferenceComparisonRun,
    VoiceComparisonResult,
)
from .reference_enrollment import validate_reference_enrollment
from .reference_enrollment_contracts import (
    ReferenceEnrollmentDisposition,
    ReferenceEnrollmentRun,
    ReferenceValidationResult,
)


def validate_reference_comparison_run(
    run: ReferenceComparisonRun,
    clustering: ClusteringRun,
    diarization: DiarizationRun,
    foundation: IdentityFoundationRun,
    enrollments: ReferenceEnrollmentRun,
    *,
    report: ReferenceComparisonReport | None = None,
) -> None:
    if canonical_hash(_payload(run)) != run.integrity_sha256:
        raise ReferenceComparisonIntegrityError(
            "reference comparison run integrity is invalid"
        )
    validate_clustering_run(clustering, diarization)
    validate_reference_enrollment(enrollments, foundation)
    if (
        run.clustering_run_id != clustering.run_id
        or run.diarization_run_id != diarization.run_id
        or run.enrollment_run_id != enrollments.run_id
        or run.identity_foundation_id != foundation.foundation_id
    ):
        raise ReferenceComparisonIntegrityError(
            "reference comparison lineage is incompatible"
        )
    references = {
        item.reference_id: item for item in enrollments.enrollments
    }
    terminal = {
        item.reference_id for item in enrollments.lifecycle_events
    }
    for comparison in run.comparisons:
        if canonical_hash(_payload(comparison)) != comparison.integrity_sha256:
            raise ReferenceComparisonIntegrityError(
                "reference comparison integrity is invalid"
            )
        if (
            comparison.clustering_run_id != run.clustering_run_id
            or comparison.diarization_run_id != run.diarization_run_id
            or comparison.enrollment_run_id != run.enrollment_run_id
        ):
            raise ReferenceComparisonIntegrityError(
                "reference comparison artifact lineage is incompatible"
            )
        reference = references.get(comparison.reference_id)
        if (
            reference is None
            or comparison.proposed_identity_id != reference.identity_id
        ):
            raise ReferenceComparisonIntegrityError(
                "reference comparison names unknown enrollment evidence"
            )
        if not _target_exists(
            comparison.target, clustering, diarization
        ):
            raise ReferenceComparisonIntegrityError(
                "reference comparison target is unknown"
            )
        if not _target_matches_identity_scope(
            comparison.target,
            reference.identity_id,
            foundation,
            clustering,
            diarization,
        ):
            raise ReferenceComparisonIntegrityError(
                "reference comparison target exceeds identity scope"
            )
        compatible = (
            comparison.target.model_space_id == reference.model_space_id
            and comparison.target.model_fingerprint
            == reference.model_fingerprint
        )
        if compatible != comparison.compatible_model_space:
            raise ReferenceComparisonIntegrityError(
                "reference comparison compatibility marker is false"
            )
        inactive = (
            reference.reference_id in terminal
            or reference.disposition
            != ReferenceEnrollmentDisposition.ACCEPTED
            or reference.validation_result
            == ReferenceValidationResult.INVALID
            or (
                reference.expires_at is not None
                and reference.expires_at <= comparison.created_at
            )
        )
        invalid = (
            comparison.result == VoiceComparisonResult.COMPARISON_INVALID
        )
        if (inactive or not compatible) and not invalid:
            raise ReferenceComparisonIntegrityError(
                "ineligible evidence was interpreted as a valid comparison"
            )
        if not invalid and comparison.result != _classify(
            comparison.score, comparison.threshold_policy  # type: ignore[arg-type]
        ):
            raise ReferenceComparisonIntegrityError(
                "reference comparison result disagrees with threshold policy"
            )
        if (
            comparison.calibration.status == CalibrationStatus.UNAVAILABLE
            and not any(
                "Calibration is unavailable" in item
                for item in comparison.limitations
            )
        ):
            raise ReferenceComparisonIntegrityError(
                "uncalibrated comparison omits its limitation"
            )
    if report is not None and (
        canonical_hash(_payload(report)) != report.integrity_sha256
        or report.run_id != run.run_id
        or report != reference_comparison_report(run)
    ):
        raise ReferenceComparisonIntegrityError(
            "reference comparison report integrity or lineage is invalid"
        )


def reference_comparison_report(
    run: ReferenceComparisonRun,
) -> ReferenceComparisonReport:
    counts = {
        result: sum(item.result == result for item in run.comparisons)
        for result in VoiceComparisonResult
    }
    invalid = counts[VoiceComparisonResult.COMPARISON_INVALID]
    calibrated = sum(
        item.calibration.status == CalibrationStatus.CALIBRATED
        for item in run.comparisons
    )
    uncalibrated = sum(
        item.calibration.status == CalibrationStatus.UNAVAILABLE
        for item in run.comparisons
    )
    findings = []
    if invalid:
        findings.append(f"{invalid} comparison(s) were invalid.")
    if uncalibrated:
        findings.append(
            f"{uncalibrated} comparison(s) have no calibration context."
        )
    status = (
        "blocked"
        if invalid == len(run.comparisons)
        else "warning"
        if invalid or uncalibrated
        else "complete"
    )
    return _seal(
        ReferenceComparisonReport,
        {
            "report_id": typed_id("voicecomparisonreport", run.run_id),
            "run_id": run.run_id,
            "generated_at": run.created_at,
            "comparison_count": len(run.comparisons),
            "valid_comparison_count": len(run.comparisons) - invalid,
            "invalid_comparison_count": invalid,
            "calibrated_comparison_count": calibrated,
            "result_counts": counts,
            "findings": tuple(findings),
            "limitations": (
                "Comparison classifications are identity-hypothesis evidence.",
                "No comparison creates or confirms an identity binding.",
                "Scores are comparable only within one declared model space, "
                "method, scale, threshold policy, and calibration context.",
            ),
            "status": status,
        },
    )


def persist_reference_comparison(
    run: ReferenceComparisonRun,
    clustering: ClusteringRun,
    diarization: DiarizationRun,
    foundation: IdentityFoundationRun,
    enrollments: ReferenceEnrollmentRun,
    destination: Path,
) -> tuple[ReferenceComparisonRun, ReferenceComparisonReport, Path, bool]:
    destination = destination.expanduser().resolve()
    validate_reference_comparison_run(
        run, clustering, diarization, foundation, enrollments
    )
    root = destination / "reference-comparisons" / run.run_id
    run_path = root / "comparison.json"
    report_path = root / "report.json"
    existing = (run_path.exists(), report_path.exists())
    if any(existing) and not all(existing):
        raise ReferenceComparisonIntegrityError(
            "cached reference comparison is incomplete"
        )
    expected_report = reference_comparison_report(run)
    if all(existing):
        stored, report = load_reference_comparison(root)
        validate_reference_comparison_run(
            stored,
            clustering,
            diarization,
            foundation,
            enrollments,
            report=report,
        )
        if stored != run or report != expected_report:
            raise ReferenceComparisonIntegrityError(
                "cached reference comparison is incompatible"
            )
        return stored, report, root, True
    _atomic(run_path, canonical_bytes(run))
    _atomic(report_path, canonical_bytes(expected_report))
    return run, expected_report, root, False


def load_reference_comparison(
    root: Path,
) -> tuple[ReferenceComparisonRun, ReferenceComparisonReport]:
    root = root.expanduser().resolve(strict=True)
    return (
        load_contract(
            (root / "comparison.json").read_bytes(),
            ReferenceComparisonRun,
        ),
        load_contract(
            (root / "report.json").read_bytes(),
            ReferenceComparisonReport,
        ),
    )
