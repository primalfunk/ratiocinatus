"""Immutable compatible reference-voice comparison evidence."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .clustering import validate_clustering_run
from .clustering_contracts import ClusteringRun
from .identity_contracts import IdentityFoundationRun
from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase2_contracts import ConfidenceMeasure, ConfidenceOrigin
from .phase3_contracts import DiarizationRun, IdentityScopeKind
from .reference_comparison_contracts import (
    CalibrationStatus,
    ChannelCompatibility,
    ReferenceComparisonReport,
    ReferenceComparisonRun,
    ReferenceComparisonThresholdPolicy,
    ReferenceVoiceComparison,
    TargetVoiceRepresentation,
    VoiceCalibrationContext,
    VoiceComparisonResult,
    VoiceComparisonTargetKind,
)
from .reference_enrollment import validate_reference_enrollment
from .reference_enrollment_contracts import (
    ReferenceEnrollmentDisposition,
    ReferenceEnrollmentRun,
    ReferenceValidationResult,
)


class ReferenceComparisonIntegrityError(RuntimeError):
    """Voice comparison evidence has invalid scope, lineage, or semantics."""


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


def _unavailable_uncertainty() -> ConfidenceMeasure:
    return ConfidenceMeasure(
        origin=ConfidenceOrigin.UNAVAILABLE,
        basis=(
            "No calibrated comparison uncertainty was supplied; the score "
            "must not be interpreted as a probability of identity."
        ),
    )


def _classify(
    score: float,
    policy: ReferenceComparisonThresholdPolicy,
) -> VoiceComparisonResult:
    if score >= policy.support_minimum:
        return VoiceComparisonResult.SUPPORTS_HYPOTHESIS
    if score >= policy.weakly_support_minimum:
        return VoiceComparisonResult.WEAKLY_SUPPORTS_HYPOTHESIS
    if score <= policy.contradict_maximum:
        return VoiceComparisonResult.CONTRADICTS_HYPOTHESIS
    if score <= policy.weakly_contradict_maximum:
        return VoiceComparisonResult.WEAKLY_CONTRADICTS_HYPOTHESIS
    return VoiceComparisonResult.INCONCLUSIVE


def _target_exists(
    target: TargetVoiceRepresentation,
    clustering: ClusteringRun,
    diarization: DiarizationRun,
) -> bool:
    if target.target_kind == VoiceComparisonTargetKind.CLUSTER:
        return target.target_artifact_id in {
            item.cluster_id for item in clustering.clusters
        }
    return target.target_artifact_id in {
        item.observation_id for item in diarization.observations
    }


def _target_matches_identity_scope(
    target: TargetVoiceRepresentation,
    identity_id: str,
    foundation: IdentityFoundationRun,
    clustering: ClusteringRun,
    diarization: DiarizationRun,
) -> bool:
    identity = next(
        (item for item in foundation.identities if item.identity_id == identity_id),
        None,
    )
    if identity is None:
        return False
    scope = identity.scope
    if scope.kind == IdentityScopeKind.CLUSTER:
        return (
            target.target_kind == VoiceComparisonTargetKind.CLUSTER
            and target.target_artifact_id == scope.target_id
        )
    if scope.kind == IdentityScopeKind.OBSERVATION:
        return (
            target.target_kind == VoiceComparisonTargetKind.OBSERVATION
            and target.target_artifact_id == scope.target_id
        )
    if scope.kind == IdentityScopeKind.CORPUS:
        return scope.target_id == diarization.corpus_id
    if scope.kind == IdentityScopeKind.RECORDING:
        return scope.target_id == diarization.source_id
    return False


def compare_reference_voice(
    clustering: ClusteringRun,
    diarization: DiarizationRun,
    foundation: IdentityFoundationRun,
    enrollments: ReferenceEnrollmentRun,
    *,
    target: TargetVoiceRepresentation,
    reference_id: str,
    score: float | None,
    threshold_policy: ReferenceComparisonThresholdPolicy,
    calibration: VoiceCalibrationContext,
    comparison_provider: str,
    comparison_method: str,
    supporting_evidence_references: tuple[str, ...] = (),
    contrary_evidence_references: tuple[str, ...] = (),
    uncertainty: ConfidenceMeasure | None = None,
    created_at: datetime | None = None,
) -> tuple[ReferenceComparisonRun, ReferenceVoiceComparison]:
    validate_clustering_run(clustering, diarization)
    validate_reference_enrollment(enrollments, foundation)
    timestamp = created_at or datetime.now(timezone.utc)
    reference = next(
        (
            item
            for item in enrollments.enrollments
            if item.reference_id == reference_id
        ),
        None,
    )
    if reference is None:
        raise ReferenceComparisonIntegrityError(
            "voice comparison references unknown enrollment"
        )
    terminal = {
        item.reference_id for item in enrollments.lifecycle_events
    }
    invalid_reasons: list[str] = []
    if reference.reference_id in terminal:
        invalid_reasons.append(
            "Reference enrollment was revoked or replaced."
        )
    if reference.expires_at is not None and reference.expires_at <= timestamp:
        invalid_reasons.append("Reference enrollment has expired.")
    if (
        reference.disposition != ReferenceEnrollmentDisposition.ACCEPTED
        or reference.validation_result == ReferenceValidationResult.INVALID
    ):
        invalid_reasons.append("Reference enrollment is not eligible.")
    if not _target_exists(target, clustering, diarization):
        invalid_reasons.append("Comparison target is unknown.")
    if not _target_matches_identity_scope(
        target,
        reference.identity_id,
        foundation,
        clustering,
        diarization,
    ):
        invalid_reasons.append(
            "Comparison target is outside the identity scope."
        )
    compatible = (
        target.model_space_id == reference.model_space_id
        and target.model_fingerprint == reference.model_fingerprint
    )
    if not compatible:
        invalid_reasons.append(
            "Target and reference use incompatible model spaces."
        )
    if target.channel_compatibility == ChannelCompatibility.INCOMPATIBLE:
        invalid_reasons.append("Target and reference channels are incompatible.")
    if target.audio_quality.value == "unusable":
        invalid_reasons.append("Target voice evidence is unusable.")
    if score is None:
        invalid_reasons.append("Comparison provider supplied no score.")
    if score is not None and not (
        threshold_policy.score_minimum
        <= score
        <= threshold_policy.score_maximum
    ):
        invalid_reasons.append("Comparison score is outside its declared scale.")
        score = None

    result = (
        VoiceComparisonResult.COMPARISON_INVALID
        if invalid_reasons
        else _classify(score, threshold_policy)  # type: ignore[arg-type]
    )
    quality_findings = list(invalid_reasons)
    if target.audio_quality.value == "marginal":
        quality_findings.append("Target audio quality is marginal.")
    if reference.audio_quality.value == "marginal":
        quality_findings.append("Reference audio quality is marginal.")
    if target.overlap_present:
        quality_findings.append("Target evidence contains overlapping speech.")
    if target.channel_compatibility in {
        ChannelCompatibility.DEGRADED,
        ChannelCompatibility.UNKNOWN,
    }:
        quality_findings.append(
            "Target/reference channel compatibility is degraded or unknown."
        )
    limitations = [
        "A voice comparison score is not proof of real-world identity.",
        "The comparison cannot create an automatic identity binding.",
        "Scores from other model spaces or policies are not comparable.",
    ]
    if calibration.status == CalibrationStatus.UNAVAILABLE:
        limitations.append(
            "Calibration is unavailable; the score is not a probability and "
            "has no established error rate."
        )
    comparison_id = typed_id(
        "voicecomparison",
        clustering.run_id,
        enrollments.run_id,
        target.model_dump(mode="json"),
        reference.reference_id,
        score,
        threshold_policy.model_dump(mode="json"),
        calibration.model_dump(mode="json"),
    )
    comparison = _seal(
        ReferenceVoiceComparison,
        {
            "comparison_id": comparison_id,
            "clustering_run_id": clustering.run_id,
            "diarization_run_id": diarization.run_id,
            "enrollment_run_id": enrollments.run_id,
            "target": target,
            "reference_id": reference.reference_id,
            "proposed_identity_id": reference.identity_id,
            "comparison_provider": comparison_provider,
            "comparison_method": comparison_method,
            "compatible_model_space": compatible,
            "score": score,
            "threshold_policy": threshold_policy,
            "calibration": calibration,
            "reference_audio_quality": reference.audio_quality,
            "quality_findings": tuple(quality_findings),
            "supporting_evidence_references": (
                supporting_evidence_references
            ),
            "contrary_evidence_references": contrary_evidence_references,
            "uncertainty": uncertainty or _unavailable_uncertainty(),
            "result": result,
            "limitations": tuple(limitations),
            "created_at": timestamp,
        },
    )
    configuration_hash = canonical_hash(
        {
            "operation": "participant.reference_voice.comparison",
            "clustering_run_id": clustering.run_id,
            "diarization_run_id": diarization.run_id,
            "enrollment_run_id": enrollments.run_id,
            "threshold_policy": threshold_policy.model_dump(mode="json"),
            "calibration": calibration.model_dump(mode="json"),
            "comparison_provider": comparison_provider,
            "comparison_method": comparison_method,
        }
    )
    run = _seal(
        ReferenceComparisonRun,
        {
            "run_id": typed_id(
                "voicecomparisonrun",
                comparison.comparison_id,
                configuration_hash,
            ),
            "clustering_run_id": clustering.run_id,
            "diarization_run_id": diarization.run_id,
            "enrollment_run_id": enrollments.run_id,
            "identity_foundation_id": foundation.foundation_id,
            "comparisons": (comparison,),
            "configuration_hash": configuration_hash,
            "created_at": timestamp,
        },
    )
    from .reference_comparison_validation import (
        validate_reference_comparison_run,
    )
    validate_reference_comparison_run(
        run, clustering, diarization, foundation, enrollments
    )
    return run, comparison
