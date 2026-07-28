"""Phase 3 integrity inventory and completion-report contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract, Sha256

PHASE3_COMPLETION_FORMAT_VERSION = "1.0.0"
PHASE3_COMPLETION_POLICY_VERSION = "1.0.0"


class CompletionEvidenceClass(str, Enum):
    MEASURED_EVALUATION = "measured_evaluation"
    SYNTHETIC_MECHANICS = "synthetic_mechanics"
    HUMAN_DECISION_MECHANICS = "human_decision_mechanics"
    PRESENTATION_VALIDATION = "presentation_validation"
    PROVIDER_CLAIM = "provider_claim"
    FUTURE_EXPECTATION = "future_expectation"


class CompletionGateStatus(str, Enum):
    COMPLETE = "complete"
    PENDING = "pending"
    BLOCKED = "blocked"


class CompletionMetricStatus(str, Enum):
    MEASURED = "measured"
    QUALIFIED_MECHANICS = "qualified_mechanics"
    PENDING = "pending"
    UNAVAILABLE = "unavailable"


class Phase3CompletionPolicy(Contract):
    policy_version: Literal["1.0.0"] = PHASE3_COMPLETION_POLICY_VERSION
    required_gate_count: Literal[18] = 18
    validate_evidence_before_inventory: Literal[True] = True
    require_machine_and_human_reports: Literal[True] = True
    separate_evidence_classes: Literal[True] = True
    incomplete_evidence_action: Literal["report_in_progress"] = (
        "report_in_progress"
    )
    corrupt_evidence_action: Literal["refuse"] = "refuse"
    complete_requires_all_gates: Literal[True] = True


class Phase3CompletionEvidence(Contract):
    qualification: str = Field(pattern=r"^phase-3-[a-z0-9-]+$")
    machine_report_relative_path: str = Field(
        pattern=r"^phase-3-[a-z0-9-]+\.json$"
    )
    machine_report_sha256: Sha256
    machine_report_byte_size: int = Field(gt=0)
    human_report_relative_path: str = Field(
        pattern=r"^phase-3-[a-z0-9-]+\.md$"
    )
    human_report_sha256: Sha256
    human_report_byte_size: int = Field(gt=0)
    evidence_class: CompletionEvidenceClass
    application_version: str = Field(min_length=1)
    target_application_version: str = Field(min_length=1)
    assertion_count: int = Field(ge=1)
    full_regression_test_count: int = Field(ge=1)
    runtime_schema_count: int = Field(ge=1)
    status: Literal["passed"] = "passed"


class Phase3CompletionMetric(Contract):
    metric_name: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    status: CompletionMetricStatus
    value: int | float | str | bool | None = None
    unit: str | None = None
    evidence_qualifications: tuple[str, ...]
    basis: str = Field(min_length=1)

    @model_validator(mode="after")
    def value_matches_status(self) -> "Phase3CompletionMetric":
        if self.status == CompletionMetricStatus.MEASURED and self.value is None:
            raise ValueError("measured completion metric requires a value")
        if self.status == CompletionMetricStatus.PENDING and self.value is not None:
            raise ValueError("pending completion metric cannot claim a value")
        if (
            self.status
            in {
                CompletionMetricStatus.MEASURED,
                CompletionMetricStatus.QUALIFIED_MECHANICS,
            }
            and not self.evidence_qualifications
        ):
            raise ValueError("qualified metric requires evidence")
        return self


class Phase3ProviderDisclosure(Contract):
    provider_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    provider_version: str = Field(min_length=1)
    production_provider_selected: bool
    model_id: str | None = None
    model_version: str | None = None
    model_fingerprint: Sha256 | None = None
    license_expression: str | None = None
    model_redistributed: bool
    claims: tuple[str, ...]
    limitations: tuple[str, ...]

    @model_validator(mode="after")
    def model_state_is_consistent(self) -> "Phase3ProviderDisclosure":
        if self.production_provider_selected and (
            self.model_id is None or self.model_version is None
        ):
            raise ValueError("selected production provider requires model identity")
        if not self.production_provider_selected and any(
            value is not None
            for value in (
                self.model_id,
                self.model_version,
                self.model_fingerprint,
            )
        ):
            raise ValueError(
                "unselected production provider cannot claim a model"
            )
        return self


class Phase3CompletionGate(Contract):
    gate_number: int = Field(ge=1, le=18)
    gate_name: str = Field(min_length=1)
    status: CompletionGateStatus
    evidence_qualifications: tuple[str, ...]
    basis: str = Field(min_length=1)
    blocking_findings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def status_is_consistent(self) -> "Phase3CompletionGate":
        if self.status == CompletionGateStatus.COMPLETE and (
            not self.evidence_qualifications or self.blocking_findings
        ):
            raise ValueError(
                "complete gate requires evidence and no blocking findings"
            )
        if self.status != CompletionGateStatus.COMPLETE and not (
            self.blocking_findings
        ):
            raise ValueError("non-complete gate requires a finding")
        return self


class Phase3IntegrityFinding(Contract):
    finding_code: str = Field(pattern=r"^phase3\.[a-z0-9_.-]+$")
    severity: Literal["information", "warning", "error", "fatal"]
    message: str = Field(min_length=1)
    evidence_relative_path: str | None = None
    gate_numbers: tuple[int, ...] = ()


class Phase3CompletionReport(Contract):
    format_version: Literal["1.0.0"] = PHASE3_COMPLETION_FORMAT_VERSION
    report_id: str = Field(pattern=r"^phase3completion_[a-f0-9]{32}$")
    predecessor_report_id: str | None = Field(
        default=None, pattern=r"^phase3completion_[a-f0-9]{32}$"
    )
    generated_at: datetime
    application_version: str = Field(min_length=1)
    target_application_version: str = Field(min_length=1)
    contract_version_reported: str = Field(min_length=1)
    workspace_format_version: str = Field(min_length=1)
    report_version: str = Field(min_length=1)
    repository_branch: str = Field(min_length=1)
    starting_repository_head: str = Field(pattern=r"^[a-f0-9]{40}$")
    final_repository_head: str = Field(pattern=r"^[a-f0-9]{40}$")
    phase_changes_committed_at_audit: bool
    policy: Phase3CompletionPolicy
    provider: Phase3ProviderDisclosure
    evidence: tuple[Phase3CompletionEvidence, ...] = Field(min_length=1)
    metrics: tuple[Phase3CompletionMetric, ...] = Field(min_length=1)
    gates: tuple[Phase3CompletionGate, ...] = Field(min_length=18, max_length=18)
    integrity_findings: tuple[Phase3IntegrityFinding, ...]
    privacy_and_export_decisions: tuple[str, ...] = Field(min_length=1)
    boundary_statements: tuple[str, ...] = Field(min_length=4)
    known_limitations: tuple[str, ...]
    unresolved_concerns: tuple[str, ...]
    status: Literal["complete", "in_progress", "blocked"]
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def completion_state_is_consistent(self) -> "Phase3CompletionReport":
        numbers = tuple(item.gate_number for item in self.gates)
        if numbers != tuple(range(1, 19)):
            raise ValueError("completion gates must be ordered 1 through 18")
        qualifications = [
            item.qualification for item in self.evidence
        ]
        if len(qualifications) != len(set(qualifications)):
            raise ValueError("completion evidence qualifications must be unique")
        metric_names = [item.metric_name for item in self.metrics]
        if len(metric_names) != len(set(metric_names)):
            raise ValueError("completion metric names must be unique")
        complete = all(
            item.status == CompletionGateStatus.COMPLETE for item in self.gates
        )
        fatal = any(
            item.severity in {"error", "fatal"}
            for item in self.integrity_findings
        )
        expected = "complete" if complete and not fatal else (
            "blocked" if fatal else "in_progress"
        )
        if self.status != expected:
            raise ValueError("completion status disagrees with gates or findings")
        return self


PHASE3_COMPLETION_CONTRACT_MODELS = (
    Phase3CompletionPolicy,
    Phase3CompletionEvidence,
    Phase3CompletionMetric,
    Phase3ProviderDisclosure,
    Phase3CompletionGate,
    Phase3IntegrityFinding,
    Phase3CompletionReport,
)
