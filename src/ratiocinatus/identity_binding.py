"""Append-only manual participant-identity decisions and derived state."""

from __future__ import annotations

import os
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .clustering_contracts import ClusteringRun
from .identity import (
    IdentityFoundationIntegrityError,
    _known_targets,
    _validate_scope,
    validate_identity_foundation,
)
from .identity_binding_contracts import (
    IdentityBindingPolicy,
    IdentityBindingReport,
    IdentityBindingRun,
)
from .identity_contracts import IdentityFoundationRun
from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase2_contracts import ConfidenceMeasure
from .phase3_contracts import (
    BindingAction,
    DiarizationRun,
    IdentityKind,
    IdentityScope,
    ManualIdentityBinding,
)


class IdentityBindingIntegrityError(RuntimeError):
    """Manual identity decisions violate lineage or append-only rules."""


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


def _integrity_payload(item) -> dict:
    payload = item.model_dump(mode="json")
    payload.pop("integrity_sha256", None)
    return payload


def active_bindings(
    run: IdentityBindingRun,
) -> tuple[ManualIdentityBinding, ...]:
    superseded = {
        item.predecessor_binding_id
        for item in run.bindings
        if item.predecessor_binding_id is not None
    }
    return tuple(
        item for item in run.bindings if item.binding_id not in superseded
    )


def _conflict_groups(
    active: tuple[ManualIdentityBinding, ...],
) -> tuple[tuple[str, ...], ...]:
    decision_actions = {
        BindingAction.BIND,
        BindingAction.REJECT_IDENTITY,
        BindingAction.MARK_UNKNOWN,
        BindingAction.REVISE,
        BindingAction.RESTORE,
    }
    grouped: dict[tuple[str, str, str], list[ManualIdentityBinding]] = (
        defaultdict(list)
    )
    for item in active:
        if item.action in decision_actions:
            grouped[
                (
                    item.target_artifact_id,
                    item.scope.kind.value,
                    item.scope.target_id,
                )
            ].append(item)
    conflicts: list[tuple[str, ...]] = []
    for decisions in grouped.values():
        dispositions = {
            (
                "unknown"
                if item.action == BindingAction.MARK_UNKNOWN
                else "rejected"
                if item.action == BindingAction.REJECT_IDENTITY
                else "bound",
                item.identity_id,
            )
            for item in decisions
        }
        if len(dispositions) > 1:
            conflicts.append(
                tuple(sorted(item.binding_id for item in decisions))
            )
    return tuple(sorted(conflicts))


def _report(run: IdentityBindingRun) -> IdentityBindingReport:
    active = active_bindings(run)
    conflicts = _conflict_groups(active)
    counts = Counter(item.action.value for item in run.bindings)
    findings = (
        (
            "Manual decisions are attributable, scoped, and preserved in "
            "append-only order."
        ),
        (
            "Active identity state is derived without modifying diarization "
            "speaker labels."
        ),
    )
    limitations = (
        (
            "Conflicting active decision branches require an explicit later "
            "revision; none is silently selected."
        ),
        (
            "Reviewed identity views are separate derived artifacts; this "
            "ledger remains the authoritative manual-decision history."
        ),
    )
    return _seal(
        IdentityBindingReport,
        {
            "report_id": typed_id("identitybindingreport", run.run_id),
            "run_id": run.run_id,
            "foundation_id": run.foundation_id,
            "generated_at": run.created_at,
            "binding_count": len(run.bindings),
            "active_binding_count": len(active),
            "unresolved_conflict_count": len(conflicts),
            "action_counts": dict(sorted(counts.items())),
            "active_binding_ids": tuple(item.binding_id for item in active),
            "conflicting_binding_groups": conflicts,
            "findings": findings,
            "limitations": limitations,
            "status": "warning" if conflicts else "complete",
        },
    )


def validate_identity_binding_run(
    run: IdentityBindingRun,
    foundation: IdentityFoundationRun,
    clustering: ClusteringRun,
    diarization: DiarizationRun,
    *,
    predecessor: IdentityBindingRun | None = None,
    report: IdentityBindingReport | None = None,
) -> None:
    if canonical_hash(_integrity_payload(run)) != run.integrity_sha256:
        raise IdentityBindingIntegrityError("identity binding integrity is invalid")
    try:
        validate_identity_foundation(foundation, clustering, diarization)
    except IdentityFoundationIntegrityError as exc:
        raise IdentityBindingIntegrityError(str(exc)) from exc
    if (
        run.foundation_id != foundation.foundation_id
        or run.foundation_integrity_sha256 != foundation.integrity_sha256
        or run.clustering_run_id != clustering.run_id
        or run.diarization_run_id != diarization.run_id
        or run.corpus_id != diarization.corpus_id
    ):
        raise IdentityBindingIntegrityError(
            "identity binding lineage is incompatible"
        )
    if predecessor is not None:
        validate_identity_binding_run(
            predecessor, foundation, clustering, diarization
        )
        if (
            run.predecessor_run_id != predecessor.run_id
            or run.bindings[: len(predecessor.bindings)]
            != predecessor.bindings
            or len(run.bindings) <= len(predecessor.bindings)
        ):
            raise IdentityBindingIntegrityError(
                "identity binding successor rewrites prior decisions"
            )

    identities = {item.identity_id: item for item in foundation.identities}
    known_artifacts = set().union(
        *_known_targets(clustering, diarization).values()
    )
    seen: dict[str, ManualIdentityBinding] = {}
    for item in run.bindings:
        structural = item.action in {
            BindingAction.MERGE_IDENTITY_PLACEHOLDERS,
            BindingAction.SPLIT_IDENTITY,
        }
        try:
            _validate_scope(item.scope, clustering, diarization)
        except IdentityFoundationIntegrityError as exc:
            raise IdentityBindingIntegrityError(str(exc)) from exc
        referenced = {
            identity_id
            for identity_id in (item.identity_id, *item.related_identity_ids)
            if identity_id is not None
        }
        if not referenced.issubset(identities):
            raise IdentityBindingIntegrityError(
                "manual binding references an unknown participant identity"
            )
        if structural:
            if item.target_artifact_id != item.identity_id:
                raise IdentityBindingIntegrityError(
                    "merge or split target must be the primary identity"
                )
            if (
                item.action == BindingAction.MERGE_IDENTITY_PLACEHOLDERS
                and any(
                    identities[identity_id].identity_kind
                    != IdentityKind.UNRESOLVED_PLACEHOLDER
                    for identity_id in item.related_identity_ids
                )
            ):
                raise IdentityBindingIntegrityError(
                    "merge action accepts unresolved identity placeholders only"
                )
            if (
                item.action == BindingAction.SPLIT_IDENTITY
                and len(item.related_identity_ids) < 2
            ):
                raise IdentityBindingIntegrityError(
                    "identity split requires at least two resulting identities"
                )
        elif item.target_artifact_id not in known_artifacts:
            raise IdentityBindingIntegrityError(
                "manual binding target is not in the pinned evidence"
            )
        if item.predecessor_binding_id is not None:
            prior = seen.get(item.predecessor_binding_id)
            if prior is None:
                raise IdentityBindingIntegrityError(
                    "binding predecessor must appear earlier in the ledger"
                )
            if (
                item.action not in {BindingAction.REVISE, BindingAction.RESTORE}
                or item.target_artifact_id != prior.target_artifact_id
            ):
                raise IdentityBindingIntegrityError(
                    "binding predecessor is invalid for this action"
                )
            already_revised = any(
                candidate.predecessor_binding_id == prior.binding_id
                for candidate in seen.values()
            )
            if already_revised:
                raise IdentityBindingIntegrityError(
                    "binding predecessor is not an active decision"
                )
        elif item.action in {BindingAction.REVISE, BindingAction.RESTORE}:
            raise IdentityBindingIntegrityError(
                "revision or restoration requires an active predecessor"
            )
        seen[item.binding_id] = item
    if report is not None and (
        canonical_hash(_integrity_payload(report)) != report.integrity_sha256
        or report != _report(run)
    ):
        raise IdentityBindingIntegrityError(
            "identity binding report integrity or projection is invalid"
        )


def append_manual_identity_binding(
    foundation: IdentityFoundationRun,
    clustering: ClusteringRun,
    diarization: DiarizationRun,
    *,
    target_artifact_id: str,
    identity_id: str | None,
    related_identity_ids: tuple[str, ...] = (),
    scope: IdentityScope,
    action: BindingAction,
    predecessor_binding_id: str | None = None,
    author_id: str,
    author_display_name: str,
    rationale: str,
    supporting_evidence_references: tuple[str, ...],
    contrary_evidence_acknowledged: tuple[str, ...] = (),
    reviewer_certainty: ConfidenceMeasure,
    predecessor: IdentityBindingRun | None = None,
    policy: IdentityBindingPolicy | None = None,
    created_at: datetime | None = None,
) -> tuple[IdentityBindingRun, ManualIdentityBinding]:
    if predecessor is not None:
        validate_identity_binding_run(
            predecessor, foundation, clustering, diarization
        )
    else:
        validate_identity_foundation(foundation, clustering, diarization)
    if not supporting_evidence_references:
        raise ValueError("manual identity binding requires supporting evidence")
    timestamp = created_at or datetime.now(timezone.utc)
    binding_id = typed_id(
        "identitybind",
        foundation.foundation_id,
        predecessor.run_id if predecessor else None,
        target_artifact_id,
        identity_id,
        related_identity_ids,
        scope.model_dump(mode="json"),
        action.value,
        predecessor_binding_id,
        author_id,
        timestamp.isoformat(),
        rationale,
        supporting_evidence_references,
        contrary_evidence_acknowledged,
        reviewer_certainty.model_dump(mode="json"),
    )
    binding = ManualIdentityBinding(
        binding_id=binding_id,
        target_artifact_id=target_artifact_id,
        identity_id=identity_id,
        related_identity_ids=related_identity_ids,
        scope=scope,
        action=action,
        predecessor_binding_id=predecessor_binding_id,
        author_id=author_id,
        author_display_name=author_display_name,
        bound_at=timestamp,
        rationale=rationale,
        supporting_evidence_references=supporting_evidence_references,
        contrary_evidence_acknowledged=contrary_evidence_acknowledged,
        reviewer_certainty=reviewer_certainty,
        resulting_identity_view_version_id=typed_id(
            "identityview",
            predecessor.run_id if predecessor else foundation.foundation_id,
            binding_id,
        ),
    )
    bindings = (*predecessor.bindings, binding) if predecessor else (binding,)
    selected_policy = predecessor.policy if predecessor else (
        policy or IdentityBindingPolicy()
    )
    configuration_hash = canonical_hash(
        {
            "operation": "participant.identity.manual_binding",
            "foundation_id": foundation.foundation_id,
            "foundation_integrity_sha256": foundation.integrity_sha256,
            "policy": selected_policy.model_dump(mode="json"),
        }
    )
    run_id = typed_id(
        "identitybindingrun",
        foundation.foundation_id,
        predecessor.run_id if predecessor else None,
        [item.model_dump(mode="json") for item in bindings],
        configuration_hash,
    )
    run = _seal(
        IdentityBindingRun,
        {
            "run_id": run_id,
            "predecessor_run_id": predecessor.run_id if predecessor else None,
            "foundation_id": foundation.foundation_id,
            "foundation_integrity_sha256": foundation.integrity_sha256,
            "clustering_run_id": clustering.run_id,
            "diarization_run_id": diarization.run_id,
            "corpus_id": diarization.corpus_id,
            "policy": selected_policy,
            "configuration_hash": configuration_hash,
            "bindings": bindings,
            "created_at": timestamp,
        },
    )
    validate_identity_binding_run(
        run,
        foundation,
        clustering,
        diarization,
        predecessor=predecessor,
    )
    return run, binding


def identity_binding_report_markdown(report: IdentityBindingReport) -> str:
    return (
        "# Manual identity binding report\n\n"
        f"- Run: `{report.run_id}`\n"
        f"- Decisions: {report.binding_count}\n"
        f"- Active decisions: {report.active_binding_count}\n"
        f"- Unresolved conflicts: {report.unresolved_conflict_count}\n"
        f"- Status: {report.status}\n"
    )


def persist_identity_binding_run(
    run: IdentityBindingRun,
    foundation: IdentityFoundationRun,
    clustering: ClusteringRun,
    diarization: DiarizationRun,
    destination: Path,
    *,
    predecessor: IdentityBindingRun | None = None,
) -> tuple[IdentityBindingRun, IdentityBindingReport, Path, bool]:
    destination = destination.expanduser().resolve()
    validate_identity_binding_run(
        run,
        foundation,
        clustering,
        diarization,
        predecessor=predecessor,
    )
    root = destination / "identity-bindings" / run.run_id
    run_path = root / "binding.json"
    report_path = root / "report.json"
    existing = (run_path.exists(), report_path.exists())
    if any(existing) and not all(existing):
        raise IdentityBindingIntegrityError(
            "cached identity binding run is incomplete"
        )
    expected_report = _report(run)
    if all(existing):
        stored = load_contract(run_path.read_bytes(), IdentityBindingRun)
        report = load_contract(report_path.read_bytes(), IdentityBindingReport)
        validate_identity_binding_run(
            stored,
            foundation,
            clustering,
            diarization,
            predecessor=predecessor,
            report=report,
        )
        if stored != run:
            raise IdentityBindingIntegrityError(
                "cached identity binding run is incompatible"
            )
        return stored, report, root, True
    _atomic(run_path, canonical_bytes(run))
    _atomic(report_path, canonical_bytes(expected_report))
    _atomic(
        root / "report.md",
        identity_binding_report_markdown(expected_report).encode("utf-8"),
    )
    return run, expected_report, root, False


def load_identity_binding_run(
    root: Path,
) -> tuple[IdentityBindingRun, IdentityBindingReport]:
    root = root.expanduser().resolve(strict=True)
    return (
        load_contract(
            (root / "binding.json").read_bytes(), IdentityBindingRun
        ),
        load_contract(
            (root / "report.json").read_bytes(), IdentityBindingReport
        ),
    )
