"""Deterministic assembly of layered participant identity views."""

from __future__ import annotations

import os
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .clustering import validate_clustering_run
from .clustering_contracts import (
    ClusterProposalDisposition,
    ClusteringRun,
)
from .identity import validate_identity_foundation
from .identity_binding import (
    _conflict_groups,
    active_bindings,
    validate_identity_binding_run,
)
from .identity_binding_contracts import IdentityBindingRun
from .identity_contracts import IdentityFoundationRun
from .identity_view_contracts import (
    IdentityView,
    IdentityViewAssembly,
    IdentityViewDisposition,
    IdentityViewEntry,
    IdentityViewKind,
    IdentityViewPolicy,
    IdentityViewReport,
)
from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase3_contracts import (
    BindingAction,
    DiarizationProviderResponse,
    DiarizationRun,
    IdentityScopeKind,
    ManualIdentityBinding,
    SpeakerTurn,
)
from .reference_comparison_contracts import (
    ReferenceComparisonRun,
    VoiceComparisonResult,
)


class IdentityViewIntegrityError(RuntimeError):
    """A reviewed identity view has invalid lineage or derived content."""


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


def _entry(
    view_kind: IdentityViewKind,
    target_artifact_id: str,
    target_kind: str,
    disposition: IdentityViewDisposition,
    **values,
) -> IdentityViewEntry:
    payload = {
        "target_artifact_id": target_artifact_id,
        "target_kind": target_kind,
        "disposition": disposition,
        **values,
    }
    return IdentityViewEntry(
        entry_id=typed_id(
            "identityviewentry",
            view_kind.value,
            payload,
        ),
        **payload,
    )


def _view(
    kind: IdentityViewKind,
    entries: tuple[IdentityViewEntry, ...],
    *,
    lineage: tuple[str, ...],
    findings: tuple[str, ...] = (),
    blocking_findings: tuple[str, ...] = (),
    trusted: bool = False,
    view_id: str | None = None,
) -> IdentityView:
    return IdentityView(
        view_id=view_id
        or typed_id(
            "identityview",
            kind.value,
            lineage,
            [item.model_dump(mode="json") for item in entries],
            findings,
            blocking_findings,
        ),
        kind=kind,
        entries=entries,
        findings=findings,
        blocking_findings=blocking_findings,
        trusted_for_participant_rendering=trusted and not blocking_findings,
    )


def _turn_cluster_map(
    clustering: ClusteringRun,
    diarization: DiarizationRun,
) -> dict[str, str | None]:
    by_observation = {
        item.observation_id: item.cluster_id
        for item in clustering.memberships
        if item.canonical
    }
    result: dict[str, str | None] = {}
    for turn in diarization.turns:
        clusters = {
            by_observation[item]
            for item in turn.observation_ids
            if item in by_observation
        }
        result[turn.turn_id] = next(iter(clusters)) if len(clusters) == 1 else None
    return result


def _binding_applies(
    binding: ManualIdentityBinding,
    turn: SpeakerTurn,
    cluster_id: str | None,
    diarization: DiarizationRun,
) -> bool:
    relevant = {
        turn.turn_id,
        *turn.observation_ids,
        diarization.source_id,
        diarization.corpus_id,
    }
    if cluster_id is not None:
        relevant.add(cluster_id)
    if binding.target_artifact_id not in relevant:
        return False
    scope = binding.scope
    if scope.kind == IdentityScopeKind.SPEAKER_TURN:
        return scope.target_id == turn.turn_id
    if scope.kind == IdentityScopeKind.OBSERVATION:
        return scope.target_id in turn.observation_ids
    if scope.kind == IdentityScopeKind.CLUSTER:
        return scope.target_id == cluster_id
    if scope.kind == IdentityScopeKind.RECORDING:
        return scope.target_id == diarization.source_id
    if scope.kind == IdentityScopeKind.CORPUS:
        return scope.target_id == diarization.corpus_id
    return False


def _overlap(left: SpeakerTurn, right: SpeakerTurn) -> bool:
    left_start = left.normalized_audio_interval.start_microseconds
    right_start = right.normalized_audio_interval.start_microseconds
    left_end = left_start + left.normalized_audio_interval.duration_microseconds
    right_end = right_start + right.normalized_audio_interval.duration_microseconds
    return max(left_start, right_start) < min(left_end, right_end)


def _manual_entries(
    binding_run: IdentityBindingRun,
    foundation: IdentityFoundationRun,
    clustering: ClusteringRun,
    diarization: DiarizationRun,
    turn_clusters: dict[str, str | None],
    policy: IdentityViewPolicy,
) -> tuple[
    tuple[IdentityViewEntry, ...],
    tuple[str, ...],
    tuple[str, ...],
]:
    identities = {item.identity_id: item for item in foundation.identities}
    active = active_bindings(binding_run)
    entries: list[IdentityViewEntry] = []
    assignments: dict[str, str] = {}
    findings: list[str] = []
    blocking = [
        (
            "Conflicting active manual bindings remain unresolved: "
            + ", ".join(group)
        )
        for group in _conflict_groups(active)
    ]
    for turn in diarization.turns:
        cluster_id = turn_clusters[turn.turn_id]
        applicable = tuple(
            item
            for item in active
            if item.action
            not in {
                BindingAction.MERGE_IDENTITY_PLACEHOLDERS,
                BindingAction.SPLIT_IDENTITY,
            }
            and _binding_applies(item, turn, cluster_id, diarization)
        )
        outcomes = {
            (
                "unknown"
                if item.action == BindingAction.MARK_UNKNOWN
                else "rejected"
                if item.action == BindingAction.REJECT_IDENTITY
                else "bound",
                item.identity_id,
            )
            for item in applicable
        }
        machine_label = cluster_id or "MACHINE: UNRESOLVED"
        identity_ids = tuple(
            sorted(
                {
                    item.identity_id
                    for item in applicable
                    if item.identity_id is not None
                }
            )
        )
        binding_ids = tuple(sorted(item.binding_id for item in applicable))
        if len(outcomes) > 1:
            disposition = IdentityViewDisposition.CONFLICTED
            reviewed_label = policy.conflict_label
            entry_findings = (
                "Multiple incompatible active manual outcomes apply.",
            )
            blocking.append(
                f"Speaker turn {turn.turn_id} has conflicting manual outcomes."
            )
        elif outcomes:
            outcome, identity_id = next(iter(outcomes))
            if outcome == "bound" and identity_id is not None:
                disposition = IdentityViewDisposition.REVIEWED_IDENTITY
                reviewed_label = (
                    policy.manual_label_prefix
                    + identities[identity_id].canonical_display_label
                )
                assignments[turn.turn_id] = identity_id
                entry_findings = ()
            elif outcome == "rejected":
                disposition = IdentityViewDisposition.REJECTED
                reviewed_label = policy.unknown_label
                entry_findings = (
                    "A candidate identity was rejected; no identity was substituted.",
                )
            else:
                disposition = IdentityViewDisposition.UNKNOWN
                reviewed_label = policy.unknown_label
                entry_findings = (
                    "Reviewer explicitly marked this assignment unknown.",
                )
        else:
            disposition = IdentityViewDisposition.UNKNOWN
            reviewed_label = None
            entry_findings = (
                "No active manual identity decision applies; machine label retained.",
            )
        entries.append(
            _entry(
                IdentityViewKind.MANUALLY_REVIEWED_IDENTITY,
                turn.turn_id,
                "speaker_turn",
                disposition,
                original_machine_label=machine_label,
                reviewed_label=reviewed_label,
                identity_ids=identity_ids,
                binding_ids=binding_ids,
                evidence_references=tuple(
                    sorted(
                        {
                            reference
                            for item in applicable
                            for reference in (
                                *item.supporting_evidence_references,
                                *item.contrary_evidence_acknowledged,
                            )
                        }
                    )
                ),
                findings=entry_findings,
            )
        )

    turns = {item.turn_id: item for item in diarization.turns}
    assigned = sorted(assignments)
    for index, left_id in enumerate(assigned):
        for right_id in assigned[index + 1 :]:
            if (
                assignments[left_id] == assignments[right_id]
                and turn_clusters[left_id] != turn_clusters[right_id]
                and _overlap(turns[left_id], turns[right_id])
            ):
                blocking.append(
                    "One participant identity is assigned to simultaneous "
                    f"independent turns {left_id} and {right_id}."
                )
    unresolved_proposals = [
        item.proposal_id
        for item in (*clustering.merge_proposals, *clustering.split_proposals)
        if item.disposition
        in {
            ClusterProposalDisposition.PROPOSED,
            ClusterProposalDisposition.REVIEW_REQUIRED,
        }
    ]
    if unresolved_proposals:
        findings.append(
            "Unresolved cluster merge or split proposals were preserved: "
            + ", ".join(unresolved_proposals)
        )
    return tuple(entries), tuple(findings), tuple(sorted(set(blocking)))


def assemble_identity_views(
    response: DiarizationProviderResponse,
    diarization: DiarizationRun,
    clustering: ClusteringRun,
    foundation: IdentityFoundationRun,
    binding_run: IdentityBindingRun,
    *,
    comparisons: ReferenceComparisonRun | None = None,
    policy: IdentityViewPolicy | None = None,
    created_at: datetime | None = None,
) -> IdentityViewAssembly:
    validate_clustering_run(clustering, diarization)
    validate_identity_foundation(foundation, clustering, diarization)
    validate_identity_binding_run(
        binding_run, foundation, clustering, diarization
    )
    if not binding_run.bindings:
        raise IdentityViewIntegrityError(
            "reviewed identity view requires at least one manual decision"
        )
    if response.response_id != diarization.response_id:
        raise IdentityViewIntegrityError(
            "provider response and canonical diarization lineage disagree"
        )
    if comparisons is not None:
        if canonical_hash(_integrity_payload(comparisons)) != (
            comparisons.integrity_sha256
        ):
            raise IdentityViewIntegrityError(
                "reference comparison integrity is invalid"
            )
        if (
            comparisons.clustering_run_id != clustering.run_id
            or comparisons.diarization_run_id != diarization.run_id
            or comparisons.identity_foundation_id != foundation.foundation_id
        ):
            raise IdentityViewIntegrityError(
                "reference comparison lineage is incompatible"
            )
    selected_policy = policy or IdentityViewPolicy()
    timestamp = created_at or datetime.now(timezone.utc)
    turn_clusters = _turn_cluster_map(clustering, diarization)
    lineage = (
        response.response_id,
        diarization.run_id,
        clustering.run_id,
        foundation.foundation_id,
        binding_run.run_id,
        comparisons.run_id if comparisons else "comparison-unavailable",
    )

    raw_entries = tuple(
        _entry(
            IdentityViewKind.RAW_PROVIDER_DIARIZATION,
            item.observation_id,
            "provider_observation",
            IdentityViewDisposition.INFORMATIONAL,
            original_machine_label=item.provider_speaker_label,
            evidence_references=tuple(
                reference
                for reference in (item.provider_reference,)
                if reference is not None
            ),
            findings=item.findings,
        )
        for item in response.observations
    )
    canonical_entries = tuple(
        _entry(
            IdentityViewKind.CANONICAL_MACHINE_DIARIZATION,
            turn.turn_id,
            "speaker_turn",
            (
                IdentityViewDisposition.MACHINE_CLUSTER
                if turn_clusters[turn.turn_id] is not None
                else IdentityViewDisposition.UNKNOWN
            ),
            original_machine_label=(
                turn_clusters[turn.turn_id] or "MACHINE: UNRESOLVED"
            ),
            evidence_references=turn.observation_ids,
            findings=turn.validation_findings,
        )
        for turn in diarization.turns
    )
    consistency_entries = tuple(
        _entry(
            IdentityViewKind.CLUSTER_CONSISTENCY,
            item.cluster_id,
            "cluster",
            (
                IdentityViewDisposition.UNRESOLVED_PROPOSAL
                if item.outlier_observation_ids
                or item.simultaneous_conflict_overlap_ids
                else IdentityViewDisposition.INFORMATIONAL
            ),
            original_machine_label=item.cluster_id,
            evidence_references=(
                *item.observation_ids,
                *item.simultaneous_conflict_overlap_ids,
            ),
            findings=(*item.findings, *item.limitations),
        )
        for item in clustering.consistency_results
    )
    unresolved_entries = tuple(
        item
        for item in canonical_entries
        if item.disposition == IdentityViewDisposition.UNKNOWN
    ) + tuple(
        _entry(
            IdentityViewKind.UNRESOLVED_SPEAKER,
            proposal.proposal_id,
            "cluster",
            IdentityViewDisposition.UNRESOLVED_PROPOSAL,
            evidence_references=(
                (
                    proposal.source_cluster_id,
                )
                if hasattr(proposal, "source_cluster_id")
                else proposal.source_cluster_ids
            ),
            findings=("Cluster proposal remains unapplied.",),
        )
        for proposal in (*clustering.merge_proposals, *clustering.split_proposals)
        if proposal.disposition
        in {
            ClusterProposalDisposition.PROPOSED,
            ClusterProposalDisposition.REVIEW_REQUIRED,
        }
    )
    hypothesis_entries = tuple(
        _entry(
            IdentityViewKind.IDENTITY_HYPOTHESIS,
            item.hypothesis_id,
            "identity_hypothesis",
            IdentityViewDisposition.INFORMATIONAL,
            identity_ids=(item.proposed_identity_id,),
            evidence_references=(
                *item.supporting_evidence_references,
                *item.contrary_evidence_references,
            ),
            findings=(
                f"Hypothesis disposition: {item.disposition.value}.",
                "Hypothesis is not a manual identity decision.",
            ),
        )
        for item in foundation.hypotheses
    )
    comparison_entries = tuple(
        _entry(
            IdentityViewKind.REFERENCE_COMPARISON,
            item.comparison_id,
            "reference_comparison",
            (
                IdentityViewDisposition.INVALID_EVIDENCE
                if item.result == VoiceComparisonResult.COMPARISON_INVALID
                else IdentityViewDisposition.INFORMATIONAL
            ),
            identity_ids=(item.proposed_identity_id,),
            evidence_references=(
                item.reference_id,
                *item.supporting_evidence_references,
                *item.contrary_evidence_references,
            ),
            findings=(
                f"Comparison result: {item.result.value}.",
                *item.quality_findings,
                *item.limitations,
            ),
        )
        for item in (comparisons.comparisons if comparisons else ())
    )
    history_entries = tuple(
        _entry(
            IdentityViewKind.BINDING_HISTORY,
            item.binding_id,
            "manual_binding",
            (
                IdentityViewDisposition.UNKNOWN
                if item.action == BindingAction.MARK_UNKNOWN
                else IdentityViewDisposition.REJECTED
                if item.action == BindingAction.REJECT_IDENTITY
                else IdentityViewDisposition.INFORMATIONAL
            ),
            reviewed_label=(
                selected_policy.unknown_label
                if item.action == BindingAction.MARK_UNKNOWN
                else None
            ),
            identity_ids=(
                (item.identity_id,) if item.identity_id is not None else ()
            ),
            binding_ids=(item.binding_id,),
            evidence_references=(
                *item.supporting_evidence_references,
                *item.contrary_evidence_acknowledged,
            ),
            findings=(
                f"Manual action: {item.action.value}.",
                f"Authored by {item.author_display_name} ({item.author_id}).",
            ),
        )
        for item in binding_run.bindings
    )
    manual_entries, manual_findings, manual_blocking = _manual_entries(
        binding_run,
        foundation,
        clustering,
        diarization,
        turn_clusters,
        selected_policy,
    )
    reviewed_view_id = binding_run.bindings[-1].resulting_identity_view_version_id
    views = (
        _view(
            IdentityViewKind.RAW_PROVIDER_DIARIZATION,
            raw_entries,
            lineage=lineage,
        ),
        _view(
            IdentityViewKind.CANONICAL_MACHINE_DIARIZATION,
            canonical_entries,
            lineage=lineage,
        ),
        _view(
            IdentityViewKind.CLUSTER_CONSISTENCY,
            consistency_entries,
            lineage=lineage,
            findings=(
                "Cluster consistency is acoustic evidence, not identity.",
            ),
        ),
        _view(
            IdentityViewKind.UNRESOLVED_SPEAKER,
            unresolved_entries,
            lineage=lineage,
            findings=("Unknown and unapplied cluster proposals are preserved.",),
        ),
        _view(
            IdentityViewKind.IDENTITY_HYPOTHESIS,
            hypothesis_entries,
            lineage=lineage,
            findings=("Hypotheses remain separate from reviewed decisions.",),
        ),
        _view(
            IdentityViewKind.REFERENCE_COMPARISON,
            comparison_entries,
            lineage=lineage,
            findings=(
                (
                    "No compatible reference-comparison run was supplied."
                    if comparisons is None
                    else "Comparison evidence remains nonbinding."
                ),
            ),
        ),
        _view(
            IdentityViewKind.MANUALLY_REVIEWED_IDENTITY,
            manual_entries,
            lineage=lineage,
            findings=manual_findings,
            blocking_findings=manual_blocking,
            trusted=True,
            view_id=reviewed_view_id,
        ),
        _view(
            IdentityViewKind.BINDING_HISTORY,
            history_entries,
            lineage=lineage,
            findings=("All manual decisions are retained in ledger order.",),
        ),
    )
    configuration_hash = canonical_hash(
        {
            "operation": "participant.identity.view_assembly",
            "lineage": lineage,
            "policy": selected_policy.model_dump(mode="json"),
        }
    )
    assembly = _seal(
        IdentityViewAssembly,
        {
            "assembly_id": typed_id(
                "identityviewassembly",
                lineage,
                configuration_hash,
                [item.model_dump(mode="json") for item in views],
            ),
            "corpus_id": diarization.corpus_id,
            "provider_response_id": response.response_id,
            "provider_response_sha256": canonical_hash(
                response.model_dump(mode="json")
            ),
            "diarization_run_id": diarization.run_id,
            "clustering_run_id": clustering.run_id,
            "foundation_id": foundation.foundation_id,
            "binding_run_id": binding_run.run_id,
            "comparison_run_id": comparisons.run_id if comparisons else None,
            "policy": selected_policy,
            "configuration_hash": configuration_hash,
            "views": views,
            "created_at": timestamp,
        },
    )
    validate_identity_view_assembly(
        assembly,
        response,
        diarization,
        clustering,
        foundation,
        binding_run,
        comparisons=comparisons,
    )
    return assembly


def reviewed_identity_view(assembly: IdentityViewAssembly) -> IdentityView:
    return next(
        item
        for item in assembly.views
        if item.kind == IdentityViewKind.MANUALLY_REVIEWED_IDENTITY
    )


def _report(assembly: IdentityViewAssembly) -> IdentityViewReport:
    reviewed = reviewed_identity_view(assembly)
    counts = Counter(item.disposition for item in reviewed.entries)
    blocking = sum(len(item.blocking_findings) for item in assembly.views)
    status = (
        "blocked"
        if reviewed.blocking_findings
        else "warning"
        if any(
            item.disposition
            in {
                IdentityViewDisposition.UNKNOWN,
                IdentityViewDisposition.UNRESOLVED_PROPOSAL,
                IdentityViewDisposition.INVALID_EVIDENCE,
            }
            for view in assembly.views
            for item in view.entries
        )
        else "complete"
    )
    return _seal(
        IdentityViewReport,
        {
            "report_id": typed_id(
                "identityviewreport", assembly.assembly_id
            ),
            "assembly_id": assembly.assembly_id,
            "reviewed_view_id": reviewed.view_id,
            "generated_at": assembly.created_at,
            "entry_count": sum(len(item.entries) for item in assembly.views),
            "reviewed_identity_count": counts[
                IdentityViewDisposition.REVIEWED_IDENTITY
            ],
            "unknown_count": counts[IdentityViewDisposition.UNKNOWN],
            "conflict_count": counts[IdentityViewDisposition.CONFLICTED],
            "blocking_finding_count": blocking,
            "findings": (
                "Eight identity evidence and decision layers were assembled.",
                "Machine labels and reviewed labels remain separate fields.",
            ),
            "limitations": (
                "This artifact does not rewrite Phase 2 transcript evidence.",
                "Speaker transcripts are separate derived views; participant-"
                "labeled subtitle rendering remains a later derivative.",
            ),
            "status": status,
        },
    )


def validate_identity_view_assembly(
    assembly: IdentityViewAssembly,
    response: DiarizationProviderResponse,
    diarization: DiarizationRun,
    clustering: ClusteringRun,
    foundation: IdentityFoundationRun,
    binding_run: IdentityBindingRun,
    *,
    comparisons: ReferenceComparisonRun | None = None,
    report: IdentityViewReport | None = None,
) -> None:
    if canonical_hash(_integrity_payload(assembly)) != assembly.integrity_sha256:
        raise IdentityViewIntegrityError("identity-view integrity is invalid")
    if (
        assembly.provider_response_id != response.response_id
        or assembly.provider_response_sha256
        != canonical_hash(response.model_dump(mode="json"))
        or assembly.diarization_run_id != diarization.run_id
        or assembly.clustering_run_id != clustering.run_id
        or assembly.foundation_id != foundation.foundation_id
        or assembly.binding_run_id != binding_run.run_id
        or assembly.comparison_run_id
        != (comparisons.run_id if comparisons else None)
    ):
        raise IdentityViewIntegrityError("identity-view lineage is incompatible")
    if response.response_id != diarization.response_id:
        raise IdentityViewIntegrityError(
            "provider response and canonical diarization lineage disagree"
        )
    validate_clustering_run(clustering, diarization)
    validate_identity_foundation(foundation, clustering, diarization)
    validate_identity_binding_run(
        binding_run, foundation, clustering, diarization
    )
    if comparisons is not None and (
        canonical_hash(_integrity_payload(comparisons))
        != comparisons.integrity_sha256
    ):
        raise IdentityViewIntegrityError(
            "reference comparison integrity is invalid"
        )
    if comparisons is not None and (
        comparisons.clustering_run_id != clustering.run_id
        or comparisons.diarization_run_id != diarization.run_id
        or comparisons.identity_foundation_id != foundation.foundation_id
    ):
        raise IdentityViewIntegrityError(
            "reference comparison lineage is incompatible"
        )
    if not binding_run.bindings:
        raise IdentityViewIntegrityError(
            "reviewed identity view requires at least one manual decision"
        )
    identities = {item.identity_id for item in foundation.identities}
    known_targets = {
        item.turn_id for item in diarization.turns
    } | {
        item.observation_id for item in diarization.observations
    } | {
        item.cluster_id for item in clustering.clusters
    }
    by_kind = {item.kind: item for item in assembly.views}
    expected_targets = {
        IdentityViewKind.RAW_PROVIDER_DIARIZATION: {
            item.observation_id for item in response.observations
        },
        IdentityViewKind.CANONICAL_MACHINE_DIARIZATION: {
            item.turn_id for item in diarization.turns
        },
        IdentityViewKind.MANUALLY_REVIEWED_IDENTITY: {
            item.turn_id for item in diarization.turns
        },
        IdentityViewKind.IDENTITY_HYPOTHESIS: {
            item.hypothesis_id for item in foundation.hypotheses
        },
        IdentityViewKind.REFERENCE_COMPARISON: {
            item.comparison_id
            for item in (comparisons.comparisons if comparisons else ())
        },
        IdentityViewKind.BINDING_HISTORY: {
            item.binding_id for item in binding_run.bindings
        },
    }
    for kind, targets in expected_targets.items():
        if {
            item.target_artifact_id for item in by_kind[kind].entries
        } != targets:
            raise IdentityViewIntegrityError(
                f"{kind.value} view does not match its pinned evidence"
            )
    turn_clusters = _turn_cluster_map(clustering, diarization)
    expected_entries, expected_findings, expected_blocking = _manual_entries(
        binding_run,
        foundation,
        clustering,
        diarization,
        turn_clusters,
        assembly.policy,
    )
    reviewed = by_kind[IdentityViewKind.MANUALLY_REVIEWED_IDENTITY]
    if (
        reviewed.view_id
        != binding_run.bindings[-1].resulting_identity_view_version_id
        or reviewed.entries != expected_entries
        or reviewed.findings != expected_findings
        or reviewed.blocking_findings != expected_blocking
        or reviewed.trusted_for_participant_rendering != (not expected_blocking)
    ):
        raise IdentityViewIntegrityError(
            "manually reviewed identity view is not the derived ledger state"
        )
    for view in assembly.views:
        for item in view.entries:
            if not set(item.identity_ids).issubset(identities):
                raise IdentityViewIntegrityError(
                    "identity-view entry references an unknown identity"
                )
            if (
                item.target_kind
                in {"speaker_turn", "observation", "cluster"}
                and item.target_artifact_id not in known_targets
                and item.disposition
                != IdentityViewDisposition.UNRESOLVED_PROPOSAL
            ):
                raise IdentityViewIntegrityError(
                    "identity-view entry references unknown diarization evidence"
                )
    if report is not None and (
        canonical_hash(_integrity_payload(report)) != report.integrity_sha256
        or report != _report(assembly)
    ):
        raise IdentityViewIntegrityError(
            "identity-view report integrity or projection is invalid"
        )


def identity_view_report_markdown(report: IdentityViewReport) -> str:
    return (
        "# Phase 3 identity-view assembly report\n\n"
        f"- Assembly: `{report.assembly_id}`\n"
        f"- Reviewed view: `{report.reviewed_view_id}`\n"
        f"- Entries: {report.entry_count}\n"
        f"- Reviewed identities: {report.reviewed_identity_count}\n"
        f"- Unknown: {report.unknown_count}\n"
        f"- Conflicts: {report.conflict_count}\n"
        f"- Status: {report.status}\n"
    )


def persist_identity_view_assembly(
    assembly: IdentityViewAssembly,
    response: DiarizationProviderResponse,
    diarization: DiarizationRun,
    clustering: ClusteringRun,
    foundation: IdentityFoundationRun,
    binding_run: IdentityBindingRun,
    destination: Path,
    *,
    comparisons: ReferenceComparisonRun | None = None,
) -> tuple[IdentityViewAssembly, IdentityViewReport, Path, bool]:
    destination = destination.expanduser().resolve()
    validate_identity_view_assembly(
        assembly,
        response,
        diarization,
        clustering,
        foundation,
        binding_run,
        comparisons=comparisons,
    )
    root = destination / "identity-views" / assembly.assembly_id
    assembly_path = root / "assembly.json"
    report_path = root / "report.json"
    existing = (assembly_path.exists(), report_path.exists())
    if any(existing) and not all(existing):
        raise IdentityViewIntegrityError(
            "cached identity-view assembly is incomplete"
        )
    expected_report = _report(assembly)
    if all(existing):
        stored = load_contract(
            assembly_path.read_bytes(), IdentityViewAssembly
        )
        report = load_contract(
            report_path.read_bytes(), IdentityViewReport
        )
        validate_identity_view_assembly(
            stored,
            response,
            diarization,
            clustering,
            foundation,
            binding_run,
            comparisons=comparisons,
            report=report,
        )
        if stored != assembly:
            raise IdentityViewIntegrityError(
                "cached identity-view assembly is incompatible"
            )
        return stored, report, root, True
    _atomic(assembly_path, canonical_bytes(assembly))
    _atomic(report_path, canonical_bytes(expected_report))
    _atomic(
        root / "report.md",
        identity_view_report_markdown(expected_report).encode("utf-8"),
    )
    return assembly, expected_report, root, False


def load_identity_view_assembly(
    root: Path,
) -> tuple[IdentityViewAssembly, IdentityViewReport]:
    root = root.expanduser().resolve(strict=True)
    return (
        load_contract(
            (root / "assembly.json").read_bytes(), IdentityViewAssembly
        ),
        load_contract(
            (root / "report.json").read_bytes(), IdentityViewReport
        ),
    )
