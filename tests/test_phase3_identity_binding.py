from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from ratiocinatus.clustering import cluster_diarization
from ratiocinatus.cli import EXIT_SUCCESS, main
from ratiocinatus.identity import (
    add_participant_identity,
    persist_identity_foundation,
)
from ratiocinatus.identity_binding import (
    IdentityBindingIntegrityError,
    active_bindings,
    append_manual_identity_binding,
    persist_identity_binding_run,
)
from ratiocinatus.identity_binding_contracts import (
    IDENTITY_BINDING_CONTRACT_MODELS,
)
from ratiocinatus.phase2_contracts import ConfidenceMeasure, ConfidenceOrigin
from ratiocinatus.phase3_contracts import (
    BindingAction,
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


def _certainty(value: float = 0.8) -> ConfidenceMeasure:
    return ConfidenceMeasure(
        value=value,
        origin=ConfidenceOrigin.DERIVED,
        basis="Reviewer supplied certainty; it is not model calibration.",
    )


def _binding(run_data, **overrides):
    foundation, clustering, diarization, scope, identities = run_data
    kwargs = {
        "target_artifact_id": scope.target_id,
        "identity_id": identities[0].identity_id,
        "scope": scope,
        "action": BindingAction.BIND,
        "author_id": "reviewer:one",
        "author_display_name": "Reviewer One",
        "rationale": "Controlled manual review of the scoped evidence.",
        "supporting_evidence_references": ("fixture:review:1",),
        "reviewer_certainty": _certainty(),
        "created_at": NOW,
    }
    kwargs.update(overrides)
    return append_manual_identity_binding(
        foundation, clustering, diarization, **kwargs
    )


def _lineage(tmp_path: Path):
    provider = ConflictedClusteringProvider()
    _, _, diarization, _, diarization_root, _ = _prepare(tmp_path, provider)
    clustering, _, clustering_root, _ = cluster_diarization(
        diarization_root,
        tmp_path / "clusters",
        capabilities=provider.capabilities,
    )
    scope = IdentityScope(
        kind=IdentityScopeKind.CLUSTER,
        target_id=clustering.clusters[0].cluster_id,
        explanation="Manual decisions are limited to this cluster.",
    )
    foundation = None
    identities = []
    specifications = (
        ("Participant A", IdentityKind.LOCAL_PARTICIPANT),
        ("Participant B", IdentityKind.LOCAL_PARTICIPANT),
        ("Placeholder A", IdentityKind.UNRESOLVED_PLACEHOLDER),
        ("Placeholder B", IdentityKind.UNRESOLVED_PLACEHOLDER),
    )
    for label, kind in specifications:
        foundation, identity = add_participant_identity(
            clustering,
            diarization,
            canonical_display_label=label,
            identity_kind=kind,
            information_source="controlled binding fixture",
            scope=scope,
            provenance_references=(f"fixture:identity:{label}",),
            predecessor=foundation,
            created_at=NOW,
        )
        identities.append(identity)
    persisted = persist_identity_foundation(
        foundation,
        clustering,
        diarization,
        tmp_path / "identity",
        predecessor=None,
    )
    return (
        foundation,
        clustering,
        diarization,
        scope,
        tuple(identities),
        persisted[2],
        clustering_root,
        diarization_root,
    )


def test_identity_binding_contract_schemas_are_closed() -> None:
    assert len(IDENTITY_BINDING_CONTRACT_MODELS) == 3
    for model in IDENTITY_BINDING_CONTRACT_MODELS:
        schema = model.model_json_schema()
        assert schema["title"] == model.__name__
        assert schema.get("additionalProperties") is False


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_manual_binding_is_append_only_separate_and_cached(tmp_path: Path) -> None:
    lineage = _lineage(tmp_path)
    foundation, clustering, diarization, scope, identities, *_ = lineage
    source_before = diarization.model_dump_json()
    run, binding = _binding(lineage[:5])
    stored = persist_identity_binding_run(
        run,
        foundation,
        clustering,
        diarization,
        tmp_path / "bindings",
    )
    assert not stored[-1]
    assert stored[1].binding_count == 1
    assert stored[1].status == "complete"
    assert binding.author_id == "reviewer:one"
    assert binding.resulting_identity_view_version_id.startswith("identityview_")
    assert identities[0].canonical_display_label not in source_before
    assert diarization.model_dump_json() == source_before
    cached = persist_identity_binding_run(
        run,
        foundation,
        clustering,
        diarization,
        tmp_path / "bindings",
    )
    assert cached[-1]


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_revise_restore_unknown_reject_and_conflicts_are_derived(
    tmp_path: Path,
) -> None:
    lineage = _lineage(tmp_path)
    foundation, clustering, diarization, scope, identities, *_ = lineage
    first, first_binding = _binding(lineage[:5])
    limited_scope = IdentityScope(
        kind=IdentityScopeKind.SPEAKER_TURN,
        target_id=diarization.turns[0].turn_id,
        explanation="Revision is limited to one turn from the target cluster.",
    )
    second, revision = append_manual_identity_binding(
        foundation,
        clustering,
        diarization,
        target_artifact_id=scope.target_id,
        identity_id=identities[1].identity_id,
        scope=limited_scope,
        action=BindingAction.REVISE,
        predecessor_binding_id=first_binding.binding_id,
        author_id="reviewer:two",
        author_display_name="Reviewer Two",
        rationale="Contrary evidence supports a revised scoped decision.",
        supporting_evidence_references=("fixture:review:2",),
        contrary_evidence_acknowledged=("fixture:review:1",),
        reviewer_certainty=_certainty(0.7),
        predecessor=first,
        created_at=NOW,
    )
    assert active_bindings(second) == (revision,)
    assert revision.scope.kind == IdentityScopeKind.SPEAKER_TURN
    third, unknown = append_manual_identity_binding(
        foundation,
        clustering,
        diarization,
        target_artifact_id=scope.target_id,
        identity_id=None,
        scope=limited_scope,
        action=BindingAction.MARK_UNKNOWN,
        author_id="reviewer:three",
        author_display_name="Reviewer Three",
        rationale="A separate review branch cannot identify this voice.",
        supporting_evidence_references=("fixture:review:3",),
        reviewer_certainty=_certainty(0.4),
        predecessor=second,
        created_at=NOW,
    )
    persisted = persist_identity_binding_run(
        third,
        foundation,
        clustering,
        diarization,
        tmp_path / "conflicted",
        predecessor=second,
    )
    assert unknown in active_bindings(third)
    assert persisted[1].unresolved_conflict_count == 1
    assert persisted[1].status == "warning"

    fourth, rejection = append_manual_identity_binding(
        foundation,
        clustering,
        diarization,
        target_artifact_id=scope.target_id,
        identity_id=identities[0].identity_id,
        scope=scope,
        action=BindingAction.REJECT_IDENTITY,
        author_id="reviewer:four",
        author_display_name="Reviewer Four",
        rationale="The proposed identity is rejected on documentary evidence.",
        supporting_evidence_references=("fixture:review:4",),
        reviewer_certainty=_certainty(0.9),
        predecessor=third,
        created_at=NOW,
    )
    fifth, restored = append_manual_identity_binding(
        foundation,
        clustering,
        diarization,
        target_artifact_id=scope.target_id,
        identity_id=identities[0].identity_id,
        scope=scope,
        action=BindingAction.RESTORE,
        predecessor_binding_id=rejection.binding_id,
        author_id="reviewer:five",
        author_display_name="Reviewer Five",
        rationale="Later evidence restores the earlier identity decision.",
        supporting_evidence_references=("fixture:review:5",),
        contrary_evidence_acknowledged=("fixture:review:4",),
        reviewer_certainty=_certainty(0.75),
        predecessor=fourth,
        created_at=NOW,
    )
    assert restored in active_bindings(fifth)
    with pytest.raises(
        IdentityBindingIntegrityError, match="active decision"
    ):
        append_manual_identity_binding(
            foundation,
            clustering,
            diarization,
            target_artifact_id=scope.target_id,
            identity_id=identities[0].identity_id,
            scope=scope,
            action=BindingAction.REVISE,
            predecessor_binding_id=first_binding.binding_id,
            author_id="reviewer:six",
            author_display_name="Reviewer Six",
            rationale="Invalid attempt to revise an inactive decision.",
            supporting_evidence_references=("fixture:review:6",),
            reviewer_certainty=_certainty(),
            predecessor=fifth,
            created_at=NOW,
        )


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_placeholder_merge_and_identity_split_require_existing_entities(
    tmp_path: Path,
) -> None:
    lineage = _lineage(tmp_path)
    foundation, clustering, diarization, scope, identities, *_ = lineage
    merged, merge = _binding(
        lineage[:5],
        target_artifact_id=identities[0].identity_id,
        identity_id=identities[0].identity_id,
        related_identity_ids=(
            identities[2].identity_id,
            identities[3].identity_id,
        ),
        action=BindingAction.MERGE_IDENTITY_PLACEHOLDERS,
    )
    assert merge.related_identity_ids
    split, split_binding = append_manual_identity_binding(
        foundation,
        clustering,
        diarization,
        target_artifact_id=identities[0].identity_id,
        identity_id=identities[0].identity_id,
        related_identity_ids=(
            identities[1].identity_id,
            identities[2].identity_id,
        ),
        scope=scope,
        action=BindingAction.SPLIT_IDENTITY,
        author_id="reviewer:one",
        author_display_name="Reviewer One",
        rationale="The prior identity entity unified distinct participants.",
        supporting_evidence_references=("fixture:split",),
        reviewer_certainty=_certainty(),
        predecessor=merged,
        created_at=NOW,
    )
    assert split_binding.action == BindingAction.SPLIT_IDENTITY
    assert split.bindings[:1] == merged.bindings
    with pytest.raises(
        IdentityBindingIntegrityError, match="unknown participant identity"
    ):
        _binding(
            lineage[:5],
            target_artifact_id=identities[0].identity_id,
            identity_id=identities[0].identity_id,
            related_identity_ids=("identity_" + "f" * 32,),
            action=BindingAction.MERGE_IDENTITY_PLACEHOLDERS,
        )


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_identity_binding_cli_bind_inspect_list_history_and_validate(
    tmp_path: Path,
) -> None:
    lineage = _lineage(tmp_path)
    (
        foundation,
        _,
        _,
        scope,
        identities,
        foundation_root,
        clustering_root,
        diarization_root,
    ) = lineage
    destination = tmp_path / "binding-cli"
    assert main(
        [
            "--json",
            "diarization",
            "identity-bind",
            str(foundation_root),
            str(clustering_root),
            str(diarization_root),
            str(destination),
            "--binding-action",
            "bind",
            "--target",
            scope.target_id,
            "--identity",
            identities[0].identity_id,
            "--scope-kind",
            "cluster",
            "--scope-target",
            scope.target_id,
            "--scope-explanation",
            "CLI decision limited to this cluster.",
            "--author-id",
            "reviewer:cli",
            "--author-name",
            "CLI Reviewer",
            "--rationale",
            "Controlled CLI binding qualification.",
            "--supporting",
            "fixture:cli:binding",
            "--certainty",
            "0.8",
            "--certainty-basis",
            "Manual reviewer certainty, not calibration.",
        ]
    ) == EXIT_SUCCESS
    root = next((destination / "identity-bindings").iterdir())
    assert main(
        ["--json", "diarization", "identity-binding-inspect", str(root)]
    ) == EXIT_SUCCESS
    assert main(
        ["--json", "diarization", "identity-binding-list", str(root)]
    ) == EXIT_SUCCESS
    assert main(
        ["--json", "diarization", "identity-binding-history", str(root)]
    ) == EXIT_SUCCESS
    assert main(
        [
            "--json",
            "diarization",
            "identity-binding-validate",
            str(root),
            str(foundation_root),
            str(clustering_root),
            str(diarization_root),
        ]
    ) == EXIT_SUCCESS
    assert foundation.foundation_id
