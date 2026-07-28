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
from ratiocinatus.reference_enrollment import (
    ReferenceEnrollmentIntegrityError,
    validate_reference_enrollment,
)
from ratiocinatus.reference_enrollment_contracts import (
    REFERENCE_ENROLLMENT_CONTRACT_MODELS,
    ReferenceAudioQuality,
    ReferenceContamination,
    ReferenceEnrollmentDisposition,
    ReferenceLawfulUseStatus,
    ReferenceLicenseStatus,
    ReferenceLifecycleAction,
    ReferenceValidationResult,
)
from ratiocinatus.reference_enrollment_operations import (
    enroll_reference_voice,
    persist_reference_enrollment,
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


def test_reference_enrollment_contract_schemas_are_closed() -> None:
    assert len(REFERENCE_ENROLLMENT_CONTRACT_MODELS) == 5
    for model in REFERENCE_ENROLLMENT_CONTRACT_MODELS:
        schema = model.model_json_schema()
        assert schema["title"] == model.__name__
        assert schema.get("additionalProperties") is False


def _foundation(tmp_path: Path):
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
        explanation="Reference enrollment is bounded to this cluster.",
    )
    foundation, identity = add_participant_identity(
        clustering,
        diarization,
        canonical_display_label="Controlled reference participant",
        identity_kind=IdentityKind.NAMED_INDIVIDUAL,
        information_source="controlled fixture roster",
        scope=scope,
        provenance_references=("fixture:roster:reference",),
        created_at=NOW,
    )
    return foundation, identity, scope


def _enroll(foundation, identity, scope, **changes):
    values = {
        "identity_id": identity.identity_id,
        "source_reference": "fixture:reference:voice-a",
        "license_status": ReferenceLicenseStatus.PERMISSION_GRANTED,
        "lawful_use_status": ReferenceLawfulUseStatus.CONSENT_RECORDED,
        "rights_basis_reference": "fixture:consent:voice-a",
        "recording_provenance_references": ("fixture:recording:voice-a",),
        "source_interval": MediaInterval(
            domain=TimeDomain.SOURCE_MEDIA,
            start_microseconds=0,
            duration_microseconds=5_000_000,
        ),
        "audio_quality": ReferenceAudioQuality.ACCEPTABLE,
        "speech_duration_microseconds": 4_000_000,
        "contamination": ReferenceContamination.CLEAN,
        "extraction_provider": "controlled.reference.extractor/1",
        "model_space_id": "controlled.voice.v1",
        "model_fingerprint": HASH_A,
        "representation_reference": "protected:voice-a.embedding",
        "representation_sha256": HASH_B,
        "enrollment_scope": scope,
        "created_at": NOW,
    }
    values.update(changes)
    return enroll_reference_voice(foundation, **values)


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_reference_enrollment_is_bounded_validated_and_cached(
    tmp_path: Path,
) -> None:
    foundation, identity, scope = _foundation(tmp_path)
    run, reference = _enroll(foundation, identity, scope)
    assert reference.disposition == ReferenceEnrollmentDisposition.ACCEPTED
    assert reference.validation_result == ReferenceValidationResult.VALID
    assert identity.canonical_display_label not in reference.reference_id
    assert "embedding" not in reference.model_dump_json().casefold().replace(
        "protected:voice-a.embedding", ""
    )
    stored = persist_reference_enrollment(
        run, foundation, tmp_path / "references"
    )
    assert not stored[-1]
    assert stored[1].active_count == 1
    assert stored[1].status == "complete"
    cached = persist_reference_enrollment(
        run, foundation, tmp_path / "references"
    )
    assert cached[-1]


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_rejected_revoked_and_replaced_references_preserve_history(
    tmp_path: Path,
) -> None:
    foundation, identity, scope = _foundation(tmp_path)
    rejected_run, rejected = _enroll(
        foundation,
        identity,
        scope,
        license_status=ReferenceLicenseStatus.UNKNOWN,
        lawful_use_status=ReferenceLawfulUseStatus.NOT_RECORDED,
        audio_quality=ReferenceAudioQuality.UNUSABLE,
        contamination=ReferenceContamination.CONTAMINATED,
        speech_duration_microseconds=1_000_000,
    )
    assert rejected.disposition == ReferenceEnrollmentDisposition.REJECTED
    assert rejected.validation_result == ReferenceValidationResult.INVALID

    accepted_run, accepted = _enroll(
        foundation,
        identity,
        scope,
        predecessor=rejected_run,
        source_reference="fixture:reference:voice-b",
        representation_sha256=HASH_A,
    )
    replaced_run, replacement = _enroll(
        foundation,
        identity,
        scope,
        predecessor=accepted_run,
        replaces_reference_id=accepted.reference_id,
        source_reference="fixture:reference:voice-c",
        representation_sha256=canonical_hash("voice-c"),
    )
    assert replaced_run.enrollments[:2] == accepted_run.enrollments
    assert replaced_run.lifecycle_events[-1].action == (
        ReferenceLifecycleAction.REPLACED
    )
    assert replacement.replaces_reference_id == accepted.reference_id

    revoked_run, event = revoke_reference_voice(
        replaced_run,
        foundation,
        reference_id=replacement.reference_id,
        authority_reference="fixture:consent:revocation",
        rationale="Participant revoked the controlled reference.",
        occurred_at=NOW,
    )
    assert event.action == ReferenceLifecycleAction.REVOKED
    assert revoked_run.enrollments == replaced_run.enrollments
    validate_reference_enrollment(
        revoked_run, foundation, predecessor=replaced_run
    )

    rewritten = revoked_run.model_copy(
        update={"enrollments": revoked_run.enrollments[1:]}
    )
    rewritten = rewritten.model_copy(
        update={
            "integrity_sha256": canonical_hash(
                rewritten.model_dump(
                    mode="json", exclude={"integrity_sha256"}
                )
            )
        }
    )
    with pytest.raises(
        ReferenceEnrollmentIntegrityError, match="rewrites prior evidence"
    ):
        validate_reference_enrollment(
            rewritten, foundation, predecessor=replaced_run
        )
