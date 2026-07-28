"""Append-only scoped participant identities and bounded hypotheses."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .clustering import validate_clustering_run
from .clustering_contracts import ClusteringRun
from .identity_contracts import (
    IdentityConflict,
    IdentityConflictKind,
    IdentityFoundationPolicy,
    IdentityFoundationRun,
    ParticipantIdentityReport,
)
from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase2_contracts import ConfidenceMeasure, ConfidenceOrigin
from .phase3_contracts import (
    DiarizationRun,
    IdentityHypothesis,
    IdentityHypothesisDisposition,
    IdentityHypothesisSource,
    IdentityKind,
    IdentityScope,
    IdentityScopeKind,
    IdentityStatus,
    ParticipantIdentity,
)


class IdentityFoundationIntegrityError(RuntimeError):
    """Identity evidence violates lineage, scope, or append-only rules."""


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


def unavailable_support(dimension: str) -> ConfidenceMeasure:
    return ConfidenceMeasure(
        origin=ConfidenceOrigin.UNAVAILABLE,
        basis=f"No {dimension} support was supplied for this hypothesis.",
    )


def _known_targets(
    clustering: ClusteringRun,
    diarization: DiarizationRun,
) -> dict[IdentityScopeKind, set[str]]:
    return {
        IdentityScopeKind.OBSERVATION: {
            item.observation_id for item in diarization.observations
        },
        IdentityScopeKind.SPEAKER_TURN: {
            item.turn_id for item in diarization.turns
        },
        IdentityScopeKind.CLUSTER: {
            item.cluster_id for item in clustering.clusters
        },
        IdentityScopeKind.RECORDING: {diarization.source_id},
        IdentityScopeKind.CORPUS: {diarization.corpus_id},
        IdentityScopeKind.LOCAL_SEGMENT: set(),
        IdentityScopeKind.RECORDING_SERIES: set(),
    }


def _validate_scope(
    scope: IdentityScope,
    clustering: ClusteringRun,
    diarization: DiarizationRun,
) -> None:
    targets = _known_targets(clustering, diarization)
    if scope.target_id not in targets[scope.kind]:
        if scope.kind in {
            IdentityScopeKind.LOCAL_SEGMENT,
            IdentityScopeKind.RECORDING_SERIES,
        }:
            raise IdentityFoundationIntegrityError(
                f"{scope.kind.value} scope is not supported in this slice"
            )
        raise IdentityFoundationIntegrityError(
            f"identity scope references unknown {scope.kind.value}"
        )


def validate_identity_foundation(
    run: IdentityFoundationRun,
    clustering: ClusteringRun,
    diarization: DiarizationRun,
    *,
    predecessor: IdentityFoundationRun | None = None,
    report: ParticipantIdentityReport | None = None,
) -> None:
    if canonical_hash(_integrity_payload(run)) != run.integrity_sha256:
        raise IdentityFoundationIntegrityError(
            "identity foundation integrity is invalid"
        )
    validate_clustering_run(clustering, diarization)
    if (
        run.clustering_run_id != clustering.run_id
        or run.diarization_run_id != diarization.run_id
        or run.corpus_id != diarization.corpus_id
    ):
        raise IdentityFoundationIntegrityError(
            "identity foundation lineage is incompatible"
        )
    if predecessor is not None:
        validate_identity_foundation(predecessor, clustering, diarization)
        if run.predecessor_foundation_id != predecessor.foundation_id:
            raise IdentityFoundationIntegrityError(
                "identity foundation predecessor lineage is invalid"
            )
        old_identities = {
            item.identity_id: item for item in predecessor.identities
        }
        old_hypotheses = {
            item.hypothesis_id: item for item in predecessor.hypotheses
        }
        old_conflicts = {
            item.conflict_id: item for item in predecessor.conflicts
        }
        current_identities = {item.identity_id: item for item in run.identities}
        current_hypotheses = {
            item.hypothesis_id: item for item in run.hypotheses
        }
        current_conflicts = {item.conflict_id: item for item in run.conflicts}
        if (
            any(current_identities.get(key) != value for key, value in old_identities.items())
            or any(current_hypotheses.get(key) != value for key, value in old_hypotheses.items())
            or any(current_conflicts.get(key) != value for key, value in old_conflicts.items())
        ):
            raise IdentityFoundationIntegrityError(
                "identity foundation successor rewrites prior evidence"
            )

    identities = {item.identity_id: item for item in run.identities}
    hypotheses = {item.hypothesis_id: item for item in run.hypotheses}
    for identity in run.identities:
        _validate_scope(identity.scope, clustering, diarization)
        if (
            identity.supersedes_identity_id is not None
            and identity.supersedes_identity_id not in identities
        ):
            raise IdentityFoundationIntegrityError(
                "identity supersedes unknown evidence"
            )
    known_artifacts = set().union(*_known_targets(clustering, diarization).values())
    for hypothesis in run.hypotheses:
        _validate_scope(hypothesis.scope, clustering, diarization)
        if (
            hypothesis.proposed_identity_id not in identities
            or hypothesis.target_artifact_id not in known_artifacts
            or hypothesis.hypothesis_id
            in hypothesis.competing_hypothesis_ids
            or not set(hypothesis.competing_hypothesis_ids).issubset(hypotheses)
        ):
            raise IdentityFoundationIntegrityError(
                "identity hypothesis references incompatible evidence"
            )
    for conflict in run.conflicts:
        if canonical_hash(_integrity_payload(conflict)) != (
            conflict.integrity_sha256
        ):
            raise IdentityFoundationIntegrityError(
                "identity conflict integrity is invalid"
            )
        if (
            not set(conflict.identity_ids).issubset(identities)
            or not set(conflict.hypothesis_ids).issubset(hypotheses)
        ):
            raise IdentityFoundationIntegrityError(
                "identity conflict references unknown evidence"
            )
    if report is not None and (
        canonical_hash(_integrity_payload(report)) != report.integrity_sha256
        or report.foundation_id != run.foundation_id
        or report.clustering_run_id != run.clustering_run_id
        or report.corpus_id != run.corpus_id
    ):
        raise IdentityFoundationIntegrityError(
            "participant identity report integrity or lineage is invalid"
        )


def _build_run(
    clustering: ClusteringRun,
    diarization: DiarizationRun,
    *,
    predecessor: IdentityFoundationRun | None,
    identities: tuple[ParticipantIdentity, ...],
    hypotheses: tuple[IdentityHypothesis, ...],
    conflicts: tuple[IdentityConflict, ...],
    policy: IdentityFoundationPolicy,
    created_at: datetime,
) -> IdentityFoundationRun:
    configuration_hash = canonical_hash(
        {
            "operation": "participant.identity.foundation",
            "clustering_run_id": clustering.run_id,
            "clustering_integrity_sha256": clustering.integrity_sha256,
            "policy": policy.model_dump(mode="json"),
        }
    )
    foundation_id = typed_id(
        "identityfoundation",
        clustering.run_id,
        predecessor.foundation_id if predecessor else None,
        [item.model_dump(mode="json") for item in identities],
        [item.model_dump(mode="json") for item in hypotheses],
        [item.model_dump(mode="json") for item in conflicts],
        configuration_hash,
    )
    return _seal(
        IdentityFoundationRun,
        {
            "foundation_id": foundation_id,
            "predecessor_foundation_id": (
                predecessor.foundation_id if predecessor else None
            ),
            "clustering_run_id": clustering.run_id,
            "diarization_run_id": diarization.run_id,
            "corpus_id": diarization.corpus_id,
            "policy": policy,
            "configuration_hash": configuration_hash,
            "identities": identities,
            "hypotheses": hypotheses,
            "conflicts": conflicts,
            "created_at": created_at,
        },
    )


def add_participant_identity(
    clustering: ClusteringRun,
    diarization: DiarizationRun,
    *,
    canonical_display_label: str,
    identity_kind: IdentityKind,
    information_source: str,
    scope: IdentityScope,
    provenance_references: tuple[str, ...],
    alternate_labels: tuple[str, ...] = (),
    predecessor: IdentityFoundationRun | None = None,
    policy: IdentityFoundationPolicy | None = None,
    created_at: datetime | None = None,
) -> tuple[IdentityFoundationRun, ParticipantIdentity]:
    policy = policy or IdentityFoundationPolicy()
    validate_clustering_run(clustering, diarization)
    if predecessor is not None:
        validate_identity_foundation(predecessor, clustering, diarization)
    _validate_scope(scope, clustering, diarization)
    if not provenance_references:
        raise ValueError("participant identity provenance is required")
    timestamp = created_at or datetime.now(timezone.utc)
    identity_id = typed_id(
        "identity",
        clustering.run_id,
        canonical_display_label,
        identity_kind.value,
        information_source,
        scope.model_dump(mode="json"),
        alternate_labels,
        provenance_references,
    )
    existing = predecessor.identities if predecessor else ()
    if any(item.identity_id == identity_id for item in existing):
        raise IdentityFoundationIntegrityError(
            "participant identity already exists in this foundation"
        )
    identity = ParticipantIdentity(
        identity_id=identity_id,
        canonical_display_label=canonical_display_label,
        alternate_labels=alternate_labels,
        identity_kind=identity_kind,
        information_source=information_source,
        scope=scope,
        status=(
            IdentityStatus.UNRESOLVED
            if identity_kind == IdentityKind.UNRESOLVED_PLACEHOLDER
            else IdentityStatus.PROVISIONAL
        ),
        provenance_references=provenance_references,
        created_at=timestamp,
    )
    conflicts = list(predecessor.conflicts if predecessor else ())
    ambiguous = tuple(
        item
        for item in existing
        if item.canonical_display_label.casefold()
        == canonical_display_label.casefold()
        and item.identity_id != identity.identity_id
    )
    if ambiguous:
        conflicts.append(
            _seal(
                IdentityConflict,
                {
                    "conflict_id": typed_id(
                        "identityconflict",
                        "ambiguous-label",
                        identity.identity_id,
                        [item.identity_id for item in ambiguous],
                    ),
                    "kind": IdentityConflictKind.AMBIGUOUS_DISPLAY_LABEL,
                    "target_artifact_id": scope.target_id,
                    "identity_ids": tuple(
                        sorted(
                            {
                                identity.identity_id,
                                *(item.identity_id for item in ambiguous),
                            }
                        )
                    ),
                    "hypothesis_ids": (),
                    "finding": (
                        "Multiple scoped identity entities share a display "
                        "label; no equivalence is inferred."
                    ),
                    "created_at": timestamp,
                },
            )
        )
    run = _build_run(
        clustering,
        diarization,
        predecessor=predecessor,
        identities=(*existing, identity),
        hypotheses=predecessor.hypotheses if predecessor else (),
        conflicts=tuple(conflicts),
        policy=policy,
        created_at=timestamp,
    )
    validate_identity_foundation(
        run, clustering, diarization, predecessor=predecessor
    )
    return run, identity


def add_identity_hypothesis(
    predecessor: IdentityFoundationRun,
    clustering: ClusteringRun,
    diarization: DiarizationRun,
    *,
    target_artifact_id: str,
    proposed_identity_id: str,
    source: IdentityHypothesisSource,
    scope: IdentityScope,
    supporting_evidence_references: tuple[str, ...],
    contrary_evidence_references: tuple[str, ...] = (),
    acoustic_support: ConfidenceMeasure | None = None,
    contextual_support: ConfidenceMeasure | None = None,
    documentary_support: ConfidenceMeasure | None = None,
    manual_assertion_support: ConfidenceMeasure | None = None,
    verified_reference_comparison_id: str | None = None,
    creation_process: str,
    disposition: IdentityHypothesisDisposition = (
        IdentityHypothesisDisposition.PROPOSED
    ),
    created_at: datetime | None = None,
) -> tuple[IdentityFoundationRun, IdentityHypothesis]:
    validate_identity_foundation(predecessor, clustering, diarization)
    _validate_scope(scope, clustering, diarization)
    known_artifacts = set().union(*_known_targets(clustering, diarization).values())
    if target_artifact_id not in known_artifacts:
        raise IdentityFoundationIntegrityError(
            "identity hypothesis target is unknown"
        )
    if proposed_identity_id not in {
        item.identity_id for item in predecessor.identities
    }:
        raise IdentityFoundationIntegrityError(
            "identity hypothesis proposes an unknown identity"
        )
    if not supporting_evidence_references:
        raise ValueError("identity hypothesis requires supporting evidence")
    reference_comparison = (
        source == IdentityHypothesisSource.REFERENCE_VOICE_COMPARISON
    )
    if reference_comparison and (
        verified_reference_comparison_id is None
        or verified_reference_comparison_id
        not in supporting_evidence_references
        or acoustic_support is None
    ):
        raise IdentityFoundationIntegrityError(
            "reference-voice hypothesis requires verified acoustic comparison"
        )
    if not reference_comparison and verified_reference_comparison_id is not None:
        raise IdentityFoundationIntegrityError(
            "verified comparison is valid only for reference-voice source"
        )
    timestamp = created_at or datetime.now(timezone.utc)
    supports = {
        "acoustic": acoustic_support or unavailable_support("acoustic"),
        "contextual": contextual_support or unavailable_support("contextual"),
        "documentary": documentary_support or unavailable_support("documentary"),
        "manual": manual_assertion_support or unavailable_support("manual"),
    }
    competing = tuple(
        item
        for item in predecessor.hypotheses
        if item.target_artifact_id == target_artifact_id
        and item.scope == scope
        and item.proposed_identity_id != proposed_identity_id
        and item.disposition
        not in {
            IdentityHypothesisDisposition.REJECTED,
            IdentityHypothesisDisposition.SUPERSEDED,
        }
    )
    hypothesis_id = typed_id(
        "identityhyp",
        predecessor.foundation_id,
        target_artifact_id,
        proposed_identity_id,
        source.value,
        supporting_evidence_references,
        contrary_evidence_references,
        {key: value.model_dump(mode="json") for key, value in supports.items()},
        scope.model_dump(mode="json"),
        creation_process,
        disposition.value,
    )
    hypothesis = IdentityHypothesis(
        hypothesis_id=hypothesis_id,
        target_artifact_id=target_artifact_id,
        proposed_identity_id=proposed_identity_id,
        source=source,
        supporting_evidence_references=supporting_evidence_references,
        contrary_evidence_references=contrary_evidence_references,
        acoustic_support=supports["acoustic"],
        contextual_support=supports["contextual"],
        documentary_support=supports["documentary"],
        manual_assertion_support=supports["manual"],
        scope=scope,
        competing_hypothesis_ids=tuple(
            item.hypothesis_id for item in competing
        ),
        creation_process=creation_process,
        disposition=disposition,
        created_at=timestamp,
    )
    conflicts = list(predecessor.conflicts)
    if competing:
        conflicts.append(
            _seal(
                IdentityConflict,
                {
                    "conflict_id": typed_id(
                        "identityconflict",
                        target_artifact_id,
                        hypothesis_id,
                        [item.hypothesis_id for item in competing],
                    ),
                    "kind": IdentityConflictKind.COMPETING_HYPOTHESES,
                    "target_artifact_id": target_artifact_id,
                    "identity_ids": tuple(
                        sorted(
                            {
                                proposed_identity_id,
                                *(
                                    item.proposed_identity_id
                                    for item in competing
                                ),
                            }
                        )
                    ),
                    "hypothesis_ids": tuple(
                        sorted(
                            {
                                hypothesis_id,
                                *(item.hypothesis_id for item in competing),
                            }
                        )
                    ),
                    "finding": (
                        "Competing scoped identity hypotheses remain "
                        "unresolved; no identity was selected."
                    ),
                    "created_at": timestamp,
                },
            )
        )
    run = _build_run(
        clustering,
        diarization,
        predecessor=predecessor,
        identities=predecessor.identities,
        hypotheses=(*predecessor.hypotheses, hypothesis),
        conflicts=tuple(conflicts),
        policy=predecessor.policy,
        created_at=timestamp,
    )
    validate_identity_foundation(
        run, clustering, diarization, predecessor=predecessor
    )
    return run, hypothesis


def _report(run: IdentityFoundationRun) -> ParticipantIdentityReport:
    unresolved_identities = sum(
        item.status in {IdentityStatus.PROVISIONAL, IdentityStatus.UNRESOLVED}
        for item in run.identities
    )
    unresolved_hypotheses = sum(
        item.disposition
        in {
            IdentityHypothesisDisposition.PROPOSED,
            IdentityHypothesisDisposition.CONTESTED,
            IdentityHypothesisDisposition.UNRESOLVED,
        }
        for item in run.hypotheses
    )
    conflicts = sum(not item.resolved for item in run.conflicts)
    status = (
        "warning"
        if conflicts or unresolved_hypotheses or unresolved_identities
        else "complete"
    )
    return _seal(
        ParticipantIdentityReport,
        {
            "report_id": typed_id("identityreport", run.foundation_id),
            "foundation_id": run.foundation_id,
            "clustering_run_id": run.clustering_run_id,
            "corpus_id": run.corpus_id,
            "generated_at": run.created_at,
            "identity_count": len(run.identities),
            "hypothesis_count": len(run.hypotheses),
            "unresolved_identity_count": unresolved_identities,
            "unresolved_hypothesis_count": unresolved_hypotheses,
            "unresolved_conflict_count": conflicts,
            "findings": tuple(item.finding for item in run.conflicts),
            "limitations": (
                "Identity entities exist only for scoped attribution.",
                "Hypotheses are not confirmed bindings.",
                "No automatic identity binding is applied.",
                "No biographical, political, psychological, or credibility "
                "profile is represented.",
            ),
            "status": status,
        },
    )


def identity_report_markdown(report: ParticipantIdentityReport) -> str:
    return "\n".join(
        [
            "# Phase 3 participant-identity foundation report",
            "",
            f"Status: **{report.status.upper()}**",
            "",
            f"Foundation: `{report.foundation_id}`",
            "",
            f"- Scoped identities: {report.identity_count}",
            f"- Bounded hypotheses: {report.hypothesis_count}",
            f"- Unresolved conflicts: {report.unresolved_conflict_count}",
            "",
            "Hypotheses are not participant bindings.",
            "",
        ]
    )


def persist_identity_foundation(
    run: IdentityFoundationRun,
    clustering: ClusteringRun,
    diarization: DiarizationRun,
    destination: Path,
    *,
    predecessor: IdentityFoundationRun | None = None,
) -> tuple[IdentityFoundationRun, ParticipantIdentityReport, Path, bool]:
    destination = destination.expanduser().resolve()
    validate_identity_foundation(
        run, clustering, diarization, predecessor=predecessor
    )
    root = destination / "identity-foundations" / run.foundation_id
    foundation_path = root / "foundation.json"
    report_path = root / "report.json"
    existing = (foundation_path.exists(), report_path.exists())
    if any(existing) and not all(existing):
        raise IdentityFoundationIntegrityError(
            "cached identity foundation is incomplete"
        )
    expected_report = _report(run)
    if all(existing):
        stored = load_contract(
            foundation_path.read_bytes(), IdentityFoundationRun
        )
        report = load_contract(
            report_path.read_bytes(), ParticipantIdentityReport
        )
        validate_identity_foundation(
            stored,
            clustering,
            diarization,
            predecessor=predecessor,
            report=report,
        )
        if stored != run or report != expected_report:
            raise IdentityFoundationIntegrityError(
                "cached identity foundation is incompatible"
            )
        return stored, report, root, True
    _atomic(foundation_path, canonical_bytes(run))
    _atomic(report_path, canonical_bytes(expected_report))
    _atomic(
        root / "report.md",
        identity_report_markdown(expected_report).encode("utf-8"),
    )
    return run, expected_report, root, False


def load_identity_foundation(
    root: Path,
) -> tuple[IdentityFoundationRun, ParticipantIdentityReport]:
    root = root.expanduser().resolve(strict=True)
    return (
        load_contract(
            (root / "foundation.json").read_bytes(), IdentityFoundationRun
        ),
        load_contract(
            (root / "report.json").read_bytes(), ParticipantIdentityReport
        ),
    )
