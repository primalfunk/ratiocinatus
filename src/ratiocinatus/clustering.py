"""Deterministic Phase 3 provisional acoustic-clustering kernel."""

from __future__ import annotations

import os
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .clustering_contracts import (
    ClusterConsistencyDisposition,
    ClusterConsistencyResult,
    ClusterConsistencySummary,
    ClusterProposalDisposition,
    ClusterSplitPartition,
    ClusterSplitProposal,
    ClusteringPolicy,
    ClusteringReport,
    ClusteringRun,
)
from .diarization import (
    validate_diarization_response,
    validate_diarization_run,
)
from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase2_contracts import ConfidenceMeasure, ConfidenceOrigin
from .phase3_contracts import (
    ClusterMembership,
    ClusterStatus,
    DiarizationCapability,
    DiarizationProviderCapabilities,
    DiarizationProviderResponse,
    DiarizationRequest,
    DiarizationRun,
    ObservationUsability,
    SpeakerCluster,
)


class ClusteringIntegrityError(RuntimeError):
    """Provisional clustering violates acoustic-evidence boundaries."""


class ClusteringUnavailable(RuntimeError):
    """The selected provider does not declare acoustic clustering."""


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


def _confidence(
    values: tuple[ConfidenceMeasure, ...],
    basis: str,
) -> ConfidenceMeasure:
    available = [item.value for item in values if item.value is not None]
    if not available:
        return ConfidenceMeasure(
            origin=ConfidenceOrigin.UNAVAILABLE,
            basis=basis + "; provider supplied no comparable score",
        )
    return ConfidenceMeasure(
        value=sum(available) / len(available),
        origin=ConfidenceOrigin.DERIVED,
        basis=basis + f"; arithmetic mean of {len(available)} provider scores",
    )


def _split_confidence(overlaps) -> ConfidenceMeasure:
    values = [
        item.overlap_confidence.value
        for item in overlaps
        if item.overlap_confidence.value is not None
    ]
    if not values:
        return ConfidenceMeasure(
            origin=ConfidenceOrigin.UNAVAILABLE,
            basis="simultaneous-self conflict exists without comparable score",
        )
    return ConfidenceMeasure(
        value=max(values),
        origin=ConfidenceOrigin.DERIVED,
        basis=(
            "maximum provider overlap confidence among simultaneous-self "
            "conflicts; not calibrated as split correctness"
        ),
    )


def form_clustering_run(
    request: DiarizationRequest,
    response: DiarizationProviderResponse,
    diarization: DiarizationRun,
    capabilities: DiarizationProviderCapabilities,
    *,
    policy: ClusteringPolicy | None = None,
) -> ClusteringRun:
    """Normalize declared provider acoustic labels into provisional clusters."""

    policy = policy or ClusteringPolicy()
    if capabilities.identity != response.provider:
        raise ClusteringIntegrityError(
            "clustering capabilities belong to another provider"
        )
    if (
        not capabilities.available
        or DiarizationCapability.SPEAKER_CLUSTERING
        not in capabilities.capabilities
    ):
        raise ClusteringUnavailable(
            "provider does not declare available speaker clustering"
        )
    if (
        diarization.request_id != request.request_id
        or diarization.response_id != response.response_id
        or diarization.corpus_id != request.corpus_id
    ):
        raise ClusteringIntegrityError(
            "diarization and provider evidence lineage is incompatible"
        )

    configuration_hash = canonical_hash(
        {
            "operation": "speaker.cluster",
            "diarization_run_id": diarization.run_id,
            "diarization_integrity_sha256": diarization.integrity_sha256,
            "provider_evidence_sha256": response.normalized_evidence_sha256,
            "provider_capabilities": capabilities.model_dump(mode="json"),
            "policy": policy.model_dump(mode="json"),
        }
    )
    run_id = typed_id(
        "clusterrun",
        diarization.run_id,
        configuration_hash,
    )

    canonical = {item.observation_id: item for item in diarization.observations}
    provider_observations = {
        item.observation_id: item
        for item in response.observations
        if item.canonical_owner and item.observation_id in canonical
    }
    embeddings = {item.embedding_id: item for item in response.embeddings}
    eligible_usability = {
        ObservationUsability.USABLE,
        ObservationUsability.PROVISIONAL,
    }
    groups: dict[str, list[str]] = {}
    unclustered = []
    for observation_id, observation in canonical.items():
        provider_observation = provider_observations.get(observation_id)
        if (
            provider_observation is None
            or not provider_observation.provider_speaker_label
            or observation.usability not in eligible_usability
            or observation.normalized_audio_interval.duration_microseconds
            < policy.minimum_observation_microseconds
        ):
            unclustered.append(observation_id)
            continue
        groups.setdefault(
            provider_observation.provider_speaker_label, []
        ).append(observation_id)

    memberships = []
    clusters = []
    consistency_results = []
    split_proposals = []
    for observation_ids in sorted(
        (tuple(sorted(values)) for values in groups.values()),
        key=lambda values: values,
    ):
        cluster_id = typed_id(
            "spkcluster",
            run_id,
            observation_ids,
        )
        member_embeddings = [
            embeddings[item.embedding_id]
            for observation_id in observation_ids
            if (
                (item := provider_observations[observation_id]).embedding_id
                is not None
            )
        ]
        model_keys = {
            (
                item.model_space_id,
                item.model_fingerprint,
                item.dimension_count,
                item.numeric_format,
            )
            for item in member_embeddings
        }
        if len(model_keys) > 1:
            raise ClusteringIntegrityError(
                "cluster observations use incompatible embedding model spaces"
            )
        model_space_id = None
        model_fingerprint = None
        representative_embedding_id = None
        if member_embeddings:
            representative = sorted(
                member_embeddings, key=lambda item: item.embedding_id
            )[0]
            model_space_id = representative.model_space_id
            model_fingerprint = representative.model_fingerprint
            representative_embedding_id = representative.embedding_id

        group_set = set(observation_ids)
        conflicts = tuple(
            item
            for item in diarization.overlaps
            if len(group_set.intersection(item.observation_ids)) >= 2
        )
        weak = tuple(
            observation_id
            for observation_id in observation_ids
            if canonical[
                observation_id
            ].normalized_audio_interval.duration_microseconds
            < 2 * policy.minimum_observation_microseconds
        )
        if conflicts:
            disposition = (
                ClusterConsistencyDisposition.LIKELY_OVER_MERGED
            )
            findings = (
                "Multiple members appear simultaneously in explicit overlap.",
            )
        elif len(observation_ids) == 1:
            disposition = (
                ClusterConsistencyDisposition.INSUFFICIENT_EVIDENCE
            )
            findings = (
                "A single observation cannot establish internal coherence.",
            )
        else:
            disposition = (
                ClusterConsistencyDisposition.PROVISIONALLY_CONSISTENT
            )
            findings = (
                "Provider acoustic labels agree; no pairwise embedding "
                "values were available for independent verification.",
            )
        result_id = typed_id(
            "clusterconsistency",
            run_id,
            cluster_id,
        )
        consistency = _seal(
            ClusterConsistencyResult,
            {
                "result_id": result_id,
                "cluster_id": cluster_id,
                "corpus_id": diarization.corpus_id,
                "observation_ids": observation_ids,
                "disposition": disposition,
                "consistency_confidence": _confidence(
                    tuple(
                        turn.assignment_confidence
                        for turn in response.turns
                        if group_set.intersection(turn.observation_ids)
                    ),
                    "provider-label cluster membership support",
                ),
                "model_space_id": model_space_id,
                "model_fingerprint": model_fingerprint,
                "pairwise_measurement_count": 0,
                "outlier_observation_ids": (),
                "simultaneous_conflict_overlap_ids": tuple(
                    item.overlap_id for item in conflicts
                ),
                "weak_observation_ids": weak,
                "findings": findings,
                "limitations": (
                    "A provider acoustic label is not a participant identity.",
                    "No pairwise embedding values were exposed to this kernel.",
                ),
                "created_at": response.completed_at,
            },
        )

        split_ids = ()
        if conflicts:
            split_id = typed_id("clustersplit", run_id, cluster_id, "overlap")
            partitions = tuple(
                ClusterSplitPartition(
                    partition_id=typed_id(
                        "clusterpartition",
                        split_id,
                        observation_id,
                    ),
                    observation_ids=(observation_id,),
                    basis=(
                        "Conservative singleton partition for review; "
                        "not automatically applied.",
                    ),
                )
                for observation_id in observation_ids
            )
            split = _seal(
                ClusterSplitProposal,
                {
                    "proposal_id": split_id,
                    "source_cluster_id": cluster_id,
                    "partitions": partitions,
                    "outlier_evidence": (),
                    "incompatibility_evidence": (
                        "simultaneous members cannot represent one bounded "
                        "voice source without contamination or provider error",
                    ),
                    "overlap_conflict_ids": tuple(
                        item.overlap_id for item in conflicts
                    ),
                    "identity_conflict_ids": (),
                    "proposal_confidence": _split_confidence(conflicts),
                    "disposition": (
                        ClusterProposalDisposition.REVIEW_REQUIRED
                    ),
                    "created_at": response.completed_at,
                },
            )
            split_proposals.append(split)
            split_ids = (split_id,)

        membership_ids = []
        for observation_id in observation_ids:
            membership_id = typed_id(
                "spkmember",
                run_id,
                cluster_id,
                observation_id,
            )
            membership_ids.append(membership_id)
            relevant = tuple(
                turn.assignment_confidence
                for turn in response.turns
                if observation_id in turn.observation_ids
            )
            memberships.append(
                ClusterMembership(
                    membership_id=membership_id,
                    cluster_id=cluster_id,
                    observation_id=observation_id,
                    membership_confidence=_confidence(
                        relevant,
                        "provider acoustic-label assignment",
                    ),
                    canonical=True,
                    basis=(
                        "Normalized from a provider acoustic label; "
                        "not a person or identity assertion."
                    ),
                )
            )
        temporal = tuple(
            canonical[item].normalized_audio_interval
            for item in observation_ids
        )
        source = tuple(
            canonical[item].source_interval for item in observation_ids
        )
        turns = tuple(
            item.turn_id
            for item in diarization.turns
            if group_set.intersection(item.observation_ids)
        )
        cluster = _seal(
            SpeakerCluster,
            {
                "cluster_id": cluster_id,
                "corpus_id": diarization.corpus_id,
                "membership_ids": tuple(membership_ids),
                "observation_ids": observation_ids,
                "turn_ids": turns,
                "formation_method": policy.formation_method,
                "configuration_hash": configuration_hash,
                "representative_embedding_id": representative_embedding_id,
                "model_space_id": model_space_id,
                "model_fingerprint": model_fingerprint,
                "internal_similarity_minimum": None,
                "internal_similarity_mean": None,
                "similarity_measurement_basis": None,
                "outlier_observation_ids": (),
                "temporal_distribution": temporal,
                "source_coverage": source,
                "total_observation_microseconds": sum(
                    item.duration_microseconds for item in temporal
                ),
                "consistency_result_id": result_id,
                "split_proposal_ids": split_ids,
                "status": (
                    ClusterStatus.UNRESOLVED
                    if conflicts
                    else ClusterStatus.PROVISIONAL
                ),
                "created_at": response.completed_at,
            },
        )
        clusters.append(cluster)
        consistency_results.append(consistency)

    payload = {
        "run_id": run_id,
        "diarization_run_id": diarization.run_id,
        "request_id": request.request_id,
        "corpus_id": diarization.corpus_id,
        "provider_capabilities": capabilities,
        "policy": policy,
        "configuration_hash": configuration_hash,
        "memberships": tuple(memberships),
        "clusters": tuple(clusters),
        "consistency_results": tuple(consistency_results),
        "merge_proposals": (),
        "split_proposals": tuple(split_proposals),
        "unclustered_observation_ids": tuple(sorted(unclustered)),
        "created_at": response.completed_at,
    }
    result = _seal(ClusteringRun, payload)
    validate_clustering_run(result, diarization)
    return result


def validate_clustering_run(
    run: ClusteringRun,
    diarization: DiarizationRun,
) -> None:
    if canonical_hash(_integrity_payload(run)) != run.integrity_sha256:
        raise ClusteringIntegrityError("clustering run integrity is invalid")
    if (
        run.diarization_run_id != diarization.run_id
        or run.request_id != diarization.request_id
        or run.corpus_id != diarization.corpus_id
    ):
        raise ClusteringIntegrityError("clustering run lineage is invalid")

    observation_ids = {item.observation_id for item in diarization.observations}
    cluster_map = {item.cluster_id: item for item in run.clusters}
    if len(cluster_map) != len(run.clusters):
        raise ClusteringIntegrityError("cluster identities repeat")
    membership_map = {
        item.membership_id: item for item in run.memberships
    }
    if len(membership_map) != len(run.memberships):
        raise ClusteringIntegrityError("cluster membership identities repeat")
    assigned = [
        item.observation_id for item in run.memberships if item.canonical
    ]
    if len(assigned) != len(set(assigned)):
        raise ClusteringIntegrityError(
            "one observation is canonically assigned to incompatible clusters"
        )
    if not set(assigned).issubset(observation_ids):
        raise ClusteringIntegrityError(
            "cluster membership references unknown observation"
        )
    unclustered = set(run.unclustered_observation_ids)
    if (
        unclustered.intersection(assigned)
        or unclustered.union(assigned) != observation_ids
    ):
        raise ClusteringIntegrityError(
            "clustered and unclustered observations do not partition evidence"
        )

    for cluster in run.clusters:
        if canonical_hash(_integrity_payload(cluster)) != (
            cluster.integrity_sha256
        ):
            raise ClusteringIntegrityError("speaker cluster integrity is invalid")
        if cluster.corpus_id != run.corpus_id:
            raise ClusteringIntegrityError("speaker cluster lineage is invalid")
        linked = [membership_map.get(item) for item in cluster.membership_ids]
        if (
            any(item is None for item in linked)
            or {item.cluster_id for item in linked} != {cluster.cluster_id}
            or {item.observation_id for item in linked}
            != set(cluster.observation_ids)
        ):
            raise ClusteringIntegrityError(
                "speaker cluster membership lineage is invalid"
            )

    consistency = {
        item.result_id: item for item in run.consistency_results
    }
    if len(consistency) != len(run.consistency_results):
        raise ClusteringIntegrityError(
            "cluster consistency identities repeat"
        )
    for cluster in run.clusters:
        result = consistency.get(cluster.consistency_result_id)
        if (
            result is None
            or result.cluster_id != cluster.cluster_id
            or set(result.observation_ids) != set(cluster.observation_ids)
            or canonical_hash(_integrity_payload(result))
            != result.integrity_sha256
        ):
            raise ClusteringIntegrityError(
                "cluster consistency lineage or integrity is invalid"
            )

    for proposal in run.merge_proposals:
        if proposal.disposition == ClusterProposalDisposition.ACCEPTED:
            raise ClusteringIntegrityError(
                "accepted merge requires an explicit successor transformation"
            )
        if (
            not set(proposal.source_cluster_ids).issubset(cluster_map)
            or canonical_hash(_integrity_payload(proposal))
            != proposal.integrity_sha256
        ):
            raise ClusteringIntegrityError("invalid cluster merge target")
    for proposal in run.split_proposals:
        if proposal.disposition == ClusterProposalDisposition.ACCEPTED:
            raise ClusteringIntegrityError(
                "accepted split requires an explicit successor transformation"
            )
        cluster = cluster_map.get(proposal.source_cluster_id)
        partitioned = {
            item
            for partition in proposal.partitions
            for item in partition.observation_ids
        }
        if (
            cluster is None
            or partitioned != set(cluster.observation_ids)
            or canonical_hash(_integrity_payload(proposal))
            != proposal.integrity_sha256
        ):
            raise ClusteringIntegrityError("invalid cluster split partition")

    predecessors = {
        item.cluster_id: set(item.predecessor_cluster_ids)
        for item in run.clusters
    }

    def visit(cluster_id: str, path: set[str]) -> None:
        if cluster_id in path:
            raise ClusteringIntegrityError("cluster lineage cycle detected")
        for predecessor in predecessors.get(cluster_id, ()):
            visit(predecessor, {*path, cluster_id})

    for cluster_id in predecessors:
        visit(cluster_id, set())


def _report(run: ClusteringRun) -> ClusteringReport:
    counts = Counter(
        item.disposition for item in run.consistency_results
    )
    conflicts = sum(
        item.disposition
        in {
            ClusterConsistencyDisposition.LIKELY_OVER_MERGED,
            ClusterConsistencyDisposition.LIKELY_OVER_SPLIT,
            ClusterConsistencyDisposition.CONTAMINATED,
            ClusterConsistencyDisposition.INVALID,
        }
        for item in run.consistency_results
    )
    return ClusteringReport(
        report_id=typed_id("clusterreport", run.run_id),
        run_id=run.run_id,
        diarization_run_id=run.diarization_run_id,
        corpus_id=run.corpus_id,
        generated_at=datetime.now(timezone.utc),
        cluster_count=len(run.clusters),
        membership_count=len(run.memberships),
        unclustered_observation_count=len(
            run.unclustered_observation_ids
        ),
        consistency_dispositions=tuple(
            ClusterConsistencySummary(disposition=item, count=counts[item])
            for item in ClusterConsistencyDisposition
        ),
        merge_proposal_count=len(run.merge_proposals),
        split_proposal_count=len(run.split_proposals),
        unresolved_conflict_count=conflicts,
        limitations=(
            "Clusters are acoustic compatibility hypotheses, not people.",
            "Provider-label partitioning exposes no pairwise embedding values.",
            "Merge and split proposals are not applied automatically.",
        ),
        status="warning" if conflicts or run.unclustered_observation_ids else "complete",
    )


def clustering_report_markdown(report: ClusteringReport) -> str:
    return "\n".join(
        [
            "# Phase 3 provisional acoustic-clustering report",
            "",
            f"Status: **{report.status.upper()}**",
            "",
            f"Run: `{report.run_id}`",
            "",
            f"- Provisional clusters: {report.cluster_count}",
            f"- Canonical memberships: {report.membership_count}",
            (
                "- Unclustered observations: "
                f"{report.unclustered_observation_count}"
            ),
            f"- Merge proposals: {report.merge_proposal_count}",
            f"- Split proposals: {report.split_proposal_count}",
            f"- Unresolved conflicts: {report.unresolved_conflict_count}",
            "",
            "No cluster identifier or membership is a participant identity.",
            "",
        ]
    )


def cluster_diarization(
    diarization_root: Path,
    destination: Path,
    *,
    capabilities: DiarizationProviderCapabilities,
    policy: ClusteringPolicy | None = None,
) -> tuple[ClusteringRun, ClusteringReport, Path, bool]:
    diarization_root = diarization_root.expanduser().resolve(strict=True)
    destination = destination.expanduser().resolve()
    if destination == diarization_root or diarization_root in destination.parents:
        raise ValueError(
            "clustering output must not modify the diarization evidence run"
        )
    request = load_contract(
        (diarization_root / "request.json").read_bytes(),
        DiarizationRequest,
    )
    response = load_contract(
        (diarization_root / "response.json").read_bytes(),
        DiarizationProviderResponse,
    )
    diarization = load_contract(
        (diarization_root / "run.json").read_bytes(),
        DiarizationRun,
    )
    validate_diarization_response(response, request, diarization_root)
    validate_diarization_run(diarization)
    expected = form_clustering_run(
        request,
        response,
        diarization,
        capabilities,
        policy=policy,
    )
    root = destination / "clustering" / expected.run_id
    clustering_path = root / "clustering.json"
    report_path = root / "report.json"
    existing = (clustering_path.exists(), report_path.exists())
    if any(existing) and not all(existing):
        raise ClusteringIntegrityError("cached clustering run is incomplete")
    if all(existing):
        stored = load_contract(clustering_path.read_bytes(), ClusteringRun)
        report = load_contract(report_path.read_bytes(), ClusteringReport)
        validate_clustering_run(stored, diarization)
        if (
            stored != expected
            or report.run_id != stored.run_id
            or report.diarization_run_id != stored.diarization_run_id
            or report.corpus_id != stored.corpus_id
        ):
            raise ClusteringIntegrityError(
                "cached clustering evidence is incompatible"
            )
        return stored, report, root, True

    report = _report(expected)
    _atomic(clustering_path, canonical_bytes(expected))
    _atomic(report_path, canonical_bytes(report))
    _atomic(
        root / "report.md",
        clustering_report_markdown(report).encode("utf-8"),
    )
    return expected, report, root, False
