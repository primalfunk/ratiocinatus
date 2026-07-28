"""Timestamp-based video access contracts."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .addressing_contracts import (
    MappingClassification,
    MediaInterval,
    MediaTimestamp,
    SourceTimeline,
)
from .contracts import Contract, Sha256, SourceFingerprint
from .phase1_contracts import ToolInvocationRecord

VIDEO_ACCESS_POLICY_VERSION = "1.0.0"
VIDEO_ACCESS_FORMAT_VERSION = "1.0.0"


class VideoAccessStatus(str, Enum):
    AVAILABLE = "available"
    NOT_APPLICABLE = "not_applicable"
    UNQUALIFIED = "unqualified"
    REFUSED = "refused"


class VideoNormalizationPolicy(Contract):
    policy_version: Literal["1.0.0"] = VIDEO_ACCESS_POLICY_VERSION
    strategy: Literal["source_passthrough_timestamp_access"] = (
        "source_passthrough_timestamp_access"
    )
    frame_number_authoritative: Literal[False] = False
    preserve_full_frame: Literal[True] = True
    crop: Literal[False] = False
    resize: Literal[False] = False
    burn_captions: Literal[False] = False
    alter_speed: Literal[False] = False
    rotation_handling: Literal["preserve_metadata_no_bake"] = (
        "preserve_metadata_no_bake"
    )
    pixel_aspect_handling: Literal["preserve_metadata_no_rescale"] = (
        "preserve_metadata_no_rescale"
    )
    unsupported_pixel_format_action: Literal["refuse"] = "refuse"
    damaged_timestamp_action: Literal["refuse"] = "refuse"
    supported_pixel_formats: tuple[str, ...] = (
        "yuv420p",
        "yuvj420p",
        "nv12",
        "gray",
    )
    frame_search_radius_microseconds: int = Field(
        default=500_000, ge=33_000, le=10_000_000
    )
    timeout_seconds: int = Field(default=120, ge=1, le=3600)


class VideoAccessPlan(Contract):
    format_version: Literal["1.0.0"] = VIDEO_ACCESS_FORMAT_VERSION
    plan_id: str = Field(pattern=r"^videoaccess_[a-f0-9]{32}$")
    source_id: str = Field(pattern=r"^src_[a-f0-9]{32}$")
    source: str
    source_fingerprint: SourceFingerprint
    policy: VideoNormalizationPolicy
    status: VideoAccessStatus
    video_stream_id: str | None = Field(
        default=None, pattern=r"^stream_[a-f0-9]{32}$"
    )
    video_stream_index: int | None = Field(default=None, ge=0)
    timeline: SourceTimeline
    time_base: str | None = None
    average_frame_rate: str | None = None
    real_frame_rate: str | None = None
    variable_frame_rate: bool = False
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    pixel_format: str | None = None
    sample_aspect_ratio: str | None = None
    display_aspect_ratio: str | None = None
    rotation_degrees: int | None = None
    transformations: tuple[str, ...] = ()
    policy_findings: tuple[str, ...] = ()
    seek_qualified: bool = False
    explanation: str

    @model_validator(mode="after")
    def availability_matches_stream(self) -> "VideoAccessPlan":
        has_stream = self.video_stream_id is not None and self.video_stream_index is not None
        if self.status == VideoAccessStatus.NOT_APPLICABLE and has_stream:
            raise ValueError("audio-only access plan cannot identify a video stream")
        if self.status != VideoAccessStatus.NOT_APPLICABLE and not has_stream:
            raise ValueError("video access plan must identify its selected stream")
        return self


class FrameAccessRequest(Contract):
    plan_id: str = Field(pattern=r"^videoaccess_[a-f0-9]{32}$")
    corpus_timestamp: MediaTimestamp
    output: str


class FrameAccessResult(Contract):
    request: FrameAccessRequest
    source_timestamp: MediaTimestamp
    located_corpus_timestamp: MediaTimestamp
    classification: MappingClassification
    timestamp_error_microseconds: int = Field(ge=0)
    output: str
    content_sha256: Sha256
    byte_size: int = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    rotation_degrees: int | None = None
    display_transform_required: bool
    locator_invocation: ToolInvocationRecord
    extraction_invocation: ToolInvocationRecord


class FrameTimestampIndex(Contract):
    plan_id: str = Field(pattern=r"^videoaccess_[a-f0-9]{32}$")
    requested_interval: MediaInterval
    corpus_timestamps: tuple[MediaTimestamp, ...]
    truncated: bool
    invocation: ToolInvocationRecord


VIDEO_CONTRACT_MODELS = (
    VideoNormalizationPolicy,
    VideoAccessPlan,
    FrameAccessRequest,
    FrameAccessResult,
    FrameTimestampIndex,
)
