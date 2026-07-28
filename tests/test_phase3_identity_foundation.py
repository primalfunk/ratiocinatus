from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from ratiocinatus.clustering import cluster_diarization
from ratiocinatus.cli import EXIT_SUCCESS, main
from ratiocinatus.identity import (
    IdentityFoundationIntegrityError,
    add_identity_hypothesis,
    add_participant_identity,
    persist_identity_foundation,
    validate_identity_foundation,
)
from ratiocinatus.kernel import canonical_hash
from ratiocinatus.identity_contracts import (
    IDENTITY_CONTRACT_MODELS,
    IdentityConflictKind,
)
from ratiocinatus.phase2_contracts import (
    ConfidenceMeasure,
    ConfidenceOrigin,
)
from ratiocinatus.phase3_contracts import (
    IdentityHypothesisSource,
    IdentityKind,
    IdentityScope,
    IdentityScopeKind,
)

from test_phase3_clustering import (
    HAS_FFMPEG,
    ConflictedClusteringProvider,
    _prepare,
)

NOW = datetime(2000, 1, 1, tzinfo=timezone.utc)


def _support(value: float, basis: str) -> ConfidenceMeasure:
    return ConfidenceMeasure(
        value=value,
        origin=ConfidenceOrigin.DERIVED,
        basis=basis,
    )


def test_identity_foundation_contract_schemas_are_closed() -> None:
    assert len(IDENTITY_CONTRACT_MODELS) == 4
    for model in IDENTITY_CONTRACT_MODELS:
        schema = model.model_json_schema()
        assert schema["title"] == model.__name__
        assert schema.get("additionalProperties") is False


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_scoped_identity_foundation_is_separate_append_only_and_cached(
    tmp_path: Path,
) -> None:
    provider = ConflictedClusteringProvider()
    _, _, diarization, _, diarization_root, _ = _prepare(tmp_path, provider)
    clustering, _, clustering_root, _ = cluster_diarization(
        diarization_root,
        tmp_path / "clusters",
        capabilities=provider.capabilities,
    )
    cluster = clustering.clusters[0]
    scope = IdentityScope(
        kind=IdentityScopeKind.CLUSTER,
        target_id=cluster.cluster_id,
        explanation="Limited to one provisional cluster in this recording.",
    )
    first, identity_a = add_participant_identity(
        clustering,
        diarization,
        canonical_display_label="Local participant A",
        identity_kind=IdentityKind.LOCAL_PARTICIPANT,
        information_source="controlled fixture roster",
        scope=scope,
        provenance_references=("fixture:participants:a",),
        created_at=NOW,
    )
    stored = persist_identity_foundation(
        first, clustering, diarization, tmp_path / "identity"
    )
    assert not stored[-1]
    assert stored[1].identity_count == 1
    assert stored[1].status == "warning"
    assert identity_a.identity_id not in clustering.model_dump_json()
    cached = persist_identity_foundation(
        first, clustering, diarization, tmp_path / "identity"
    )
    assert cached[-1]

    cli_destination = tmp_path / "identity-cli"
    assert main(
        [
            "--json",
            "diarization",
            "identity-create",
            str(clustering_root),
            str(diarization_root),
            str(cli_destination),
            "--label",
            "CLI local participant",
            "--kind",
            "local_participant",
            "--information-source",
            "controlled CLI test",
            "--scope-kind",
            "cluster",
            "--scope-target",
            cluster.cluster_id,
            "--scope-explanation",
            "Limited to the controlled cluster.",
            "--provenance",
            "fixture:cli:participant",
        ]
    ) == EXIT_SUCCESS
    cli_root = next(
        (cli_destination / "identity-foundations").iterdir()
    )
    assert main(
        ["--json", "diarization", "identity-inspect", str(cli_root)]
    ) == EXIT_SUCCESS
    assert main(
        ["--json", "diarization", "identity-list", str(cli_root)]
    ) == EXIT_SUCCESS
    assert main(
        [
            "--json",
            "diarization",
            "identity-validate",
            str(cli_root),
            str(clustering_root),
            str(diarization_root),
        ]
    ) == EXIT_SUCCESS

    second, identity_b = add_participant_identity(
        clustering,
        diarization,
        canonical_display_label="Local participant B",
        identity_kind=IdentityKind.LOCAL_PARTICIPANT,
        information_source="controlled fixture roster",
        scope=scope,
        provenance_references=("fixture:participants:b",),
        predecessor=first,
        created_at=NOW,
    )
    assert second.predecessor_foundation_id == first.foundation_id
    assert second.identities[:1] == first.identities
    validate_identity_foundation(
        second, clustering, diarization, predecessor=first
    )
    assert identity_b.identity_id != identity_a.identity_id

    invalid_scope = IdentityScope(
        kind=IdentityScopeKind.CLUSTER,
        target_id="spkcluster_" + "f" * 32,
        explanation="Unknown cluster must be refused.",
    )
    with pytest.raises(
        IdentityFoundationIntegrityError, match="unknown cluster"
    ):
        add_participant_identity(
            clustering,
            diarization,
            canonical_display_label="Invalid identity",
            identity_kind=IdentityKind.LOCAL_PARTICIPANT,
            information_source="invalid test",
            scope=invalid_scope,
            provenance_references=("test:invalid",),
        )


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_competing_hypotheses_preserve_dimensions_and_remain_unresolved(
    tmp_path: Path,
) -> None:
    provider = ConflictedClusteringProvider()
    _, _, diarization, _, diarization_root, _ = _prepare(tmp_path, provider)
    clustering, _, clustering_root, _ = cluster_diarization(
        diarization_root,
        tmp_path / "clusters",
        capabilities=provider.capabilities,
    )
    cluster = clustering.clusters[0]
    scope = IdentityScope(
        kind=IdentityScopeKind.CLUSTER,
        target_id=cluster.cluster_id,
        explanation="Hypothesis is bounded to this cluster only.",
    )
    first, identity_a = add_participant_identity(
        clustering,
        diarization,
        canonical_display_label="Roster participant A",
        identity_kind=IdentityKind.NAMED_INDIVIDUAL,
        information_source="controlled event roster",
        scope=scope,
        provenance_references=("fixture:roster:a",),
        created_at=NOW,
    )
    second, identity_b = add_participant_identity(
        clustering,
        diarization,
        canonical_display_label="Roster participant B",
        identity_kind=IdentityKind.NAMED_INDIVIDUAL,
        information_source="controlled event roster",
        scope=scope,
        provenance_references=("fixture:roster:b",),
        predecessor=first,
        created_at=NOW,
    )
    third, hypothesis_a = add_identity_hypothesis(
        second,
        clustering,
        diarization,
        target_artifact_id=cluster.cluster_id,
        proposed_identity_id=identity_a.identity_id,
        source=IdentityHypothesisSource.TRUSTED_EVENT_METADATA,
        scope=scope,
        supporting_evidence_references=("fixture:roster:a",),
        documentary_support=_support(
            0.7, "Controlled roster association; not identity proof."
        ),
        creation_process="controlled metadata hypothesis test",
        created_at=NOW,
    )
    fourth, hypothesis_b = add_identity_hypothesis(
        third,
        clustering,
        diarization,
        target_artifact_id=cluster.cluster_id,
        proposed_identity_id=identity_b.identity_id,
        source=IdentityHypothesisSource.MODERATOR_INTRODUCTION,
        scope=scope,
        supporting_evidence_references=("fixture:transcript:introduction",),
        contrary_evidence_references=("fixture:roster:a",),
        contextual_support=_support(
            0.6, "Controlled introduction context; not acoustic support."
        ),
        creation_process="controlled competing hypothesis test",
        created_at=NOW,
    )

    assert hypothesis_a.acoustic_support.value is None
    assert hypothesis_a.documentary_support.value == 0.7
    assert hypothesis_b.contextual_support.value == 0.6
    assert hypothesis_b.manual_assertion_support.value is None
    assert hypothesis_b.competing_hypothesis_ids == (
        hypothesis_a.hypothesis_id,
    )
    assert fourth.conflicts[-1].kind == (
        IdentityConflictKind.COMPETING_HYPOTHESES
    )
    assert not fourth.conflicts[-1].resolved
    persisted = persist_identity_foundation(
        fourth,
        clustering,
        diarization,
        tmp_path / "identity",
        predecessor=third,
    )
    assert persisted[1].unresolved_conflict_count == 1
    assert persisted[1].status == "warning"

    cli_destination = tmp_path / "identity-hypothesis-cli"
    assert main(
        [
            "--json",
            "diarization",
            "identity-propose",
            str(persisted[2]),
            str(clustering_root),
            str(diarization_root),
            str(cli_destination),
            "--target",
            cluster.cluster_id,
            "--identity",
            identity_a.identity_id,
            "--source",
            "trusted_event_metadata",
            "--scope-kind",
            "cluster",
            "--scope-target",
            cluster.cluster_id,
            "--scope-explanation",
            "Limited to the controlled cluster.",
            "--supporting",
            "fixture:cli:hypothesis",
            "--creation-process",
            "controlled CLI hypothesis test",
        ]
    ) == EXIT_SUCCESS
    cli_successor = next(
        (cli_destination / "identity-foundations").iterdir()
    )
    assert main(
        [
            "--json",
            "diarization",
            "identity-list-hypotheses",
            str(cli_successor),
        ]
    ) == EXIT_SUCCESS
    assert main(
        [
            "--json",
            "diarization",
            "identity-list-conflicts",
            str(cli_successor),
        ]
    ) == EXIT_SUCCESS

    with pytest.raises(
        IdentityFoundationIntegrityError, match="verified acoustic comparison"
    ):
        add_identity_hypothesis(
            fourth,
            clustering,
            diarization,
            target_artifact_id=cluster.cluster_id,
            proposed_identity_id=identity_a.identity_id,
            source=IdentityHypothesisSource.REFERENCE_VOICE_COMPARISON,
            scope=scope,
            supporting_evidence_references=("comparison:not-yet-implemented",),
            creation_process="invalid premature comparison",
        )

    rewritten = third.model_copy(
        update={"identities": third.identities[1:]}
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
        IdentityFoundationIntegrityError, match="rewrites prior evidence"
    ):
        validate_identity_foundation(
            rewritten, clustering, diarization, predecessor=second
        )
