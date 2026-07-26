"""Authoritative, closed Phase 0 runtime contracts.

JSON schemas are derived from these Pydantic models; there is no second
hand-maintained contract definition.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from .version import CONTRACT_VERSION, REPORT_VERSION, WORKSPACE_VERSION

Identifier = Annotated[
    str,
    Field(pattern=r"^(ws|src|art|op|inv|prov|finding|report)_[a-z0-9]{16,64}$"),
]
Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class Contract(BaseModel):
    """Strict immutable base for authoritative values."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    contract_version: str = CONTRACT_VERSION

    @field_validator("*")
    @classmethod
    def aware_datetimes(cls, value: Any) -> Any:
        if isinstance(value, datetime) and value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return value


class Severity(str, Enum):
    INFORMATION = "information"
    WARNING = "warning"
    ERROR = "error"
    FATAL = "fatal"


class IntegrityState(str, Enum):
    UNCHECKED = "unchecked"
    VALID = "valid"
    INVALID = "invalid"


class ArtifactState(str, Enum):
    PROPOSED = "proposed"
    VALIDATED = "validated"
    SUPERSEDED = "superseded"
    MALFORMED = "malformed"


class OperationStatus(str, Enum):
    REQUESTED = "requested"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ReplayStatus(str, Enum):
    MATCH = "match"
    MISMATCH = "mismatch"
    UNSUPPORTED = "unsupported"


class Capability(str, Enum):
    MEDIA_INSPECTION = "media_inspection"
    TRANSCRIPTION = "transcription"
    DIARIZATION = "diarization"
    EMBEDDING = "embedding"
    STRUCTURED_GENERATION = "structured_generation"
    RENDERING = "rendering"


class ProvenanceKind(str, Enum):
    DETERMINISTIC_CODE = "deterministic_code"
    EXTERNAL_COMMAND = "external_command"
    PROVIDER = "provider"
    HUMAN_REVIEW = "human_review"
    IMPORT = "import"


class FailureKind(str, Enum):
    INVALID_REQUEST = "invalid_request"
    MISSING_INPUT = "missing_input"
    UNSUPPORTED_VERSION = "unsupported_version"
    UNAVAILABLE_PROVIDER = "unavailable_provider"
    PROVIDER_FAILURE = "provider_failure"
    MALFORMED_PROVIDER_OUTPUT = "malformed_provider_output"
    INTEGRITY_FAILURE = "integrity_failure"
    PERSISTENCE_FAILURE = "persistence_failure"
    VALIDATION_FAILURE = "validation_failure"
    INTERNAL_FAILURE = "internal_failure"


class SourceReference(Contract):
    original: str = Field(min_length=1)
    reference_kind: Literal["file", "uri", "symbolic"] = "file"
    display_name: str | None = None


class SourceFingerprint(Contract):
    algorithm: Literal["sha256"] = "sha256"
    digest: Sha256
    byte_size: int = Field(ge=0)


class SourceInterval(Contract):
    source_id: Identifier
    start_microseconds: int = Field(ge=0)
    duration_microseconds: int = Field(gt=0)


class ConfigurationSnapshot(Contract):
    workspace: str
    serialization_policy: Literal["canonical-json-1"] = "canonical-json-1"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    provider_selection: tuple[str, ...] = ()
    deterministic: bool = False
    copy_sources: bool = False
    report_output: str = "reports"
    snapshot_hash: Sha256 | None = None


class RegisteredSource(Contract):
    source_id: Identifier
    reference: SourceReference
    fingerprint: SourceFingerprint
    media_type: str | None
    registered_at: datetime
    configuration_hash: Sha256
    provenance_id: Identifier
    integrity: IntegrityState = IntegrityState.VALID
    duplicate_of: Identifier | None = None


class ArtifactReference(Contract):
    artifact_id: Identifier
    expected_hash: Sha256
    artifact_type: str


class EvidenceArtifact(Contract):
    artifact_type: str = Field(min_length=1)
    payload: Any
    synthetic: bool = False


class ArtifactEnvelope(Contract):
    artifact_id: Identifier
    artifact_type: str
    created_at: datetime
    creation_operation_id: Identifier
    dependencies: tuple[ArtifactReference, ...] = ()
    provenance_ids: tuple[Identifier, ...] = ()
    content_hash: Sha256
    state: ArtifactState = ArtifactState.VALIDATED
    supersedes: Identifier | None = None
    artifact: EvidenceArtifact


class ProvenanceRecord(Contract):
    provenance_id: Identifier
    sequence: int = Field(ge=0)
    kind: ProvenanceKind
    recorded_at: datetime
    operation_id: Identifier
    input_ids: tuple[str, ...] = ()
    output_ids: tuple[str, ...] = ()
    configuration_hash: Sha256
    application_version: str
    provider_invocation_id: Identifier | None = None
    validation_finding_ids: tuple[Identifier, ...] = ()
    note: str | None = None


class ProviderDescriptor(Contract):
    provider_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    display_name: str
    provider_version: str
    capabilities: tuple[Capability, ...]
    mock: bool
    deterministic: bool
    available: bool


class ProviderInvocation(Contract):
    invocation_id: Identifier
    provider: ProviderDescriptor
    capability: Capability
    operation_id: Identifier
    input_hash: Sha256
    configuration_hash: Sha256
    seed: int | None = None
    decoding_policy: str | None = None
    invoked_at: datetime


class ProviderResult(Contract):
    invocation_id: Identifier
    success: bool
    output: EvidenceArtifact | None = None
    failure: FailureKind | None = None
    message: str | None = None

    @model_validator(mode="after")
    def result_consistent(self) -> "ProviderResult":
        if self.success and (self.output is None or self.failure is not None):
            raise ValueError("successful provider result requires output and no failure")
        if not self.success and (self.failure is None or self.output is not None):
            raise ValueError("failed provider result requires failure and no output")
        return self


class OperationRequest(Contract):
    operation_id: Identifier
    operation_type: Literal["source.register", "provider.invoke", "workspace.report"]
    requested_at: datetime
    configuration: ConfigurationSnapshot
    input_ids: tuple[str, ...] = ()
    provider_id: str | None = None
    capability: Capability | None = None
    parameters: tuple[tuple[str, str], ...] = ()


class OperationResult(Contract):
    operation_id: Identifier
    status: OperationStatus
    completed_at: datetime
    artifact_ids: tuple[Identifier, ...] = ()
    provenance_ids: tuple[Identifier, ...] = ()
    failure: FailureKind | None = None
    message: str | None = None


class ReplayRecord(Contract):
    report_id: Identifier
    original_operation_id: Identifier
    replayed_at: datetime
    status: ReplayStatus
    expected_hashes: tuple[Sha256, ...]
    reproduced_hashes: tuple[Sha256, ...]
    reason: str | None = None


class ValidationFinding(Contract):
    finding_id: Identifier
    severity: Severity
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]+$")
    message: str
    subject_id: str | None = None


class IntegrityReport(Contract):
    report_id: Identifier
    generated_at: datetime
    workspace_id: Identifier
    findings: tuple[ValidationFinding, ...]
    valid: bool
    report_version: str = REPORT_VERSION


class PhaseReport(Contract):
    report_id: Identifier
    generated_at: datetime
    phase: Literal["0"] = "0"
    status: Literal["complete", "partial", "mocked", "deferred", "unsupported", "failed"]
    summary: str
    findings: tuple[ValidationFinding, ...] = ()
    report_version: str = REPORT_VERSION


class WorkspaceManifest(Contract):
    workspace_id: Identifier
    created_at: datetime
    application_version: str
    workspace_version: str = WORKSPACE_VERSION
    canonical_serialization_version: str
    configuration_hash: Sha256


CONTRACT_MODELS = (
    SourceReference, SourceFingerprint, SourceInterval, RegisteredSource,
    EvidenceArtifact, ArtifactReference, ArtifactEnvelope, ProvenanceRecord,
    ProviderDescriptor, ProviderInvocation, ProviderResult,
    ConfigurationSnapshot, OperationRequest, OperationResult, ReplayRecord,
    ValidationFinding, IntegrityReport, PhaseReport, WorkspaceManifest,
)

