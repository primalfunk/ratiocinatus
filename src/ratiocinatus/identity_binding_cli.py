"""CLI integration for append-only manual identity binding."""

from __future__ import annotations

from pathlib import Path

from .clustering_contracts import ClusteringRun
from .identity import load_identity_foundation
from .identity_binding import (
    active_bindings,
    append_manual_identity_binding,
    load_identity_binding_run,
    persist_identity_binding_run,
    validate_identity_binding_run,
)
from .kernel import load_contract
from .phase2_contracts import ConfidenceMeasure, ConfidenceOrigin
from .phase3_contracts import (
    BindingAction,
    DiarizationRun,
    IdentityScope,
    IdentityScopeKind,
)

BIND_ACTION = "identity-bind"
BINDING_ACTIONS = {
    BIND_ACTION,
    "identity-binding-inspect",
    "identity-binding-list",
    "identity-binding-history",
    "identity-binding-validate",
}


def add_identity_binding_parsers(diasub) -> None:
    bind = diasub.add_parser(BIND_ACTION)
    bind.add_argument("foundation_root", type=Path)
    bind.add_argument("clustering_root", type=Path)
    bind.add_argument("diarization_root", type=Path)
    bind.add_argument("destination", type=Path)
    bind.add_argument("--predecessor", type=Path)
    bind.add_argument(
        "--binding-action",
        required=True,
        choices=[item.value for item in BindingAction],
    )
    bind.add_argument("--target", required=True)
    bind.add_argument("--identity")
    bind.add_argument("--related-identity", action="append", default=[])
    bind.add_argument("--predecessor-binding")
    bind.add_argument("--scope-kind", required=True)
    bind.add_argument("--scope-target", required=True)
    bind.add_argument("--scope-explanation", required=True)
    bind.add_argument("--author-id", required=True)
    bind.add_argument("--author-name", required=True)
    bind.add_argument("--rationale", required=True)
    bind.add_argument("--supporting", action="append", required=True)
    bind.add_argument("--contrary-acknowledged", action="append", default=[])
    bind.add_argument("--certainty", type=float, required=True)
    bind.add_argument("--certainty-basis", required=True)

    validate = diasub.add_parser("identity-binding-validate")
    validate.add_argument("binding_root", type=Path)
    validate.add_argument("foundation_root", type=Path)
    validate.add_argument("clustering_root", type=Path)
    validate.add_argument("diarization_root", type=Path)
    validate.add_argument("--predecessor", type=Path)

    for action in (
        "identity-binding-inspect",
        "identity-binding-list",
        "identity-binding-history",
    ):
        parser = diasub.add_parser(action)
        parser.add_argument("binding_root", type=Path)
        if action == "identity-binding-history":
            parser.add_argument("--binding")


def _load_lineage(args):
    foundation, _ = load_identity_foundation(args.foundation_root)
    clustering_root = args.clustering_root.expanduser().resolve(strict=True)
    diarization_root = args.diarization_root.expanduser().resolve(strict=True)
    clustering = load_contract(
        (clustering_root / "clustering.json").read_bytes(), ClusteringRun
    )
    diarization = load_contract(
        (diarization_root / "run.json").read_bytes(), DiarizationRun
    )
    return foundation, clustering, diarization


def _history(run, binding_id: str | None):
    if binding_id is None:
        return run.bindings
    by_id = {item.binding_id: item for item in run.bindings}
    current = by_id.get(binding_id)
    if current is None:
        raise ValueError("requested manual binding is not in this ledger")
    history = []
    while current is not None:
        history.append(current)
        current = (
            by_id.get(current.predecessor_binding_id)
            if current.predecessor_binding_id is not None
            else None
        )
    return tuple(reversed(history))


def run_identity_binding_command(args, emit, structured: bool):
    if args.action not in BINDING_ACTIONS:
        return None
    if args.action in {
        "identity-binding-inspect",
        "identity-binding-list",
        "identity-binding-history",
    }:
        run, report = load_identity_binding_run(args.binding_root)
        if args.action == "identity-binding-list":
            emit(active_bindings(run), structured)
        elif args.action == "identity-binding-history":
            emit(_history(run, args.binding), structured)
        else:
            emit(
                {
                    "binding": run.model_dump(mode="json"),
                    "report": report.model_dump(mode="json"),
                },
                structured,
            )
        return 0

    foundation, clustering, diarization = _load_lineage(args)
    predecessor = None
    if args.predecessor is not None:
        predecessor, _ = load_identity_binding_run(args.predecessor)
    if args.action == "identity-binding-validate":
        run, report = load_identity_binding_run(args.binding_root)
        validate_identity_binding_run(
            run,
            foundation,
            clustering,
            diarization,
            predecessor=predecessor,
            report=report,
        )
        emit({"valid": True, "run_id": run.run_id}, structured)
        return 0

    protected = tuple(
        path.expanduser().resolve(strict=True)
        for path in (
            args.foundation_root,
            args.clustering_root,
            args.diarization_root,
        )
    )
    destination = args.destination.expanduser().resolve()
    if any(
        destination == root or root in destination.parents
        for root in protected
    ):
        raise ValueError("identity binding output must not modify source evidence")
    scope = IdentityScope(
        kind=IdentityScopeKind(args.scope_kind),
        target_id=args.scope_target,
        explanation=args.scope_explanation,
    )
    run, binding = append_manual_identity_binding(
        foundation,
        clustering,
        diarization,
        target_artifact_id=args.target,
        identity_id=args.identity,
        related_identity_ids=tuple(args.related_identity),
        scope=scope,
        action=BindingAction(args.binding_action),
        predecessor_binding_id=args.predecessor_binding,
        author_id=args.author_id,
        author_display_name=args.author_name,
        rationale=args.rationale,
        supporting_evidence_references=tuple(args.supporting),
        contrary_evidence_acknowledged=tuple(
            args.contrary_acknowledged
        ),
        reviewer_certainty=ConfidenceMeasure(
            value=args.certainty,
            origin=ConfidenceOrigin.DERIVED,
            basis=args.certainty_basis,
        ),
        predecessor=predecessor,
    )
    persisted = persist_identity_binding_run(
        run,
        foundation,
        clustering,
        diarization,
        destination,
        predecessor=predecessor,
    )
    emit(
        {
            "binding": binding.model_dump(mode="json"),
            "run": persisted[0].model_dump(mode="json"),
            "report": persisted[1].model_dump(mode="json"),
            "binding_root": str(persisted[2]),
            "reused": persisted[3],
        },
        structured,
    )
    return 0
