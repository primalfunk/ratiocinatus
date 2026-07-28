from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from ratiocinatus.addressing_contracts import MediaInterval, TimeDomain
from ratiocinatus.clustering import cluster_diarization
from ratiocinatus.identity import add_participant_identity
from ratiocinatus.kernel import canonical_hash
from ratiocinatus.phase3_contracts import (
    IdentityKind,
    IdentityScope,
    IdentityScopeKind,
)
from ratiocinatus.reference_comparison import compare_reference_voice
from ratiocinatus.reference_comparison_contracts import (
    REFERENCE_COMPARISON_CONTRACT_MODELS,
    CalibrationStatus,
    ChannelCompatibility,
    ReferenceComparisonThresholdPolicy,
    TargetVoiceRepresentation,
    VoiceCalibrationContext,
    VoiceComparisonResult,
    VoiceComparisonTargetKind,
)
from ratiocinatus.reference_comparison_validation import (
    persist_reference_comparison,
    validate_reference_comparison_run,
)
from ratiocinatus.reference_enrollment_contracts import (
    ReferenceAudioQuality,
    ReferenceContamination,
    ReferenceLawfulUseStatus,
    ReferenceLicenseStatus,
)
from ratiocinatus.reference_enrollment_operations import (
    enroll_reference_voice,
    revoke_reference_voice,
)

from test_phase3_clustering import (
    HAS_FFMPEG,
    ConflictedClusteringProvider,
    _prepare,
)

NOW = datetime(2000, 1, 1, tzinfo=timezone.utc)
HASH_A = "a" * 64
HASH_B = "b" * 64


def test_reference_comparison_contract_schemas_are_closed() -> None:
    assert len(REFERENCE_COMPARISON_CONTRACT_MODELS) == 6
    for model in REFERENCE_COMPARISON_CONTRACT_MODELS:
        schema = model.model_json_schema()
        assert schema["title"] == model.__name__
        assert schema.get("additionalProperties") is False


def _setup(tmp_path: Path):
    provider = ConflictedClusteringProvider()
    _, _, diarization, _, diarization_root, _ = _prepare(tmp_path, provider)
    clustering, _, _, _ = cluster_diarization(
        diarization_root,
        tmp_path / "clusters",
        capabilities=provider.capabilities,
    )
    cluster = clustering.clusters[0]
    scope = IdentityScope(
        kind=IdentityScopeKind.CLUSTER,
        target_id=cluster.cluster_id,
        explanation="Comparison is bounded to one controlled cluster.",
    )
    foundation, identity = add_participant_identity(
        clustering,
        diarization,
        canonical_display_label="Controlled comparison participant",
        identity_kind=IdentityKind.NAMED_INDIVIDUAL,
        information_source="controlled comparison roster",
        scope=scope,
        provenance_references=("fixture:comparison:identity",),
        created_at=NOW,
    )
    enrollments, reference = enroll_reference_voice(
        foundation,
        identity_id=identity.identity_id,
        source_reference="fixture:comparison:reference",
        license_status=ReferenceLicenseStatus.PERMISSION_GRANTED,
        lawful_use_status=ReferenceLawfulUseStatus.CONSENT_RECORDED,
        rights_basis_reference="fixture:comparison:consent",
        recording_provenance_references=("fixture:comparison:recording",),
        source_interval=MediaInterval(
            domain=TimeDomain.SOURCE_MEDIA,
            start_microseconds=0,
            duration_microseconds=5_000_000,
        ),
        audio_quality=ReferenceAudioQuality.ACCEPTABLE,
        speech_duration_microseconds=4_000_000,
        contamination=ReferenceContamination.CLEAN,
        extraction_provider="controlled.reference.extractor/1",
        model_space_id="controlled.voice.v1",
        model_fingerprint=HASH_A,
        representation_reference="protected:comparison-reference.embedding",
        representation_sha256=HASH_B,
        enrollment_scope=scope,
        created_at=NOW,
    )
    target = TargetVoiceRepresentation(
        target_kind=VoiceComparisonTargetKind.CLUSTER,
        target_artifact_id=cluster.cluster_id,
        representation_reference="protected:comparison-target.embedding",
        representation_sha256=HASH_A,
        model_space_id="controlled.voice.v1",
        model_fingerprint=HASH_A,
        extraction_provider="controlled.target.extractor/1",
        speech_duration_microseconds=6_000_000,
        audio_quality=ReferenceAudioQuality.ACCEPTABLE,
        channel_compatibility=ChannelCompatibility.COMPATIBLE,
        overlap_present=False,
        provenance_references=("fixture:comparison:target",),
    )
    return (
        clustering,
        diarization,
        foundation,
        enrollments,
        reference,
        target,
    )


def _policy() -> ReferenceComparisonThresholdPolicy:
    return ReferenceComparisonThresholdPolicy(
        score_minimum=0.0,
        score_maximum=1.0,
        contradict_maximum=0.20,
        weakly_contradict_maximum=0.35,
        weakly_support_minimum=0.65,
        support_minimum=0.80,
    )


def _uncalibrated() -> VoiceCalibrationContext:
    return VoiceCalibrationContext(
        status=CalibrationStatus.UNAVAILABLE,
        limitations=("Controlled score has no population calibration.",),
    )


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_compatible_comparison_is_classified_nonbinding_and_cached(
    tmp_path: Path,
) -> None:
    (
        clustering,
        diarization,
        foundation,
        enrollments,
        reference,
        target,
    ) = _setup(tmp_path)
    run, comparison = compare_reference_voice(
        clustering,
        diarization,
        foundation,
        enrollments,
        target=target,
        reference_id=reference.reference_id,
        score=0.90,
        threshold_policy=_policy(),
        calibration=_uncalibrated(),
        comparison_provider="controlled.score.provider/1",
        comparison_method="controlled cosine-like score",
        supporting_evidence_references=("fixture:score:0.90",),
        created_at=NOW,
    )
    assert comparison.result == VoiceComparisonResult.SUPPORTS_HYPOTHESIS
    assert comparison.compatible_model_space
    assert comparison.proposed_identity_id == reference.identity_id
    assert "binding" in " ".join(comparison.limitations).casefold()
    assert comparison.uncertainty.value is None
    stored = persist_reference_comparison(
        run,
        clustering,
        diarization,
        foundation,
        enrollments,
        tmp_path / "comparisons",
    )
    assert not stored[-1]
    assert stored[1].valid_comparison_count == 1
    assert stored[1].status == "warning"
    cached = persist_reference_comparison(
        run,
        clustering,
        diarization,
        foundation,
        enrollments,
        tmp_path / "comparisons",
    )
    assert cached[-1]


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_threshold_classes_and_ineligible_evidence_remain_explicit(
    tmp_path: Path,
) -> None:
    (
        clustering,
        diarization,
        foundation,
        enrollments,
        reference,
        target,
    ) = _setup(tmp_path)
    expected = {
        0.90: VoiceComparisonResult.SUPPORTS_HYPOTHESIS,
        0.70: VoiceComparisonResult.WEAKLY_SUPPORTS_HYPOTHESIS,
        0.50: VoiceComparisonResult.INCONCLUSIVE,
        0.30: VoiceComparisonResult.WEAKLY_CONTRADICTS_HYPOTHESIS,
        0.10: VoiceComparisonResult.CONTRADICTS_HYPOTHESIS,
    }
    for score, result in expected.items():
        _, comparison = compare_reference_voice(
            clustering,
            diarization,
            foundation,
            enrollments,
            target=target,
            reference_id=reference.reference_id,
            score=score,
            threshold_policy=_policy(),
            calibration=_uncalibrated(),
            comparison_provider="controlled.score.provider/1",
            comparison_method="controlled cosine-like score",
            created_at=NOW,
        )
        assert comparison.result == result

    incompatible = target.model_copy(
        update={"model_fingerprint": canonical_hash("incompatible")}
    )
    invalid_run, invalid = compare_reference_voice(
        clustering,
        diarization,
        foundation,
        enrollments,
        target=incompatible,
        reference_id=reference.reference_id,
        score=0.99,
        threshold_policy=_policy(),
        calibration=_uncalibrated(),
        comparison_provider="controlled.score.provider/1",
        comparison_method="controlled incompatible score",
        created_at=NOW,
    )
    assert invalid.result == VoiceComparisonResult.COMPARISON_INVALID
    assert not invalid.compatible_model_space
    validate_reference_comparison_run(
        invalid_run,
        clustering,
        diarization,
        foundation,
        enrollments,
    )

    revoked, _ = revoke_reference_voice(
        enrollments,
        foundation,
        reference_id=reference.reference_id,
        authority_reference="fixture:comparison:revocation",
        rationale="Controlled reference was revoked.",
        occurred_at=NOW,
    )
    _, revoked_comparison = compare_reference_voice(
        clustering,
        diarization,
        foundation,
        revoked,
        target=target,
        reference_id=reference.reference_id,
        score=0.99,
        threshold_policy=_policy(),
        calibration=_uncalibrated(),
        comparison_provider="controlled.score.provider/1",
        comparison_method="controlled revoked score",
        created_at=NOW,
    )
    assert revoked_comparison.result == (
        VoiceComparisonResult.COMPARISON_INVALID
    )
