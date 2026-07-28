from __future__ import annotations

from pathlib import Path

import pytest

from ratiocinatus.cli import EXIT_SUCCESS, main
from ratiocinatus.identity_binding import (
    append_manual_identity_binding,
    persist_identity_binding_run,
)
from ratiocinatus.identity_view import (
    IdentityViewIntegrityError,
    assemble_identity_views,
    persist_identity_view_assembly,
    reviewed_identity_view,
)
from ratiocinatus.identity_view_contracts import (
    IDENTITY_VIEW_CONTRACT_MODELS,
    IdentityViewDisposition,
    IdentityViewKind,
)
from ratiocinatus.kernel import load_contract
from ratiocinatus.phase3_contracts import (
    BindingAction,
    DiarizationProviderResponse,
)

from test_phase3_clustering import HAS_FFMPEG
from test_phase3_identity_binding import NOW, _binding, _certainty, _lineage


def _inputs(tmp_path: Path):
    lineage = _lineage(tmp_path)
    (
        foundation,
        clustering,
        diarization,
        scope,
        identities,
        foundation_root,
        clustering_root,
        diarization_root,
    ) = lineage
    response = load_contract(
        (diarization_root / "response.json").read_bytes(),
        DiarizationProviderResponse,
    )
    binding_run, binding = _binding(lineage[:5])
    persisted_binding = persist_identity_binding_run(
        binding_run,
        foundation,
        clustering,
        diarization,
        tmp_path / "bindings",
    )
    return (
        response,
        diarization,
        clustering,
        foundation,
        binding_run,
        binding,
        scope,
        identities,
        persisted_binding[2],
        foundation_root,
        clustering_root,
        diarization_root,
    )


def test_identity_view_contract_schemas_are_closed() -> None:
    assert len(IDENTITY_VIEW_CONTRACT_MODELS) == 5
    for model in IDENTITY_VIEW_CONTRACT_MODELS:
        schema = model.model_json_schema()
        assert schema["title"] == model.__name__
        assert schema.get("additionalProperties") is False


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_assembly_contains_eight_distinct_views_and_visible_review_labels(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    response, diarization, clustering, foundation, binding_run, binding = (
        inputs[:6]
    )
    source_before = diarization.model_dump_json()
    assembly = assemble_identity_views(
        response,
        diarization,
        clustering,
        foundation,
        binding_run,
        created_at=NOW,
    )
    assert {item.kind for item in assembly.views} == set(IdentityViewKind)
    reviewed = reviewed_identity_view(assembly)
    assert reviewed.view_id == binding.resulting_identity_view_version_id
    labeled = tuple(
        item
        for item in reviewed.entries
        if item.disposition == IdentityViewDisposition.REVIEWED_IDENTITY
    )
    assert labeled
    assert all(item.reviewed_label.startswith("REVIEWED: ") for item in labeled)
    assert all(item.original_machine_label for item in reviewed.entries)
    comparison = next(
        item
        for item in assembly.views
        if item.kind == IdentityViewKind.REFERENCE_COMPARISON
    )
    assert not comparison.entries
    assert "No compatible" in comparison.findings[0]
    assert diarization.model_dump_json() == source_before


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_conflicting_manual_branches_block_reviewed_identity_view(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    (
        response,
        diarization,
        clustering,
        foundation,
        first,
        _,
        scope,
        identities,
    ) = inputs[:8]
    conflicted, _ = append_manual_identity_binding(
        foundation,
        clustering,
        diarization,
        target_artifact_id=scope.target_id,
        identity_id=identities[1].identity_id,
        scope=scope,
        action=BindingAction.BIND,
        author_id="reviewer:conflict",
        author_display_name="Conflict Reviewer",
        rationale="An independent branch reaches an incompatible conclusion.",
        supporting_evidence_references=("fixture:conflicting-view",),
        reviewer_certainty=_certainty(0.7),
        predecessor=first,
        created_at=NOW,
    )
    assembly = assemble_identity_views(
        response,
        diarization,
        clustering,
        foundation,
        conflicted,
        created_at=NOW,
    )
    reviewed = reviewed_identity_view(assembly)
    assert reviewed.blocking_findings
    assert not reviewed.trusted_for_participant_rendering
    assert any(
        item.disposition == IdentityViewDisposition.CONFLICTED
        and item.reviewed_label == "REVIEWED: CONFLICT"
        for item in reviewed.entries
    )


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_identity_view_persistence_reuses_and_rejects_lineage_mismatch(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    response, diarization, clustering, foundation, binding_run = inputs[:5]
    assembly = assemble_identity_views(
        response,
        diarization,
        clustering,
        foundation,
        binding_run,
        created_at=NOW,
    )
    stored = persist_identity_view_assembly(
        assembly,
        response,
        diarization,
        clustering,
        foundation,
        binding_run,
        tmp_path / "views",
    )
    assert not stored[-1]
    assert stored[1].view_count == 8
    assert persist_identity_view_assembly(
        assembly,
        response,
        diarization,
        clustering,
        foundation,
        binding_run,
        tmp_path / "views",
    )[-1]
    wrong_response = response.model_copy(
        update={"response_id": "diaresponse_" + "f" * 32}
    )
    with pytest.raises(
        IdentityViewIntegrityError, match="lineage disagree"
    ):
        assemble_identity_views(
            wrong_response,
            diarization,
            clustering,
            foundation,
            binding_run,
        )


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_identity_view_cli_assemble_inspect_list_reviewed_and_validate(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    (
        _,
        _,
        _,
        _,
        _,
        _,
        _,
        _,
        binding_root,
        foundation_root,
        clustering_root,
        diarization_root,
    ) = inputs
    destination = tmp_path / "view-cli"
    assert main(
        [
            "--json",
            "diarization",
            "identity-view-assemble",
            str(diarization_root),
            str(clustering_root),
            str(foundation_root),
            str(binding_root),
            str(destination),
        ]
    ) == EXIT_SUCCESS
    view_root = next((destination / "identity-views").iterdir())
    assert main(
        ["--json", "diarization", "identity-view-inspect", str(view_root)]
    ) == EXIT_SUCCESS
    assert main(
        [
            "--json",
            "diarization",
            "identity-view-list",
            str(view_root),
            "--kind",
            "manually_reviewed_identity",
        ]
    ) == EXIT_SUCCESS
    assert main(
        ["--json", "diarization", "identity-view-reviewed", str(view_root)]
    ) == EXIT_SUCCESS
    assert main(
        [
            "--json",
            "diarization",
            "identity-view-validate",
            str(view_root),
            str(diarization_root),
            str(clustering_root),
            str(foundation_root),
            str(binding_root),
        ]
    ) == EXIT_SUCCESS
