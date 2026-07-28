"""Phase 3 provisional acoustic-clustering and consistency contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract, Sha256
from .phase2_contracts import ConfidenceMeasure
from .phase3_contracts import (
    ClusterMembership,
    DiarizationProviderCapabilities,
    SpeakerCluster,
)

CLUSTERING_FORMAT_VERSION = "1.0.0"
CLUSTERING_POLICY_VERSION = "1.0.0"


class ClusterConsistencyDisposition(str, Enum):
    CONSISTENT = "consistent"
    PROVISIONALLY_CONSISTENT = "provisionally_consistent"
    MIXED_EVIDENCE = "mixed_evidence"
    LIKELY_OVER_MERGED = "likely_over_merged"
    LIKELY_OVER_SPLIT = "likely_over_split"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONTAMINATED = "contaminated"
    INVALID = "invalid"


class ClusterProposalDisposition(str, Enum):
    PROPOSED = "proposed"
    REVIEW_REQUIRED = "review_required"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class ClusteringPolicy(Contract):
    policy_version: Literal["1.0.0"] = CLUSTERING_POLICY_VERSION
    formation_method: Literal["provider_acoustic_label_partition_v1"] = (
        "provider_acoustic_label_partition_v1"
    )
    minimum_observation_microseconds: int = Field(default=500_000, gt=0)
    unusable_observation_policy: Literal["preserve_unclustered"] = (
        "preserve_unclustered"
    )
    missing_label_policy: Literal["preserve_unclustered"] = (
        "preserve_unclustered"
    )
    mixed_embedding_space_policy: Literal["refuse"] = "refuse"
    simultaneous_self_overlap_policy: Literal[
        "flag_likely_over_merged_and_propose_split"
    ] = "flag_likely_over_merged_and_propose_split"
    automatic_merge_policy: Literal["disabled"] = "disabled"
    automatic_split_policy: Literal["disabled"] = "disabled"


class ClusterConsistencyResult(Contract):
    format_version: Literal["1.0.0"] = CLUSTERING_FORMAT_VERSION
    result_id: str = Field(pattern=r"^clusterconsistency_[a-f0-9]{32}$")
    cluster_id: str = Field(pattern=r"^spkcluster_[a-f0-9]{32}$")
    corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    observation_ids: tuple[str, ...] = Field(min_length=1)
    disposition: ClusterConsistencyDisposition
    consistency_confidence: ConfidenceMeasure
    model_space_id: str | None = Field(
        default=None, pattern=r"^[a-z][a-z0-9_.:-]+$"
    )
    model_fingerprint: Sha256 | None = None
    pairwise_measurement_count: int = Field(default=0, ge=0)
    outlier_observation_ids: tuple[str, ...] = ()
    simultaneous_conflict_overlap_ids: tuple[str, ...] = ()
    weak_observation_ids: tuple[str, ...] = ()
    findings: tuple[str, ...]
    limitations: tuple[str, ...]
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def result_references_are_bounded(self) -> "ClusterConsistencyResult":
        known = set(self.observation_ids)
        if not set(self.outlier_observation_ids).issubset(known):
            raise ValueError("cluster outlier references unknown observation")
        if not set(self.weak_observation_ids).issubset(known):
            raise ValueError("cluster weak evidence references unknown observation")
        if self.model_space_id is None and self.model_fingerprint is not None:
            raise ValueError("consistency fingerprint requires a model space")
        return self


class ClusterMergeProposal(Contract):
    format_version: Literal["1.0.0"] = CLUSTERING_FORMAT_VERSION
    proposal_id: str = Field(pattern=r"^clustermerge_[a-f0-9]{32}$")
    source_cluster_ids: tuple[str, ...] = Field(min_length=2)
    acoustic_basis: tuple[str, ...]
    temporal_basis: tuple[str, ...]
    identity_compatibility_basis: tuple[str, ...]
    contrary_evidence: tuple[str, ...]
    proposal_confidence: ConfidenceMeasure
    disposition: ClusterProposalDisposition
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def merge_sources_are_unique(self) -> "ClusterMergeProposal":
        if len(self.source_cluster_ids) != len(set(self.source_cluster_ids)):
            raise ValueError("merge proposal sources must be unique")
        return self


class ClusterSplitPartition(Contract):
    partition_id: str = Field(pattern=r"^clusterpartition_[a-f0-9]{32}$")
    observation_ids: tuple[str, ...] = Field(min_length=1)
    basis: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def partition_members_are_unique(self) -> "ClusterSplitPartition":
        if len(self.observation_ids) != len(set(self.observation_ids)):
            raise ValueError("split partition observations must be unique")
        return self


class ClusterSplitProposal(Contract):
    format_version: Literal["1.0.0"] = CLUSTERING_FORMAT_VERSION
    proposal_id: str = Field(pattern=r"^clustersplit_[a-f0-9]{32}$")
    source_cluster_id: str = Field(pattern=r"^spkcluster_[a-f0-9]{32}$")
    partitions: tuple[ClusterSplitPartition, ...] = Field(min_length=2)
    outlier_evidence: tuple[str, ...]
    incompatibility_evidence: tuple[str, ...]
    overlap_conflict_ids: tuple[str, ...]
    identity_conflict_ids: tuple[str, ...]
    proposal_confidence: ConfidenceMeasure
    disposition: ClusterProposalDisposition
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def partitions_do_not_overlap(self) -> "ClusterSplitProposal":
        members = [
            observation_id
            for partition in self.partitions
            for observation_id in partition.observation_ids
        ]
        if len(members) != len(set(members)):
            raise ValueError("split proposal partitions overlap")
        return self


class ClusteringRun(Contract):
    format_version: Literal["1.0.0"] = CLUSTERING_FORMAT_VERSION
    run_id: str = Field(pattern=r"^clusterrun_[a-f0-9]{32}$")
    diarization_run_id: str = Field(pattern=r"^diarun_[a-f0-9]{32}$")
    request_id: str = Field(pattern=r"^diareq_[a-f0-9]{32}$")
    corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    provider_capabilities: DiarizationProviderCapabilities
    policy: ClusteringPolicy
    configuration_hash: Sha256
    memberships: tuple[ClusterMembership, ...]
    clusters: tuple[SpeakerCluster, ...]
    consistency_results: tuple[ClusterConsistencyResult, ...]
    merge_proposals: tuple[ClusterMergeProposal, ...] = ()
    split_proposals: tuple[ClusterSplitProposal, ...] = ()
    unclustered_observation_ids: tuple[str, ...] = ()
    created_at: datetime
    integrity_sha256: Sha256


class ClusterConsistencySummary(Contract):
    disposition: ClusterConsistencyDisposition
    count: int = Field(ge=0)

class ClusteringReport(Contract):
    format_version: Literal["1.0.0"] = CLUSTERING_FORMAT_VERSION
    report_id: str = Field(pattern=r"^clusterreport_[a-f0-9]{32}$")
    run_id: str = Field(pattern=r"^clusterrun_[a-f0-9]{32}$")
    diarization_run_id: str = Field(pattern=r"^diarun_[a-f0-9]{32}$")
    corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    generated_at: datetime
    cluster_count: int = Field(ge=0)
    membership_count: int = Field(ge=0)
    unclustered_observation_count: int = Field(ge=0)
    consistency_dispositions: tuple[ClusterConsistencySummary, ...]
    merge_proposal_count: int = Field(ge=0)
    split_proposal_count: int = Field(ge=0)
    unresolved_conflict_count: int = Field(ge=0)
    findings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    status: Literal["complete", "warning", "blocked"]


CLUSTERING_CONTRACT_MODELS = (
    ClusteringPolicy,
    ClusterConsistencyResult,
    ClusterMergeProposal,
    ClusterSplitPartition,
    ClusterSplitProposal,
    ClusteringRun,
    ClusterConsistencySummary,
    ClusteringReport,
)
