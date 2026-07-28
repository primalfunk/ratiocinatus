"""Controlled clustering evaluation and embedding qualification contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract, Sha256

CLUSTERING_EVALUATION_FORMAT_VERSION = "1.0.0"
CLUSTERING_EVALUATION_POLICY_VERSION = "1.0.0"


class EmbeddingQualificationDisposition(str, Enum):
    QUALIFIED_FOR_CONTROLLED_COMPARISON = (
        "qualified_for_controlled_comparison"
    )
    QUALIFIED_METADATA_ONLY = "qualified_metadata_only"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    BLOCKED_INTEGRITY = "blocked_integrity"


class ClusteringEvaluationPolicy(Contract):
    policy_version: Literal["1.0.0"] = (
        CLUSTERING_EVALUATION_POLICY_VERSION
    )
    partition_metric: Literal["unordered_observation_pairs_v1"] = (
        "unordered_observation_pairs_v1"
    )
    unclustered_pair_policy: Literal["predicted_different"] = (
        "predicted_different"
    )
    incomplete_reference_policy: Literal["evaluate_labeled_subset"] = (
        "evaluate_labeled_subset"
    )
    reference_labels_are_identities: Literal[False] = False
    embedding_integrity_policy: Literal[
        "verify_stored_artifacts_refuse_unsafe_paths"
    ] = "verify_stored_artifacts_refuse_unsafe_paths"


class ReferenceSpeakerAssignment(Contract):
    observation_id: str = Field(pattern=r"^spkobs_[a-f0-9]{32}$")
    reference_speaker_key: str = Field(
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$"
    )
    basis: str = Field(min_length=1)


class DiarizationReference(Contract):
    format_version: Literal["1.0.0"] = (
        CLUSTERING_EVALUATION_FORMAT_VERSION
    )
    reference_id: str = Field(pattern=r"^diaref_[a-f0-9]{32}$")
    corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    diarization_run_id: str = Field(pattern=r"^diarun_[a-f0-9]{32}$")
    source_artifact_sha256: Sha256
    assignments: tuple[ReferenceSpeakerAssignment, ...] = Field(min_length=2)
    provenance: tuple[str, ...] = Field(min_length=1)
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def assignments_are_unique(self) -> "DiarizationReference":
        observation_ids = [item.observation_id for item in self.assignments]
        if len(observation_ids) != len(set(observation_ids)):
            raise ValueError("reference observation assignments must be unique")
        return self


class ClusteringPairwiseMetrics(Contract):
    evaluated_observation_count: int = Field(ge=2)
    reference_speaker_count: int = Field(ge=1)
    predicted_cluster_count: int = Field(ge=0)
    evaluated_pair_count: int = Field(ge=1)
    same_speaker_same_cluster_pairs: int = Field(ge=0)
    different_speaker_same_cluster_pairs: int = Field(ge=0)
    same_speaker_different_cluster_pairs: int = Field(ge=0)
    different_speaker_different_cluster_pairs: int = Field(ge=0)
    same_speaker_precision: float | None = Field(
        default=None, ge=0.0, le=1.0
    )
    same_speaker_recall: float | None = Field(
        default=None, ge=0.0, le=1.0
    )
    same_speaker_f1: float | None = Field(
        default=None, ge=0.0, le=1.0
    )
    reference_coverage: float = Field(ge=0.0, le=1.0)
    clustered_reference_coverage: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def pair_counts_are_complete(self) -> "ClusteringPairwiseMetrics":
        pair_sum = (
            self.same_speaker_same_cluster_pairs
            + self.different_speaker_same_cluster_pairs
            + self.same_speaker_different_cluster_pairs
            + self.different_speaker_different_cluster_pairs
        )
        if pair_sum != self.evaluated_pair_count:
            raise ValueError("clustering pair counts do not cover all pairs")
        expected = (
            self.evaluated_observation_count
            * (self.evaluated_observation_count - 1)
            // 2
        )
        if self.evaluated_pair_count != expected:
            raise ValueError("evaluated pair count is inconsistent")
        return self


class EmbeddingModelQualification(Contract):
    qualification_id: str = Field(
        pattern=r"^embedqual_[a-f0-9]{32}$"
    )
    diarization_run_id: str = Field(pattern=r"^diarun_[a-f0-9]{32}$")
    provider_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    model_space_id: str | None = Field(
        default=None, pattern=r"^[a-z][a-z0-9_.:-]+$"
    )
    model_fingerprint: Sha256 | None = None
    dimension_count: int | None = Field(default=None, gt=0)
    numeric_format: Literal["float32", "float64", "int8"] | None = None
    embedding_count: int = Field(ge=0)
    stored_embedding_count: int = Field(ge=0)
    omitted_embedding_count: int = Field(ge=0)
    integrity_verified_count: int = Field(ge=0)
    comparison_eligible: bool
    portable_export_permitted: bool
    disposition: EmbeddingQualificationDisposition
    findings: tuple[str, ...]
    limitations: tuple[str, ...]
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def qualification_counts_are_consistent(
        self,
    ) -> "EmbeddingModelQualification":
        if (
            self.stored_embedding_count + self.omitted_embedding_count
            != self.embedding_count
        ):
            raise ValueError("embedding storage counts are inconsistent")
        if self.integrity_verified_count > self.stored_embedding_count:
            raise ValueError("verified embeddings exceed stored embeddings")
        model_fields = (
            self.model_space_id,
            self.model_fingerprint,
            self.dimension_count,
            self.numeric_format,
        )
        if (
            self.embedding_count
            and self.disposition
            != EmbeddingQualificationDisposition.BLOCKED_INTEGRITY
            and any(item is None for item in model_fields)
        ):
            raise ValueError("embedding evidence requires complete model identity")
        if not self.embedding_count and any(
            item is not None for item in model_fields
        ):
            raise ValueError("absent embeddings cannot declare a model space")
        if self.comparison_eligible and (
            self.embedding_count < 2
            or self.integrity_verified_count != self.embedding_count
        ):
            raise ValueError(
                "comparison eligibility requires two verified embeddings"
            )
        return self


class DiarizationEvaluation(Contract):
    format_version: Literal["1.0.0"] = (
        CLUSTERING_EVALUATION_FORMAT_VERSION
    )
    evaluation_id: str = Field(pattern=r"^diaeval_[a-f0-9]{32}$")
    clustering_run_id: str = Field(pattern=r"^clusterrun_[a-f0-9]{32}$")
    diarization_run_id: str = Field(pattern=r"^diarun_[a-f0-9]{32}$")
    corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    reference: DiarizationReference
    policy: ClusteringEvaluationPolicy
    metrics: ClusteringPairwiseMetrics
    embedding_qualification: EmbeddingModelQualification
    generated_at: datetime
    findings: tuple[str, ...]
    limitations: tuple[str, ...]
    status: Literal["complete", "warning", "blocked"]
    integrity_sha256: Sha256


class DiarizationEvaluationReport(Contract):
    format_version: Literal["1.0.0"] = (
        CLUSTERING_EVALUATION_FORMAT_VERSION
    )
    report_id: str = Field(pattern=r"^diarevalreport_[a-f0-9]{32}$")
    evaluation_id: str = Field(pattern=r"^diaeval_[a-f0-9]{32}$")
    clustering_run_id: str = Field(pattern=r"^clusterrun_[a-f0-9]{32}$")
    reference_id: str = Field(pattern=r"^diaref_[a-f0-9]{32}$")
    generated_at: datetime
    evaluated_observation_count: int = Field(ge=2)
    pairwise_f1: float | None = Field(default=None, ge=0.0, le=1.0)
    embedding_disposition: EmbeddingQualificationDisposition
    findings: tuple[str, ...]
    limitations: tuple[str, ...]
    status: Literal["complete", "warning", "blocked"]
    integrity_sha256: Sha256


CLUSTERING_EVALUATION_CONTRACT_MODELS = (
    ClusteringEvaluationPolicy,
    ReferenceSpeakerAssignment,
    DiarizationReference,
    ClusteringPairwiseMetrics,
    EmbeddingModelQualification,
    DiarizationEvaluation,
    DiarizationEvaluationReport,
)
