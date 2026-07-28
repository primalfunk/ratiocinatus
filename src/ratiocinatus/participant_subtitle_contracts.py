"""Participant-labeled subtitle presentation-derivative contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from .addressing_contracts import MediaInterval, TimeDomain
from .contracts import Contract, Sha256
from .speaker_transcript_contracts import SpeakerAttributionKind
from .subtitle_contracts import (
    SubtitleExportFile,
    SubtitleExportPolicy,
    SubtitleLossRecord,
)

PARTICIPANT_SUBTITLE_FORMAT_VERSION = "1.0.0"
PARTICIPANT_SUBTITLE_POLICY_VERSION = "1.0.0"


class ParticipantSubtitlePolicy(Contract):
    policy_version: Literal["1.0.0"] = PARTICIPANT_SUBTITLE_POLICY_VERSION
    subtitle_policy: SubtitleExportPolicy = SubtitleExportPolicy()
    label_placement: Literal["first_line"] = "first_line"
    sequential_multi_attribution_policy: Literal[
        "retain_combined_labels_without_text_partition"
    ] = "retain_combined_labels_without_text_partition"
    overlap_label_prefix: Literal["OVERLAP: "] = "OVERLAP: "
    unknown_label: Literal["REVIEWED: UNKNOWN"] = "REVIEWED: UNKNOWN"
    unattributed_label: Literal["UNATTRIBUTED"] = "UNATTRIBUTED"
    conflict_policy: Literal["refuse_export"] = "refuse_export"
    authoritative_identity_record: Literal[False] = False


class ParticipantSubtitleCue(Contract):
    format_version: Literal["1.0.0"] = PARTICIPANT_SUBTITLE_FORMAT_VERSION
    cue_id: str = Field(pattern=r"^participantcue_[a-f0-9]{32}$")
    sequence_position: int = Field(ge=0)
    source_interval: MediaInterval
    normalized_audio_interval: MediaInterval
    rounded_start_milliseconds: int = Field(ge=0)
    rounded_end_milliseconds: int = Field(gt=0)
    speaker_label: str = Field(min_length=1)
    text: str = Field(min_length=1)
    rendered_lines: tuple[str, ...] = Field(min_length=2)
    source_segment_ids: tuple[str, ...] = Field(min_length=1)
    attribution_span_ids: tuple[str, ...] = Field(min_length=1)
    identity_ids: tuple[str, ...] = ()
    identity_view_entry_ids: tuple[str, ...] = ()
    attribution_kinds: tuple[SpeakerAttributionKind, ...] = Field(min_length=1)
    unresolved: bool
    overlap_disclosed: bool
    findings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def timing_labels_and_references_are_consistent(
        self,
    ) -> "ParticipantSubtitleCue":
        if (
            self.source_interval.domain != TimeDomain.SOURCE_MEDIA
            or self.normalized_audio_interval.domain
            != TimeDomain.NORMALIZED_CORPUS
            or self.source_interval.duration_microseconds
            != self.normalized_audio_interval.duration_microseconds
        ):
            raise ValueError("participant subtitle cue mapping is invalid")
        if self.rounded_end_milliseconds <= self.rounded_start_milliseconds:
            raise ValueError("participant subtitle rounded interval must be positive")
        if self.rendered_lines[0] != self.speaker_label:
            raise ValueError("participant label must be the first subtitle line")
        if any(not line or "\n" in line or "\r" in line for line in self.rendered_lines):
            raise ValueError("participant subtitle lines must be non-empty single lines")
        for values, label in (
            (self.source_segment_ids, "source segments"),
            (self.attribution_span_ids, "attribution spans"),
            (self.identity_ids, "identities"),
            (self.identity_view_entry_ids, "identity-view entries"),
            (self.attribution_kinds, "attribution kinds"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"participant subtitle {label} must be unique")
        if (
            SpeakerAttributionKind.CONFLICTED in self.attribution_kinds
            or self.speaker_label == "REVIEWED: CONFLICT"
        ):
            raise ValueError("conflicted participant subtitle cue is prohibited")
        return self


class ParticipantSubtitleManifest(Contract):
    format_version: Literal["1.0.0"] = PARTICIPANT_SUBTITLE_FORMAT_VERSION
    export_id: str = Field(pattern=r"^participantsubtitle_[a-f0-9]{32}$")
    speaker_transcript_view_id: str = Field(
        pattern=r"^speakertranscript_[a-f0-9]{32}$"
    )
    source_assembly_id: str = Field(pattern=r"^txassembly_[a-f0-9]{32}$")
    source_transcript_version_id: str = Field(
        pattern=r"^txversion_[a-f0-9]{32}$"
    )
    source_revision_id: str | None = Field(
        default=None, pattern=r"^txrevision_[a-f0-9]{32}$"
    )
    identity_view_assembly_id: str = Field(
        pattern=r"^identityviewassembly_[a-f0-9]{32}$"
    )
    reviewed_identity_view_id: str = Field(
        pattern=r"^identityview_[a-f0-9]{32}$"
    )
    diarization_run_id: str = Field(pattern=r"^diarun_[a-f0-9]{32}$")
    corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    source_id: str = Field(pattern=r"^src_[a-f0-9]{32}$")
    normalized_audio_duration_microseconds: int = Field(gt=0)
    source_mapping_offset_microseconds: int
    generated_at: datetime
    policy: ParticipantSubtitlePolicy
    cues: tuple[ParticipantSubtitleCue, ...]
    losses: tuple[SubtitleLossRecord, ...]
    files: tuple[SubtitleExportFile, ...]
    status: Literal["complete", "warning"]
    integrity_sha256: Sha256


class ParticipantSubtitleReport(Contract):
    format_version: Literal["1.0.0"] = PARTICIPANT_SUBTITLE_FORMAT_VERSION
    report_id: str = Field(pattern=r"^participantsubtitlereport_[a-f0-9]{32}$")
    export_id: str = Field(pattern=r"^participantsubtitle_[a-f0-9]{32}$")
    generated_at: datetime
    cue_count: int = Field(ge=0)
    reviewed_cue_count: int = Field(ge=0)
    machine_cue_count: int = Field(ge=0)
    unresolved_cue_count: int = Field(ge=0)
    unattributed_cue_count: int = Field(ge=0)
    multiple_candidate_cue_count: int = Field(ge=0)
    overlap_disclosure_count: int = Field(ge=0)
    loss_record_count: int = Field(ge=0)
    checked_formats: tuple[str, ...]
    findings: tuple[str, ...]
    limitations: tuple[str, ...]
    status: Literal["complete", "warning"]
    valid: bool
    integrity_sha256: Sha256


PARTICIPANT_SUBTITLE_CONTRACT_MODELS = (
    ParticipantSubtitlePolicy,
    ParticipantSubtitleCue,
    ParticipantSubtitleManifest,
    ParticipantSubtitleReport,
)
