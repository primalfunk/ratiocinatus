"""Versioned decode-qualification contracts."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract
from .phase1_contracts import ExternalToolIdentity, StreamKind, ToolInvocationRecord
from .selection_contracts import StreamSelectionResult

DECODE_QUALIFICATION_POLICY_VERSION = "1.0.0"


class QualificationStatus(str, Enum):
    SUCCESS = "success"
    WARNING = "warning"
    FAILURE = "failure"
    NOT_PERFORMED = "not_performed"


class DecodeQualificationPolicy(Contract):
    policy_version: Literal["1.0.0"] = DECODE_QUALIFICATION_POLICY_VERSION
    probe_duration_microseconds: int = Field(
        default=1_000_000, ge=100_000, le=30_000_000
    )
    timeout_seconds: int = Field(default=120, ge=1, le=3600)
    full_decode: bool = False


class DecodeQualificationProbe(Contract):
    label: str = Field(pattern=r"^(early|middle|late|full)$")
    stream_id: str = Field(pattern=r"^stream_[a-f0-9]{32}$")
    stream_index: int = Field(ge=0)
    stream_type: StreamKind
    requested_start_microseconds: int = Field(ge=0)
    requested_duration_microseconds: int = Field(gt=0)
    status: QualificationStatus
    invocation: ToolInvocationRecord
    message: str | None = None


class DecodeQualificationResult(Contract):
    source_id: str = Field(pattern=r"^src_[a-f0-9]{32}$")
    policy: DecodeQualificationPolicy
    selection: StreamSelectionResult
    tool: ExternalToolIdentity
    inspection_status: QualificationStatus
    decode_start_status: QualificationStatus
    sampled_decode_status: QualificationStatus
    full_decode_status: QualificationStatus
    duration_plausibility_status: QualificationStatus
    probes: tuple[DecodeQualificationProbe, ...]
    warnings: tuple[str, ...] = ()
    valid: bool

    @model_validator(mode="after")
    def valid_requires_required_successes(self) -> "DecodeQualificationResult":
        required = (
            self.inspection_status,
            self.decode_start_status,
            self.sampled_decode_status,
            self.duration_plausibility_status,
        )
        expected = all(
            item in {QualificationStatus.SUCCESS, QualificationStatus.WARNING}
            for item in required
        )
        if self.valid != expected:
            raise ValueError("qualification validity must match required statuses")
        return self


QUALIFICATION_CONTRACT_MODELS = (
    DecodeQualificationPolicy,
    DecodeQualificationProbe,
    DecodeQualificationResult,
)
