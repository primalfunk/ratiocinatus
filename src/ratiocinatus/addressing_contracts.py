"""Exact time-domain, timeline, and interval-mapping contracts."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract

SOURCE_TIMELINE_FORMAT_VERSION = "1.0.0"
INTERVAL_MAPPING_FORMAT_VERSION = "1.0.0"


class TimeDomain(str, Enum):
    SOURCE_MEDIA = "source_media"
    NORMALIZED_CORPUS = "normalized_corpus"
    DERIVATIVE_LOCAL = "derivative_local"
    CHUNK_LOCAL = "chunk_local"


class MappingClassification(str, Enum):
    EXACT = "exact"
    ROUNDED = "rounded"
    CLIPPED = "clipped"
    DISCONTINUOUS = "discontinuous"
    UNAVAILABLE = "unavailable"
    AMBIGUOUS = "ambiguous"


class MediaTimeBase(Contract):
    numerator: int
    denominator: int = Field(gt=0)


class MediaTimestamp(Contract):
    domain: TimeDomain
    microseconds: int

    @model_validator(mode="after")
    def non_source_time_is_non_negative(self) -> "MediaTimestamp":
        if self.domain != TimeDomain.SOURCE_MEDIA and self.microseconds < 0:
            raise ValueError("normalized and local timestamps cannot be negative")
        return self


class MediaDuration(Contract):
    microseconds: int = Field(gt=0)


class MediaInterval(Contract):
    domain: TimeDomain
    start_microseconds: int
    duration_microseconds: int = Field(gt=0)

    @model_validator(mode="after")
    def non_source_interval_is_non_negative(self) -> "MediaInterval":
        if self.domain != TimeDomain.SOURCE_MEDIA and self.start_microseconds < 0:
            raise ValueError("normalized and local intervals cannot begin negative")
        return self


class SourceTimeline(Contract):
    format_version: Literal["1.0.0"] = SOURCE_TIMELINE_FORMAT_VERSION
    source_id: str = Field(pattern=r"^src_[a-f0-9]{32}$")
    source_start_microseconds: int
    source_duration_microseconds: int = Field(gt=0)
    corpus_start_microseconds: int = Field(default=0, ge=0)
    corpus_duration_microseconds: int = Field(gt=0)
    audio_stream_id: str | None = Field(
        default=None, pattern=r"^stream_[a-f0-9]{32}$"
    )
    audio_start_microseconds: int | None = None
    audio_duration_microseconds: int | None = Field(default=None, gt=0)
    video_stream_id: str | None = Field(
        default=None, pattern=r"^stream_[a-f0-9]{32}$"
    )
    video_start_microseconds: int | None = None
    video_duration_microseconds: int | None = Field(default=None, gt=0)
    variable_frame_rate: bool = False
    discontinuities: tuple[MediaInterval, ...] = ()
    mapping_offset_microseconds: int

    @model_validator(mode="after")
    def timeline_is_consistent(self) -> "SourceTimeline":
        if self.corpus_start_microseconds != 0:
            raise ValueError("normalized corpus time must begin at zero")
        if self.corpus_duration_microseconds != self.source_duration_microseconds:
            raise ValueError("Phase 1 passthrough timeline durations must agree")
        if self.mapping_offset_microseconds != self.source_start_microseconds:
            raise ValueError("mapping offset must equal source start")
        if any(
            interval.domain != TimeDomain.SOURCE_MEDIA
            for interval in self.discontinuities
        ):
            raise ValueError("timeline discontinuities must use source media time")
        return self


class IntervalMappingSegment(Contract):
    source: MediaInterval
    target: MediaInterval
    classification: MappingClassification


class IntervalMapping(Contract):
    format_version: Literal["1.0.0"] = INTERVAL_MAPPING_FORMAT_VERSION
    source_id: str = Field(pattern=r"^src_[a-f0-9]{32}$")
    source_domain: TimeDomain
    target_domain: TimeDomain
    requested: MediaInterval
    mapped: MediaInterval | None = None
    classification: MappingClassification
    segments: tuple[IntervalMappingSegment, ...] = ()
    tolerance_microseconds: int = Field(default=0, ge=0)
    explanation: str


class TimestampMapping(Contract):
    format_version: Literal["1.0.0"] = INTERVAL_MAPPING_FORMAT_VERSION
    source_id: str = Field(pattern=r"^src_[a-f0-9]{32}$")
    requested: MediaTimestamp
    mapped: MediaTimestamp | None = None
    classification: MappingClassification
    tolerance_microseconds: int = Field(default=0, ge=0)
    explanation: str


ADDRESSING_CONTRACT_MODELS = (
    MediaTimeBase,
    MediaTimestamp,
    MediaDuration,
    MediaInterval,
    SourceTimeline,
    IntervalMappingSegment,
    IntervalMapping,
    TimestampMapping,
)
