"""Phase 4 long-recording and completion-gate contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract, Sha256
from .phase4_contracts import PHASE4_FORMAT_VERSION

PHASE4_COMPLETION_POLICY_VERSION = "1.0.0"


class Phase4EvidenceClass(str, Enum):
    MEASURED_EVALUATION = "measured_evaluation"
    SYNTHETIC_MECHANICS = "synthetic_mechanics"
    HUMAN_DECISION_MECHANICS = "human_decision_mechanics"
    INTEGRITY_VALIDATION = "integrity_validation"
    FUTURE_EXPECTATION = "future_expectation"


class Phase4GateStatus(str, Enum):
    COMPLETE = "complete"
    PENDING = "pending"
    BLOCKED = "blocked"


class Phase4MetricStatus(str, Enum):
    MEASURED = "measured"
    QUALIFIED_MECHANICS = "qualified_mechanics"
    PENDING = "pending"
    UNAVAILABLE = "unavailable"


class Phase4LongRecordingQualification(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    qualification_id: str = Field(pattern=r"^phase4long_[a-f0-9]{32}$")
    generated_at: datetime
    duration_microseconds: int = Field(gt=7_200_000_000)
    processing_chunk_count: int = Field(ge=2)
    utterance_count: int = Field(ge=2)
    context_window_count: int = Field(ge=18)
    cross_chunk_utterance_count: int = Field(ge=1)
    continuation_count: int = Field(ge=1)
    chunk_boundary_interruption_count: int = Field(ge=1)
    cache_hit_count: int = Field(ge=1)
    recovery_count: int = Field(ge=1)
    peak_memory_bytes: int = Field(gt=0)
    phase1_chunk_ownership_reused: Literal[True] = True
    phase2_transcript_reused: Literal[True] = True
    phase3_speaker_evidence_reused: Literal[True] = True
    stable_cross_chunk_construction: Literal[True] = True
    duplicate_word_ownership_count: Literal[0] = 0
    duplicate_utterance_count: Literal[0] = 0
    context_budgets_enforced: Literal[True] = True
    export_reload_valid: Literal[True] = True
    final_integrity_valid: Literal[True] = True
    bounded_memory: Literal[True] = True
    evidence_class: Literal["synthetic_mechanics"] = "synthetic_mechanics"
    natural_speech_accuracy_claim: Literal[False] = False
    integrity_sha256: Sha256


class Phase4CompletionPolicy(Contract):
    policy_version: Literal["1.0.0"] = PHASE4_COMPLETION_POLICY_VERSION
    required_gate_count: Literal[19] = 19
    validate_evidence_before_inventory: Literal[True] = True
    require_machine_and_human_reports: Literal[True] = True
    separate_evidence_classes: Literal[True] = True
    complete_requires_all_gates: Literal[True] = True
    corrupt_evidence_action: Literal["refuse"] = "refuse"
    incomplete_evidence_action: Literal["report_in_progress"] = (
        "report_in_progress"
    )


class Phase4CompletionEvidence(Contract):
    qualification: str = Field(pattern=r"^phase-4-[a-z0-9-]+$")
    machine_report_relative_path: str = Field(
        pattern=r"^phase-4-[a-z0-9-]+\.json$"
    )
    machine_report_sha256: Sha256
    machine_report_byte_size: int = Field(gt=0)
    human_report_relative_path: str = Field(
        pattern=r"^phase-4-[a-z0-9-]+\.md$"
    )
    human_report_sha256: Sha256
    human_report_byte_size: int = Field(gt=0)
    evidence_class: Phase4EvidenceClass
    target_application_version: str = Field(min_length=1)
    assertion_count: int = Field(ge=1)
    full_regression_test_count: int = Field(ge=1)
    runtime_schema_count: int = Field(ge=1)
    status: Literal["passed"] = "passed"


class Phase4CompletionMetric(Contract):
    metric_name: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    status: Phase4MetricStatus
    value: int | float | str | bool | None = None
    unit: str | None = None
    evidence_qualifications: tuple[str, ...]
    basis: str = Field(min_length=1)

    @model_validator(mode="after")
    def metric_status_is_coherent(self) -> "Phase4CompletionMetric":
        if self.status == Phase4MetricStatus.MEASURED and self.value is None:
            raise ValueError("measured completion metric requires a value")
        if self.status == Phase4MetricStatus.PENDING and self.value is not None:
            raise ValueError("pending completion metric cannot claim a value")
        if self.status in {
            Phase4MetricStatus.MEASURED,
            Phase4MetricStatus.QUALIFIED_MECHANICS,
        } and not self.evidence_qualifications:
            raise ValueError("qualified completion metric requires evidence")
        return self


class Phase4CompletionGate(Contract):
    gate_number: int = Field(ge=1, le=19)
    gate_name: str = Field(min_length=1)
    status: Phase4GateStatus
    evidence_qualifications: tuple[str, ...]
    basis: str = Field(min_length=1)
    blocking_findings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def gate_status_is_coherent(self) -> "Phase4CompletionGate":
        if self.status == Phase4GateStatus.COMPLETE and (
            not self.evidence_qualifications or self.blocking_findings
        ):
            raise ValueError("complete gate requires evidence and no blockers")
        if self.status != Phase4GateStatus.COMPLETE and not self.blocking_findings:
            raise ValueError("non-complete gate requires a blocking finding")
        return self


class Phase4CompletionIntegrityFinding(Contract):
    finding_code: str = Field(pattern=r"^phase4\.[a-z0-9_.-]+$")
    severity: Literal["information", "warning", "error", "fatal"]
    message: str = Field(min_length=1)
    evidence_relative_path: str | None = None
    gate_numbers: tuple[int, ...] = ()


class Phase4CompletionReport(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    report_id: str = Field(pattern=r"^phase4completion_[a-f0-9]{32}$")
    predecessor_report_id: str | None = Field(
        default=None, pattern=r"^phase4completion_[a-f0-9]{32}$"
    )
    generated_at: datetime
    application_version: str = Field(min_length=1)
    target_application_version: str = Field(min_length=1)
    contract_version_reported: str = Field(min_length=1)
    repository_branch: str = Field(min_length=1)
    starting_repository_head: str = Field(pattern=r"^[a-f0-9]{40}$")
    final_repository_head: str = Field(pattern=r"^[a-f0-9]{40}$")
    phase_changes_committed_at_audit: bool
    policy: Phase4CompletionPolicy
    evidence: tuple[Phase4CompletionEvidence, ...] = Field(min_length=1)
    metrics: tuple[Phase4CompletionMetric, ...] = Field(min_length=1)
    gates: tuple[Phase4CompletionGate, ...] = Field(
        min_length=19, max_length=19
    )
    integrity_findings: tuple[Phase4CompletionIntegrityFinding, ...]
    boundary_statements: tuple[str, ...] = Field(min_length=5)
    known_limitations: tuple[str, ...]
    unresolved_concerns: tuple[str, ...]
    status: Literal["complete", "in_progress", "blocked"]
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def completion_state_is_coherent(self) -> "Phase4CompletionReport":
        if tuple(item.gate_number for item in self.gates) != tuple(
            range(1, 20)
        ):
            raise ValueError("completion gates must be ordered 1 through 19")
        qualifications = [item.qualification for item in self.evidence]
        if len(qualifications) != len(set(qualifications)):
            raise ValueError("completion evidence must be unique")
        names = [item.metric_name for item in self.metrics]
        if len(names) != len(set(names)):
            raise ValueError("completion metrics must be unique")
        complete = all(
            item.status == Phase4GateStatus.COMPLETE for item in self.gates
        )
        fatal = any(
            item.severity in {"error", "fatal"}
            for item in self.integrity_findings
        )
        expected = (
            "complete"
            if complete and not fatal
            else ("blocked" if fatal else "in_progress")
        )
        if self.status != expected:
            raise ValueError("completion status disagrees with gates")
        return self


PHASE4_COMPLETION_CONTRACT_MODELS = (
    Phase4LongRecordingQualification,
    Phase4CompletionPolicy,
    Phase4CompletionEvidence,
    Phase4CompletionMetric,
    Phase4CompletionGate,
    Phase4CompletionIntegrityFinding,
    Phase4CompletionReport,
)
