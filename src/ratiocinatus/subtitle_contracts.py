"""Versioned subtitle cue, export, loss, and validation contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .addressing_contracts import MediaInterval, TimeDomain
from .contracts import Contract, Sha256
from .correction_contracts import TranscriptViewKind

SUBTITLE_FORMAT_VERSION = "1.0.0"
SUBTITLE_EXPORT_POLICY_VERSION = "1.0.0"
SUBTITLE_ROUNDING_POLICY_VERSION = "1.0.0"


class SubtitleFormat(str, Enum):
    WEBVTT = "webvtt"
    SRT = "srt"


class SubtitleSegmentationOrigin(str, Enum):
    CANONICAL_SEGMENT = "canonical_segment"
    PROVIDER_WORD_TIMESTAMPS = "provider_word_timestamps"


class SubtitleLossClassification(str, Enum):
    MILLISECOND_TIMESTAMP_ROUNDING = "millisecond_timestamp_rounding"
    NORMALIZED_TEXT_RENDERING = "normalized_text_rendering"
    WORD_TIMING_SEGMENTATION = "word_timing_segmentation"
    LONG_CUE_RETAINED = "long_cue_retained"
    LINE_LENGTH_EXCEEDED = "line_length_exceeded"
    LOW_CONFIDENCE_IN_COMPANION_MANIFEST = (
        "low_confidence_in_companion_manifest"
    )
    FORMAT_METADATA_IN_COMPANION_MANIFEST = (
        "format_metadata_in_companion_manifest"
    )


class SubtitleTimestampRoundingPolicy(Contract):
    policy_version: Literal["1.0.0"] = SUBTITLE_ROUNDING_POLICY_VERSION
    resolution_microseconds: Literal[1000] = 1000
    start_rounding: Literal["floor"] = "floor"
    end_rounding: Literal["ceiling"] = "ceiling"
    minimum_rounded_duration_milliseconds: int = Field(
        default=1, ge=1, le=1000
    )


class SubtitleExportPolicy(Contract):
    policy_version: Literal["1.0.0"] = SUBTITLE_EXPORT_POLICY_VERSION
    formats: tuple[SubtitleFormat, ...] = (
        SubtitleFormat.WEBVTT,
        SubtitleFormat.SRT,
    )
    rounding: SubtitleTimestampRoundingPolicy = (
        SubtitleTimestampRoundingPolicy()
    )
    maximum_cue_duration_microseconds: int = Field(
        default=7_000_000, ge=100_000, le=60_000_000
    )
    maximum_cue_characters: int = Field(default=84, ge=10, le=1000)
    maximum_line_characters: int = Field(default=42, ge=5, le=500)
    maximum_lines_per_cue: int = Field(default=2, ge=1, le=10)
    long_cue_policy: Literal[
        "split_on_retained_word_timestamps_else_retain_and_record"
    ] = "split_on_retained_word_timestamps_else_retain_and_record"
    blocked_transcript_policy: Literal["refuse_export"] = "refuse_export"
    low_confidence_policy: Literal[
        "retain_cue_and_record_in_companion_manifest"
    ] = "retain_cue_and_record_in_companion_manifest"
    rendered_text_policy: Literal["use_normalized_text"] = "use_normalized_text"

    @model_validator(mode="after")
    def formats_are_unique(self) -> "SubtitleExportPolicy":
        if not self.formats or len(self.formats) != len(set(self.formats)):
            raise ValueError("subtitle formats must be non-empty and unique")
        if (
            self.maximum_line_characters * self.maximum_lines_per_cue
            < self.maximum_cue_characters
        ):
            raise ValueError(
                "line capacity must cover the configured cue character limit"
            )
        return self


class SubtitleCue(Contract):
    format_version: Literal["1.0.0"] = SUBTITLE_FORMAT_VERSION
    cue_id: str = Field(pattern=r"^cue_[a-f0-9]{32}$")
    sequence_position: int = Field(ge=0)
    source_interval: MediaInterval
    normalized_audio_interval: MediaInterval
    rounded_start_milliseconds: int = Field(ge=0)
    rounded_end_milliseconds: int = Field(gt=0)
    text: str = Field(min_length=1)
    rendered_lines: tuple[str, ...] = Field(min_length=1)
    source_artifact_ids: tuple[str, ...] = Field(min_length=1)
    retained_word_ids: tuple[str, ...] = ()
    low_confidence_region_ids: tuple[str, ...] = ()
    review_recommended: bool = False
    segmentation_origin: SubtitleSegmentationOrigin

    @model_validator(mode="after")
    def timing_and_text_are_consistent(self) -> "SubtitleCue":
        if self.source_interval.domain != TimeDomain.SOURCE_MEDIA:
            raise ValueError("subtitle source interval has wrong domain")
        if self.normalized_audio_interval.domain != TimeDomain.NORMALIZED_CORPUS:
            raise ValueError("subtitle normalized interval has wrong domain")
        if (
            self.source_interval.duration_microseconds
            != self.normalized_audio_interval.duration_microseconds
        ):
            raise ValueError("subtitle mapped durations disagree")
        if self.rounded_end_milliseconds <= self.rounded_start_milliseconds:
            raise ValueError("subtitle rounded interval must be positive")
        if any(not line or "\n" in line or "\r" in line for line in self.rendered_lines):
            raise ValueError("subtitle rendered lines must be non-empty single lines")
        return self


class SubtitleLossRecord(Contract):
    loss_id: str = Field(pattern=r"^subtitleloss_[a-f0-9]{32}$")
    cue_id: str | None = Field(
        default=None, pattern=r"^cue_[a-f0-9]{32}$"
    )
    classification: SubtitleLossClassification
    explanation: str = Field(min_length=1)


class SubtitleExportFile(Contract):
    subtitle_format: SubtitleFormat
    relative_path: str = Field(min_length=1)
    media_type: str = Field(min_length=1)
    content_sha256: Sha256
    byte_size: int = Field(gt=0)


class SubtitleExportManifest(Contract):
    format_version: Literal["1.0.0"] = SUBTITLE_FORMAT_VERSION
    export_id: str = Field(pattern=r"^subtitleexport_[a-f0-9]{32}$")
    base_assembly_id: str = Field(pattern=r"^txassembly_[a-f0-9]{32}$")
    revision_id: str | None = Field(
        default=None, pattern=r"^txrevision_[a-f0-9]{32}$"
    )
    transcript_version_id: str = Field(pattern=r"^txversion_[a-f0-9]{32}$")
    view_kind: TranscriptViewKind
    corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    source_id: str = Field(pattern=r"^src_[a-f0-9]{32}$")
    normalized_audio_duration_microseconds: int = Field(gt=0)
    source_mapping_offset_microseconds: int
    generated_at: datetime
    policy: SubtitleExportPolicy
    cues: tuple[SubtitleCue, ...]
    losses: tuple[SubtitleLossRecord, ...]
    files: tuple[SubtitleExportFile, ...]
    status: Literal["complete", "warning"]
    integrity_sha256: Sha256


class SubtitleValidationReport(Contract):
    format_version: Literal["1.0.0"] = SUBTITLE_FORMAT_VERSION
    report_id: str = Field(pattern=r"^subtitlevalidation_[a-f0-9]{32}$")
    export_id: str = Field(pattern=r"^subtitleexport_[a-f0-9]{32}$")
    transcript_version_id: str = Field(pattern=r"^txversion_[a-f0-9]{32}$")
    generated_at: datetime
    cue_count: int = Field(ge=0)
    reviewed_cue_count: int = Field(ge=0)
    split_cue_count: int = Field(ge=0)
    loss_record_count: int = Field(ge=0)
    maximum_start_rounding_loss_microseconds: int = Field(ge=0, le=999)
    maximum_end_rounding_loss_microseconds: int = Field(ge=0, le=999)
    checked_formats: tuple[SubtitleFormat, ...]
    findings: tuple[str, ...] = ()
    valid: bool


SUBTITLE_CONTRACT_MODELS = (
    SubtitleTimestampRoundingPolicy,
    SubtitleExportPolicy,
    SubtitleCue,
    SubtitleLossRecord,
    SubtitleExportFile,
    SubtitleExportManifest,
    SubtitleValidationReport,
)
