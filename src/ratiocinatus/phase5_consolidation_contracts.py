"""Contracts for deterministic/provider discourse candidate consolidation."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract, Sha256
from .phase5_contracts import (
    PHASE5_FORMAT_VERSION,
    DiscourseActCandidateSet,
)

DISCOURSE_CONSOLIDATION_POLICY_VERSION = "1.0.0"


class CandidateEvidenceDisposition(str, Enum):
    DETERMINISTIC_ONLY = "deterministic_only"
    PROVIDER_ONLY = "provider_only"
    CORROBORATED = "corroborated"



class DiscourseConsolidationPolicy(Contract):
    policy_version: Literal["1.0.0"] = (
        DISCOURSE_CONSOLIDATION_POLICY_VERSION
    )
    minimum_span_overlap_for_merge: float = Field(
        default=0.5, gt=0.0, le=1.0
    )
    selection_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    conflict_resolution_margin: float = Field(
        default=0.15, ge=0.0, le=1.0
    )
    corroboration_bonus: float = Field(default=0.05, ge=0.0, le=0.25)
    maximum_selected_acts_per_utterance: int = Field(
        default=12, ge=1, le=100
    )
    compatible_multi_label_selection: Literal[True] = True
    retain_rejected_candidates: Literal[True] = True
    retain_deferred_candidates: Literal[True] = True
    provider_output_authoritative: Literal[False] = False
    close_conflicts_remain_unresolved: Literal[True] = True
    unknown_is_valid: Literal[True] = True


class CandidateEvidenceSummary(Contract):
    summary_id: str = Field(
        pattern=r"^candidateevidence_[a-f0-9]{32}$"
    )
    candidate_id: str = Field(
        pattern=r"^discoursecandidate_[a-f0-9]{32}$"
    )
    observation_ids: tuple[str, ...] = Field(min_length=1)
    disposition: CandidateEvidenceDisposition
    deterministic_observation_count: int = Field(ge=0)
    provider_observation_count: int = Field(ge=0)
    maximum_span_overlap: float = Field(ge=0.0, le=1.0)
    selection_score: float = Field(ge=0.0, le=1.0)
    supporting_evidence: tuple[str, ...] = Field(min_length=1)
    contrary_evidence: tuple[str, ...] = ()
    limitations: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def evidence_counts_are_coherent(self) -> "CandidateEvidenceSummary":
        if (
            self.deterministic_observation_count
            + self.provider_observation_count
            != len(self.observation_ids)
        ):
            raise ValueError("candidate evidence counts are inconsistent")
        expected = (
            CandidateEvidenceDisposition.CORROBORATED
            if self.deterministic_observation_count
            and self.provider_observation_count
            else (
                CandidateEvidenceDisposition.DETERMINISTIC_ONLY
                if self.deterministic_observation_count
                else CandidateEvidenceDisposition.PROVIDER_ONLY
            )
        )
        if self.disposition != expected:
            raise ValueError("candidate evidence disposition is inconsistent")
        return self


class DiscourseConsolidationRun(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    consolidation_run_id: str = Field(
        pattern=r"^discourseconsolidation_[a-f0-9]{32}$"
    )
    discourse_run_id: str = Field(pattern=r"^discourserun_[a-f0-9]{32}$")
    discourse_corpus_id: str = Field(
        pattern=r"^discoursecorpus_[a-f0-9]{32}$"
    )
    phase4_utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    phase4_utterance_corpus_sha256: Sha256
    deterministic_baseline_run_id: str = Field(
        pattern=r"^discoursebaseline_[a-f0-9]{32}$"
    )
    provider_run_id: str = Field(
        pattern=r"^discourseproviderrun_[a-f0-9]{32}$"
    )
    policy: DiscourseConsolidationPolicy
    configuration_hash: Sha256
    candidate_sets: tuple[DiscourseActCandidateSet, ...]
    evidence_summaries: tuple[CandidateEvidenceSummary, ...]
    selected_act_ids: tuple[str, ...]
    unresolved_candidate_set_ids: tuple[str, ...]
    created_at: datetime
    complete: bool
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def run_children_are_coherent(self) -> "DiscourseConsolidationRun":
        set_ids = [item.candidate_set_id for item in self.candidate_sets]
        summary_ids = [item.summary_id for item in self.evidence_summaries]
        candidate_ids = {
            item.candidate_id
            for candidate_set in self.candidate_sets
            for item in candidate_set.candidates
        }
        if len(set_ids) != len(set(set_ids)):
            raise ValueError("consolidation candidate-set ids must be unique")
        if len(summary_ids) != len(set(summary_ids)):
            raise ValueError("consolidation summary ids must be unique")
        if {item.candidate_id for item in self.evidence_summaries} != candidate_ids:
            raise ValueError("every candidate requires one evidence summary")
        unresolved = {
            item.candidate_set_id
            for item in self.candidate_sets
            if item.unresolved
        }
        if set(self.unresolved_candidate_set_ids) != unresolved:
            raise ValueError("unresolved candidate-set inventory is stale")
        return self


class DiscourseConsolidationReport(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    report_id: str = Field(
        pattern=r"^discourseconsolidationreport_[a-f0-9]{32}$"
    )
    consolidation_run_id: str = Field(
        pattern=r"^discourseconsolidation_[a-f0-9]{32}$"
    )
    discourse_corpus_id: str = Field(
        pattern=r"^discoursecorpus_[a-f0-9]{32}$"
    )
    generated_at: datetime
    observation_count: int = Field(ge=0)
    candidate_count: int = Field(ge=0)
    corroborated_candidate_count: int = Field(ge=0)
    deterministic_only_candidate_count: int = Field(ge=0)
    provider_only_candidate_count: int = Field(ge=0)
    selected_candidate_count: int = Field(ge=0)
    rejected_candidate_count: int = Field(ge=0)
    deferred_candidate_count: int = Field(ge=0)
    unresolved_candidate_set_count: int = Field(ge=0)
    canonical_act_count: int = Field(ge=0)
    multi_label_utterance_count: int = Field(ge=0)
    unclassified_utterance_count: int = Field(ge=0)
    provider_failure_count: int = Field(ge=0)
    limitations: tuple[str, ...] = Field(min_length=1)
    status: Literal["complete", "warning", "failed"]
    integrity_sha256: Sha256


PHASE5_CONSOLIDATION_CONTRACT_MODELS = (
    DiscourseConsolidationPolicy,
    CandidateEvidenceSummary,
    DiscourseConsolidationRun,
    DiscourseConsolidationReport,
)
