"""Phase 5 long-recording and twenty-four-gate completion contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract, Sha256
from .phase5_contracts import PHASE5_FORMAT_VERSION

PHASE5_COMPLETION_POLICY_VERSION = "1.0.0"


class Phase5EvidenceClass(str, Enum):
    DETERMINISTIC_RULES = "deterministic_rules"
    PROVIDER_PROPOSALS = "provider_proposals"
    SELECTED_MACHINE_ANALYSIS = "selected_machine_analysis"
    HUMAN_REVIEW = "human_review"
    MEASURED_EVALUATION = "measured_evaluation"
    SYNTHETIC_MECHANICS = "synthetic_mechanics"
    INTEGRITY_VALIDATION = "integrity_validation"
    FUTURE_EXPECTATION = "future_expectation"


class Phase5GateStatus(str, Enum):
    COMPLETE = "complete"
    PENDING = "pending"
    BLOCKED = "blocked"


class Phase5LongRecordingQualification(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    qualification_id: str = Field(pattern=r"^phase5long_[a-f0-9]{32}$")
    generated_at: datetime
    duration_microseconds: int = Field(gt=7_200_000_000)
    processing_chunk_count: int = Field(ge=2)
    utterance_count: int = Field(ge=2)
    discourse_act_count: int = Field(ge=2)
    context_window_count: int = Field(ge=2)
    maximum_active_context_utterances: int = Field(ge=1)
    maximum_relation_search_utterances: int = Field(ge=1)
    cross_chunk_continuity_count: int = Field(ge=1)
    interruption_resume_count: int = Field(ge=1)
    cache_hit_count: int = Field(ge=1)
    recovery_count: int = Field(ge=1)
    peak_memory_bytes: int = Field(gt=0)
    incremental_processing: Literal[True] = True
    deterministic_context_retrieval: Literal[True] = True
    bounded_relation_search: Literal[True] = True
    duplicate_act_ownership_count: Literal[0] = 0
    context_budgets_enforced: Literal[True] = True
    export_reload_valid: Literal[True] = True
    final_integrity_valid: Literal[True] = True
    bounded_memory: Literal[True] = True
    provider_execution_used: Literal[False] = False
    evidence_class: Literal["synthetic_mechanics"] = "synthetic_mechanics"
    natural_discourse_accuracy_claim: Literal[False] = False
    integrity_sha256: Sha256


class Phase5CompletionPolicy(Contract):
    policy_version: Literal["1.0.0"] = PHASE5_COMPLETION_POLICY_VERSION
    required_gate_count: Literal[24] = 24
    separate_evidence_classes: Literal[True] = True
    complete_requires_all_gates: Literal[True] = True
    corrupt_evidence_action: Literal["refuse"] = "refuse"
    incomplete_evidence_action: Literal["report_in_progress"] = (
        "report_in_progress"
    )


class Phase5CompletionEvidence(Contract):
    qualification: str = Field(pattern=r"^phase-5-[a-z0-9-]+$")
    evidence_reference: str = Field(min_length=1)
    evidence_sha256: Sha256
    evidence_byte_size: int = Field(gt=0)
    evidence_class: Phase5EvidenceClass
    assertion_count: int = Field(ge=1)
    status: Literal["passed"] = "passed"


class Phase5CompletionMeasurements(Contract):
    discourse_corpus_id: str = Field(pattern=r"^discoursecorpus_[a-f0-9]{32}$")
    configuration_hash: Sha256
    phase4_utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    act_family_counts: tuple[str, ...]
    act_type_counts: tuple[str, ...]
    multi_label_utterance_count: int = Field(ge=0)
    unclassified_utterance_count: int = Field(ge=0)
    evidence_span_count: int = Field(ge=0)
    question_count: int = Field(ge=0)
    question_type_counts: tuple[str, ...]
    answer_relation_count: int = Field(ge=0)
    unresolved_answer_count: int = Field(ge=0)
    objection_count: int = Field(ge=0)
    rebuttal_count: int = Field(ge=0)
    concession_count: int = Field(ge=0)
    qualification_count: int = Field(ge=0)
    definition_count: int = Field(ge=0)
    example_count: int = Field(ge=0)
    quotation_use_count: int = Field(ge=0)
    procedural_act_count: int = Field(ge=0)
    alternative_candidate_count: int = Field(ge=0)
    confidence_distribution: tuple[str, ...]
    manual_review_action_count: int = Field(ge=0)
    correction_affected_act_count: int = Field(ge=0)
    measured_evaluation_metric_count: int = Field(ge=0)
    long_recording_duration_microseconds: int = Field(gt=7_200_000_000)
    recovery_stage_count: int = Field(ge=14)
    negative_proof_count: int = Field(ge=25)
    peak_memory_bytes: int = Field(gt=0)
    full_regression_test_count: int = Field(ge=1)
    runtime_schema_count: int = Field(ge=1)


class Phase5CompletionGate(Contract):
    gate_number: int = Field(ge=1, le=24)
    gate_name: str = Field(min_length=1)
    status: Phase5GateStatus
    evidence_qualifications: tuple[str, ...]
    basis: str = Field(min_length=1)
    blocking_findings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def status_is_coherent(self) -> "Phase5CompletionGate":
        if self.status == Phase5GateStatus.COMPLETE and (
            not self.evidence_qualifications or self.blocking_findings
        ):
            raise ValueError("complete gate requires evidence and no blockers")
        if self.status != Phase5GateStatus.COMPLETE and not self.blocking_findings:
            raise ValueError("non-complete gate requires a blocker")
        return self


class Phase5CompletionReport(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    report_id: str = Field(pattern=r"^phase5completion_[a-f0-9]{32}$")
    predecessor_report_id: str | None = Field(
        default=None, pattern=r"^phase5completion_[a-f0-9]{32}$"
    )
    generated_at: datetime
    application_version: str = Field(min_length=1)
    contract_version_reported: str = Field(min_length=1)
    repository_branch: str = Field(min_length=1)
    starting_repository_head: str = Field(pattern=r"^[a-f0-9]{40}$")
    final_repository_head: str = Field(pattern=r"^[a-f0-9]{40}$")
    phase_changes_committed_at_audit: bool
    policy: Phase5CompletionPolicy
    evidence: tuple[Phase5CompletionEvidence, ...] = Field(min_length=1)
    measurements: Phase5CompletionMeasurements
    gates: tuple[Phase5CompletionGate, ...] = Field(
        min_length=24, max_length=24
    )
    boundary_statements: tuple[str, ...] = Field(min_length=6)
    known_limitations: tuple[str, ...]
    unresolved_concerns: tuple[str, ...]
    status: Literal["complete", "in_progress", "blocked"]
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def completion_is_coherent(self) -> "Phase5CompletionReport":
        if tuple(item.gate_number for item in self.gates) != tuple(
            range(1, 25)
        ):
            raise ValueError("completion gates must be ordered 1 through 24")
        qualifications = [item.qualification for item in self.evidence]
        if len(qualifications) != len(set(qualifications)):
            raise ValueError("completion evidence must be unique")
        complete = all(
            item.status == Phase5GateStatus.COMPLETE for item in self.gates
        )
        expected = "complete" if complete else "in_progress"
        if self.status != expected:
            raise ValueError("completion status disagrees with gates")
        return self


PHASE5_COMPLETION_CONTRACT_MODELS = (
    Phase5LongRecordingQualification,
    Phase5CompletionPolicy,
    Phase5CompletionEvidence,
    Phase5CompletionMeasurements,
    Phase5CompletionGate,
    Phase5CompletionReport,
)
