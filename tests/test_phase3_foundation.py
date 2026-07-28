from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from ratiocinatus.addressing_contracts import MediaInterval, TimeDomain
from ratiocinatus.cli import EXIT_SUCCESS, main
from ratiocinatus.diarization_providers import (
    DiarizationProviderRegistry,
    DiarizationProviderUnavailable,
)
from ratiocinatus.phase2_contracts import (
    ConfidenceMeasure,
    ConfidenceOrigin,
    RawEvidenceDisposition,
    RawProviderEvidence,
)
from ratiocinatus.phase3_contracts import (
    BindingAction,
    ClusterStatus,
    DiarizationCapability,
    DiarizationFailureKind,
    DiarizationProviderCapabilities,
    DiarizationProviderIdentity,
    DiarizationProviderResponse,
    EmbeddingStorageDisposition,
    IdentityKind,
    IdentityScope,
    IdentityScopeKind,
    IdentityStatus,
    ManualIdentityBinding,
    ObservationUsability,
    PHASE3_CONTRACT_MODELS,
    ParticipantIdentity,
    ProviderSpeakerObservation,
    ProviderSpeakerTurn,
    SpeakerCluster,
    SpeakerEmbedding,
    SpeakerTurnKind,
    VoiceEmbeddingPolicy,
)

NOW = datetime(2000, 1, 1, tzinfo=timezone.utc)


def unavailable(basis: str = "provider supplied no score") -> ConfidenceMeasure:
    return ConfidenceMeasure(
        origin=ConfidenceOrigin.UNAVAILABLE,
        basis=basis,
    )


def provider() -> DiarizationProviderIdentity:
    return DiarizationProviderIdentity(
        provider_id="test.diarization",
        display_name="Test diarization boundary",
        provider_version="1.0.0",
        local=True,
    )


def observation() -> ProviderSpeakerObservation:
    return ProviderSpeakerObservation(
        observation_id="spkobs_" + "1" * 32,
        speech_interval_ids=("speech_" + "2" * 32,),
        source_interval=MediaInterval(
            domain=TimeDomain.SOURCE_MEDIA,
            start_microseconds=100,
            duration_microseconds=1_000_000,
        ),
        normalized_audio_interval=MediaInterval(
            domain=TimeDomain.NORMALIZED_CORPUS,
            start_microseconds=0,
            duration_microseconds=1_000_000,
        ),
        chunk_local_interval=MediaInterval(
            domain=TimeDomain.CHUNK_LOCAL,
            start_microseconds=0,
            duration_microseconds=1_000_000,
        ),
        processing_chunk_id="chunk_" + "3" * 32,
        provider_speaker_label="SPEAKER_00",
        acoustic_evidence_available=True,
        usability=ObservationUsability.PROVISIONAL,
        usability_confidence=unavailable(),
    )


def test_phase3_contract_schemas_are_closed() -> None:
    assert len(PHASE3_CONTRACT_MODELS) == 22
    for model in PHASE3_CONTRACT_MODELS:
        schema = model.model_json_schema()
        assert schema["title"] == model.__name__
        assert schema.get("additionalProperties") is False


def test_embedding_policy_defaults_private_and_requires_export_authority() -> None:
    policy = VoiceEmbeddingPolicy()
    assert not policy.portable_export
    assert not policy.log_embedding_values
    assert (
        policy.storage_disposition
        == EmbeddingStorageDisposition.PROTECTED_REFERENCE
    )
    with pytest.raises(ValidationError, match="explicit authorization"):
        VoiceEmbeddingPolicy(portable_export=True)
    with pytest.raises(ValidationError, match="invalid when export is disabled"):
        VoiceEmbeddingPolicy(export_authorization_reference="consent:1")

    embedding = SpeakerEmbedding(
        embedding_id="spkembed_" + "1" * 32,
        observation_id="spkobs_" + "2" * 32,
        model_space_id="test.embedding:v1",
        model_fingerprint="3" * 64,
        dimension_count=192,
        numeric_format="float32",
        extraction_interval=MediaInterval(
            domain=TimeDomain.NORMALIZED_CORPUS,
            start_microseconds=0,
            duration_microseconds=1_000_000,
        ),
        storage_disposition=EmbeddingStorageDisposition.OMITTED,
    )
    assert embedding.relative_path is None
    with pytest.raises(ValidationError, match="path, hash, and byte size"):
        embedding.model_validate(
            {
                **embedding.model_dump(),
                "storage_disposition": (
                    EmbeddingStorageDisposition.PROTECTED_REFERENCE
                ),
            }
        )


def test_provider_capabilities_do_not_imply_identity() -> None:
    capabilities = DiarizationProviderCapabilities(
        identity=provider(),
        capabilities=(DiarizationCapability.TURN_SEGMENTATION,),
        available=True,
    )
    assert "participant_identity" not in capabilities.model_dump()
    with pytest.raises(ValidationError, match="require clustering"):
        DiarizationProviderCapabilities(
            identity=provider(),
            capabilities=(DiarizationCapability.TURN_SEGMENTATION,),
            available=True,
            minimum_speaker_count=True,
        )


def test_speaker_observations_require_explicit_mapped_domains() -> None:
    item = observation()
    assert item.canonical_owner
    with pytest.raises(ValidationError, match="mapped durations disagree"):
        ProviderSpeakerObservation(
            **{
                **item.model_dump(),
                "chunk_local_interval": item.chunk_local_interval.model_copy(
                    update={"duration_microseconds": 500_000}
                ),
            }
        )
    with pytest.raises(
        ValidationError, match="unavailable acoustic evidence"
    ):
        ProviderSpeakerObservation(
            **{
                **item.model_dump(),
                "acoustic_evidence_available": False,
                "embedding_id": "spkembed_" + "4" * 32,
            }
        )


def test_provider_response_rejects_unknown_turn_lineage_and_failed_success() -> None:
    item = observation()
    turn = ProviderSpeakerTurn(
        provider_turn_id="turn-1",
        observation_ids=("spkobs_" + "9" * 32,),
        source_interval=item.source_interval,
        normalized_audio_interval=item.normalized_audio_interval,
        provider_speaker_label="SPEAKER_00",
        turn_kind=SpeakerTurnKind.SINGLE_SPEAKER,
        boundary_confidence=unavailable(),
        assignment_confidence=unavailable(),
    )
    kwargs = {
        "response_id": "diaresponse_" + "1" * 32,
        "request_id": "diareq_" + "2" * 32,
        "provider": provider(),
        "started_at": NOW,
        "completed_at": NOW,
        "observations": (item,),
        "turns": (turn,),
        "normalized_evidence_sha256": "0" * 64,
        "raw_evidence": RawProviderEvidence(
            disposition=RawEvidenceDisposition.UNAVAILABLE,
            explanation="unit test",
        ),
        "complete": True,
    }
    with pytest.raises(ValidationError, match="unknown observation"):
        DiarizationProviderResponse(**kwargs)
    with pytest.raises(ValidationError, match="requires no failure"):
        DiarizationProviderResponse(
            **{
                **kwargs,
                "turns": (),
                "failure": DiarizationFailureKind.TIMEOUT,
            }
        )


def test_cluster_identity_and_manual_binding_remain_separate() -> None:
    cluster = SpeakerCluster(
        cluster_id="spkcluster_" + "1" * 32,
        corpus_id="corpus_" + "2" * 32,
        membership_ids=("spkmember_" + "3" * 32,),
        observation_ids=("spkobs_" + "4" * 32,),
        formation_method="unit acoustic clustering",
        configuration_hash="5" * 64,
        status=ClusterStatus.PROVISIONAL,
        created_at=NOW,
        integrity_sha256="6" * 64,
    )
    assert "identity" not in cluster.model_dump()
    with pytest.raises(ValidationError, match="own predecessor"):
        SpeakerCluster(
            **{
                **cluster.model_dump(),
                "predecessor_cluster_ids": (cluster.cluster_id,),
            }
        )

    scope = IdentityScope(
        kind=IdentityScopeKind.CLUSTER,
        target_id=cluster.cluster_id,
        explanation="bounded to this cluster in this recording",
    )
    identity = ParticipantIdentity(
        identity_id="identity_" + "7" * 32,
        canonical_display_label="Unresolved local participant A",
        identity_kind=IdentityKind.LOCAL_PARTICIPANT,
        information_source="controlled fixture roster",
        scope=scope,
        status=IdentityStatus.PROVISIONAL,
        provenance_references=("fixture:speakers",),
        created_at=NOW,
    )
    assert identity.identity_id not in cluster.model_dump_json()
    with pytest.raises(ValidationError, match="availability disagree"):
        ManualIdentityBinding(
            binding_id="identitybind_" + "8" * 32,
            target_artifact_id=cluster.cluster_id,
            identity_id=identity.identity_id,
            scope=scope,
            action=BindingAction.MARK_UNKNOWN,
            author_id="reviewer-1",
            author_display_name="Controlled reviewer",
            bound_at=NOW,
            rationale="Evidence does not justify identity.",
            reviewer_certainty=unavailable(),
            resulting_identity_view_version_id="identityview_" + "9" * 32,
        )


def test_diarization_provider_registry_and_cli_are_conservative(capsys) -> None:
    registry = DiarizationProviderRegistry.with_boundaries()
    capabilities = registry.list()
    assert len(capabilities) == 1
    assert capabilities[0].identity.provider_id == "unconfigured.diarization"
    assert not capabilities[0].available
    with pytest.raises(DiarizationProviderUnavailable):
        registry.get("missing.provider")

    assert main(["--json", "diarization-provider", "list"]) == EXIT_SUCCESS
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["available"] is False
    assert payload[0]["identity"]["model_id"] is None

    assert main(
        [
            "--json",
            "diarization-provider",
            "inspect",
            "unconfigured.diarization",
        ]
    ) == EXIT_SUCCESS
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["capabilities"] == ["turn_segmentation"]
    assert main(
        ["--json", "diarization-provider", "inspect", "missing.provider"]
    ) == 4
    assert "diarization provider unavailable" in capsys.readouterr().err
