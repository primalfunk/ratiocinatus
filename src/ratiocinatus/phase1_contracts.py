"""Strict Phase 1 audiovisual ingestion contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract, Sha256, SourceFingerprint

PHASE1_CONTRACT_VERSION = "0.1.0"
MEDIA_INSPECTION_FORMAT_VERSION = "1.0.0"


class MediaSupportStatus(str, Enum):
    SUPPORTED = "supported"
    RECOGNIZED_UNSUPPORTED = "recognized_unsupported"
    DECODABLE_UNQUALIFIED = "decodable_unqualified"
    MALFORMED = "malformed"
    ENCRYPTED_OR_DRM = "encrypted_or_drm"
    MISSING_REQUIRED_STREAMS = "missing_required_streams"
    UNSUPPORTED = "unsupported"


class StreamKind(str, Enum):
    VIDEO = "video"
    AUDIO = "audio"
    SUBTITLE = "subtitle"
    DATA = "data"
    ATTACHMENT = "attachment"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"


class MediaInspectionRequest(Contract):
    phase1_contract_version: Literal["0.1.0"] = PHASE1_CONTRACT_VERSION
    source: str = Field(min_length=1)
    source_fingerprint: SourceFingerprint
    ffprobe_executable: str | None = None
    timeout_seconds: int = Field(default=60, ge=1, le=3600)


class ExternalToolIdentity(Contract):
    executable: str = Field(min_length=1)
    executable_sha256: Sha256
    product: Literal["ffprobe", "ffmpeg"] = "ffprobe"
    version_line: str = Field(min_length=1)
    build_configuration: str | None = None


class ToolInvocationRecord(Contract):
    executable: str
    arguments: tuple[str, ...]
    started_at: datetime
    completed_at: datetime
    exit_code: int
    standard_output: str = ""
    standard_error: str
    timed_out: bool = False


class RawInspectionAttachment(Contract):
    media_inspection_format_version: Literal["1.0.0"] = MEDIA_INSPECTION_FORMAT_VERSION
    raw_json: str
    raw_json_sha256: Sha256
    invocation: ToolInvocationRecord
    tool: ExternalToolIdentity


class ContainerDescriptor(Contract):
    format_names: tuple[str, ...] = ()
    format_long_name: str | None = None
    duration_microseconds: int | None = Field(default=None, ge=0)
    start_time_microseconds: int | None = None
    bit_rate: int | None = Field(default=None, ge=0)
    file_size: int = Field(ge=0)
    tags: tuple[tuple[str, str], ...] = ()
    chapter_count: int = Field(default=0, ge=0)
    program_count: int = Field(default=0, ge=0)


class StreamDisposition(Contract):
    default: bool = False
    forced: bool = False
    attached_picture: bool = False
    hearing_impaired: bool = False
    visual_impaired: bool = False
    original: bool = False
    commentary: bool = False


class MediaStreamDescriptor(Contract):
    stream_id: str = Field(pattern=r"^stream_[a-f0-9]{32}$")
    stream_index: int = Field(ge=0)
    stream_type: StreamKind
    codec_name: str | None = None
    codec_long_name: str | None = None
    profile: str | None = None
    level: int | None = None
    codec_tag: str | None = None
    time_base: str | None = None
    start_timestamp: int | None = None
    start_time_microseconds: int | None = None
    duration_timestamp: int | None = None
    duration_microseconds: int | None = Field(default=None, ge=0)
    bit_rate: int | None = Field(default=None, ge=0)
    disposition: StreamDisposition
    language: str | None = None
    tags: tuple[tuple[str, str], ...] = ()


class VideoStreamDescriptor(MediaStreamDescriptor):
    stream_type: Literal[StreamKind.VIDEO] = StreamKind.VIDEO
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    pixel_format: str | None = None
    sample_aspect_ratio: str | None = None
    display_aspect_ratio: str | None = None
    average_frame_rate: str | None = None
    real_frame_rate: str | None = None
    color_range: str | None = None
    color_space: str | None = None
    color_transfer: str | None = None
    color_primaries: str | None = None
    rotation_degrees: int | None = None
    frame_count: int | None = Field(default=None, ge=0)


class AudioStreamDescriptor(MediaStreamDescriptor):
    stream_type: Literal[StreamKind.AUDIO] = StreamKind.AUDIO
    sample_format: str | None = None
    sample_rate: int | None = Field(default=None, gt=0)
    channels: int | None = Field(default=None, gt=0)
    channel_layout: str | None = None
    bits_per_sample: int | None = Field(default=None, ge=0)


class SubtitleStreamDescriptor(MediaStreamDescriptor):
    stream_type: Literal[StreamKind.SUBTITLE] = StreamKind.SUBTITLE


class MediaInspectionResult(Contract):
    phase1_contract_version: Literal["0.1.0"] = PHASE1_CONTRACT_VERSION
    source_id: str = Field(pattern=r"^src_[a-f0-9]{32}$")
    source: str
    source_fingerprint: SourceFingerprint
    support_status: MediaSupportStatus
    container: ContainerDescriptor
    streams: tuple[
        VideoStreamDescriptor
        | AudioStreamDescriptor
        | SubtitleStreamDescriptor
        | MediaStreamDescriptor,
        ...,
    ]
    warnings: tuple[str, ...] = ()
    raw_attachment: RawInspectionAttachment

    @model_validator(mode="after")
    def stream_indexes_and_ids_are_unique(self) -> "MediaInspectionResult":
        indexes = [stream.stream_index for stream in self.streams]
        identities = [stream.stream_id for stream in self.streams]
        if len(indexes) != len(set(indexes)):
            raise ValueError("stream indexes must be unique within a source")
        if len(identities) != len(set(identities)):
            raise ValueError("stream identities must be unique within a source")
        return self


PHASE1_CONTRACT_MODELS = (
    MediaInspectionRequest,
    ExternalToolIdentity,
    ToolInvocationRecord,
    RawInspectionAttachment,
    ContainerDescriptor,
    StreamDisposition,
    MediaStreamDescriptor,
    VideoStreamDescriptor,
    AudioStreamDescriptor,
    SubtitleStreamDescriptor,
    MediaInspectionResult,
)
