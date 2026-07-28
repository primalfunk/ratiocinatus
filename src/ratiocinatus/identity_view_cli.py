"""CLI integration for deterministic layered identity-view assembly."""

from __future__ import annotations

from pathlib import Path

from .clustering_contracts import ClusteringRun
from .identity import load_identity_foundation
from .identity_binding import load_identity_binding_run
from .identity_view import (
    assemble_identity_views,
    load_identity_view_assembly,
    persist_identity_view_assembly,
    reviewed_identity_view,
    validate_identity_view_assembly,
)
from .identity_view_contracts import IdentityViewKind
from .kernel import load_contract
from .phase3_contracts import DiarizationProviderResponse, DiarizationRun
from .reference_comparison_validation import load_reference_comparison

IDENTITY_VIEW_ACTIONS = {
    "identity-view-assemble",
    "identity-view-inspect",
    "identity-view-list",
    "identity-view-reviewed",
    "identity-view-validate",
}


def add_identity_view_parsers(diasub) -> None:
    assemble = diasub.add_parser("identity-view-assemble")
    assemble.add_argument("diarization_root", type=Path)
    assemble.add_argument("clustering_root", type=Path)
    assemble.add_argument("foundation_root", type=Path)
    assemble.add_argument("binding_root", type=Path)
    assemble.add_argument("destination", type=Path)
    assemble.add_argument("--comparison-root", type=Path)

    validate = diasub.add_parser("identity-view-validate")
    validate.add_argument("view_root", type=Path)
    validate.add_argument("diarization_root", type=Path)
    validate.add_argument("clustering_root", type=Path)
    validate.add_argument("foundation_root", type=Path)
    validate.add_argument("binding_root", type=Path)
    validate.add_argument("--comparison-root", type=Path)

    for action in ("identity-view-inspect", "identity-view-reviewed"):
        parser = diasub.add_parser(action)
        parser.add_argument("view_root", type=Path)
    listing = diasub.add_parser("identity-view-list")
    listing.add_argument("view_root", type=Path)
    listing.add_argument(
        "--kind",
        choices=[item.value for item in IdentityViewKind],
    )


def _load_lineage(args):
    diarization_root = args.diarization_root.expanduser().resolve(strict=True)
    clustering_root = args.clustering_root.expanduser().resolve(strict=True)
    response = load_contract(
        (diarization_root / "response.json").read_bytes(),
        DiarizationProviderResponse,
    )
    diarization = load_contract(
        (diarization_root / "run.json").read_bytes(), DiarizationRun
    )
    clustering = load_contract(
        (clustering_root / "clustering.json").read_bytes(), ClusteringRun
    )
    foundation, _ = load_identity_foundation(args.foundation_root)
    binding_run, _ = load_identity_binding_run(args.binding_root)
    comparisons = (
        load_reference_comparison(args.comparison_root)[0]
        if args.comparison_root is not None
        else None
    )
    return response, diarization, clustering, foundation, binding_run, comparisons


def run_identity_view_command(args, emit, structured: bool):
    if args.action not in IDENTITY_VIEW_ACTIONS:
        return None
    if args.action in {
        "identity-view-inspect",
        "identity-view-list",
        "identity-view-reviewed",
    }:
        assembly, report = load_identity_view_assembly(args.view_root)
        if args.action == "identity-view-list":
            selected = (
                assembly.views
                if args.kind is None
                else tuple(
                    item
                    for item in assembly.views
                    if item.kind == IdentityViewKind(args.kind)
                )
            )
            emit(selected, structured)
        elif args.action == "identity-view-reviewed":
            emit(reviewed_identity_view(assembly), structured)
        else:
            emit(
                {
                    "assembly": assembly.model_dump(mode="json"),
                    "report": report.model_dump(mode="json"),
                },
                structured,
            )
        return 0

    lineage = _load_lineage(args)
    if args.action == "identity-view-validate":
        assembly, report = load_identity_view_assembly(args.view_root)
        validate_identity_view_assembly(
            assembly,
            *lineage[:5],
            comparisons=lineage[5],
            report=report,
        )
        emit(
            {"valid": True, "assembly_id": assembly.assembly_id},
            structured,
        )
        return 0

    protected = tuple(
        path.expanduser().resolve(strict=True)
        for path in (
            args.diarization_root,
            args.clustering_root,
            args.foundation_root,
            args.binding_root,
        )
    )
    destination = args.destination.expanduser().resolve()
    if any(
        destination == root or root in destination.parents
        for root in protected
    ):
        raise ValueError("identity-view output must not modify source evidence")
    assembly = assemble_identity_views(
        *lineage[:5],
        comparisons=lineage[5],
    )
    persisted = persist_identity_view_assembly(
        assembly,
        *lineage[:5],
        destination,
        comparisons=lineage[5],
    )
    emit(
        {
            "assembly": persisted[0].model_dump(mode="json"),
            "report": persisted[1].model_dump(mode="json"),
            "view_root": str(persisted[2]),
            "reused": persisted[3],
        },
        structured,
    )
    return 0
