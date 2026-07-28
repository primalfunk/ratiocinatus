"""Promote eligible voice comparisons into bounded acoustic hypotheses."""

from __future__ import annotations

from datetime import datetime

from .clustering_contracts import ClusteringRun
from .identity import (
    IdentityFoundationIntegrityError,
    add_identity_hypothesis,
)
from .identity_contracts import IdentityFoundationRun
from .kernel import typed_id
from .phase2_contracts import ConfidenceMeasure, ConfidenceOrigin
from .phase3_contracts import (
    DiarizationRun,
    IdentityHypothesis,
    IdentityHypothesisDisposition,
    IdentityHypothesisSource,
)
from .reference_comparison import ReferenceComparisonIntegrityError
from .reference_comparison_contracts import (
    CalibrationStatus,
    ReferenceComparisonRun,
    VoiceComparisonResult,
)
from .reference_comparison_validation import (
    validate_reference_comparison_run,
)
from .reference_enrollment_contracts import ReferenceEnrollmentRun


def _ordered_unique(values) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _acoustic_support(comparison) -> ConfidenceMeasure:
    policy = comparison.threshold_policy
    width = policy.score_maximum - policy.score_minimum
    normalized = (
        (comparison.score - policy.score_minimum) / width
        if comparison.score is not None and width > 0
        else 0.0
    )
    calibrated = comparison.calibration.status == CalibrationStatus.CALIBRATED
    calibration_id = (
        typed_id(
            "voicecalibration",
            comparison.calibration.model_dump(mode="json"),
            comparison.threshold_policy.model_dump(mode="json"),
        )
        if calibrated
        else None
    )
    return ConfidenceMeasure(
        value=max(0.0, min(1.0, normalized)),
        origin=ConfidenceOrigin.DERIVED,
        basis=(
            "Normalized within the comparison's declared score scale for the "
            f"{comparison.result.value} classification. This is acoustic "
            "support strength, not a probability of identity."
        ),
        calibrated=calibrated,
        calibration_id=calibration_id,
    )


def add_comparison_identity_hypothesis(
    predecessor: IdentityFoundationRun,
    clustering: ClusteringRun,
    diarization: DiarizationRun,
    enrollments: ReferenceEnrollmentRun,
    comparison_run: ReferenceComparisonRun,
    *,
    comparison_id: str,
    created_at: datetime | None = None,
) -> tuple[IdentityFoundationRun, IdentityHypothesis]:
    """Add positive comparison evidence without creating an identity binding."""

    validate_reference_comparison_run(
        comparison_run,
        clustering,
        diarization,
        predecessor,
        enrollments,
    )
    comparison = next(
        (
            item
            for item in comparison_run.comparisons
            if item.comparison_id == comparison_id
        ),
        None,
    )
    if comparison is None:
        raise ReferenceComparisonIntegrityError(
            "identity integration names unknown comparison evidence"
        )
    if comparison.result not in {
        VoiceComparisonResult.SUPPORTS_HYPOTHESIS,
        VoiceComparisonResult.WEAKLY_SUPPORTS_HYPOTHESIS,
    }:
        raise IdentityFoundationIntegrityError(
            "only positive valid comparison evidence can support a hypothesis"
        )
    identity = next(
        (
            item
            for item in predecessor.identities
            if item.identity_id == comparison.proposed_identity_id
        ),
        None,
    )
    if identity is None:
        raise IdentityFoundationIntegrityError(
            "comparison proposes an identity outside the foundation"
        )
    if comparison.target.target_artifact_id != identity.scope.target_id:
        raise IdentityFoundationIntegrityError(
            "comparison target differs from the bounded identity scope"
        )
    supporting = _ordered_unique(
        (
            comparison.comparison_id,
            comparison.reference_id,
            *comparison.supporting_evidence_references,
            *comparison.target.provenance_references,
        )
    )
    contrary = _ordered_unique(
        comparison.contrary_evidence_references
    )
    disposition = (
        IdentityHypothesisDisposition.SUPPORTED
        if comparison.result == VoiceComparisonResult.SUPPORTS_HYPOTHESIS
        else IdentityHypothesisDisposition.PROPOSED
    )
    return add_identity_hypothesis(
        predecessor,
        clustering,
        diarization,
        target_artifact_id=comparison.target.target_artifact_id,
        proposed_identity_id=comparison.proposed_identity_id,
        source=IdentityHypothesisSource.REFERENCE_VOICE_COMPARISON,
        scope=identity.scope,
        supporting_evidence_references=supporting,
        contrary_evidence_references=contrary,
        acoustic_support=_acoustic_support(comparison),
        verified_reference_comparison_id=comparison.comparison_id,
        creation_process=(
            "Verified reference-voice comparison integration; acoustic "
            "evidence only, with no automatic identity binding."
        ),
        disposition=disposition,
        created_at=created_at,
    )
