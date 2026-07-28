"""Bounded packet-timestamp continuity qualification contracts."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .addressing_contracts import MediaInterval
from .contracts import Contract
from .phase1_contracts import ExternalToolIdentity, StreamKind, ToolInvocationRecord

PACKET_CONTINUITY_POLICY_VERSION = "1.0.0"
PACKET_CONTINUITY_FORMAT_VERSION = "1.0.0"


class PacketContinuityStatus(str, Enum):
    SUCCESS = "success"
    WARNING = "warning"
    FAILURE = "failure"


class PacketContinuityPolicy(Contract):
    policy_version: Literal["1.0.0"] = PACKET_CONTINUITY_POLICY_VERSION
    probe_duration_microseconds: int = Field(
        default=2_000_000, ge=100_000, le=30_000_000
    )
    timeout_seconds: int = Field(default=120, ge=1, le=3600)
    maximum_packets_per_probe: int = Field(default=20_000, ge=1, le=1_000_000)
    absolute_gap_warning_microseconds: int = Field(
        default=2_000_000, ge=1_000, le=60_000_000
    )
    duration_gap_multiplier: int = Field(default=10, ge=2, le=1000)


class PacketContinuityProbe(Contract):
    format_version: Literal["1.0.0"] = PACKET_CONTINUITY_FORMAT_VERSION
    label: Literal["early", "middle", "late"]
    stream_id: str = Field(pattern=r"^stream_[a-f0-9]{32}$")
    stream_index: int = Field(ge=0)
    stream_type: StreamKind
    requested_interval: MediaInterval
    packet_count: int = Field(ge=0)
    truncated: bool
    missing_pts_count: int = Field(ge=0)
    missing_dts_count: int = Field(ge=0)
    dts_regression_count: int = Field(ge=0)
    maximum_dts_gap_microseconds: int | None = Field(default=None, ge=0)
    discontinuities: tuple[MediaInterval, ...] = ()
    status: PacketContinuityStatus
    invocation: ToolInvocationRecord
    findings: tuple[str, ...] = ()


class PacketContinuityResult(Contract):
    format_version: Literal["1.0.0"] = PACKET_CONTINUITY_FORMAT_VERSION
    source_id: str = Field(pattern=r"^src_[a-f0-9]{32}$")
    policy: PacketContinuityPolicy
    tool: ExternalToolIdentity
    probes: tuple[PacketContinuityProbe, ...]
    discontinuities: tuple[MediaInterval, ...] = ()
    valid: bool

    @model_validator(mode="after")
    def validity_matches_probes(self) -> "PacketContinuityResult":
        expected = bool(self.probes) and all(
            probe.status != PacketContinuityStatus.FAILURE
            for probe in self.probes
        )
        if self.valid != expected:
            raise ValueError("packet continuity validity is inconsistent")
        return self


PACKET_CONTRACT_MODELS = (
    PacketContinuityPolicy,
    PacketContinuityProbe,
    PacketContinuityResult,
)
