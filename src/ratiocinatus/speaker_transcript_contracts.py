"""Speaker-labeled transcript presentation contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .addressing_contracts import MediaInterval, TimeDomain
from .contracts import Contract, Sha256
from .correction_contracts import TranscriptViewKind

SPEAKER_TRANSCRIPT_FORMAT_VERSION = "1.0.0"
SPEAKER_TRANSCRIPT_POLICY_VERSION = "1.0.0"


class SpeakerAttributionKind(str, Enum):
    REVIEWED = "reviewed"
    MACHINE_CLUSTER = "machine_cluster"
    UNKNOWN = "unknown"
    UNATTRIBUTED = "unattributed"
    MULTIPLE_CANDIDATES = "multiple_candidates"
    CONFLICTED = "conflicted"


class SpeakerLabeledTranscriptPolicy(Contract):
    policy_version: Literal["1.0.0"] = SPEAKER_TRANSCRIPT_POLICY_VERSION
    transcript_view_kind: TranscriptViewKind = (
        TranscriptViewKind.ORIGINAL_MACHINE
    )
    interval_association: Literal[
        "normalized_time_intersection_v1"
    ] = "normalized_time_intersection_v1"
    segment_policy: Literal[
        "preserve_source_segment_with_attribution_spans"
    ] = "preserve_source_segment_with_attribution_spans"
    unattributed_label: Literal["UNATTRIBUTED"] = "UNATTRIBUTED"
    machine_label_prefix: Literal["MACHINE: "] = "MACHINE: "
    multiple_candidate_separator: Literal[" + "] = " + "
    overlap_disclosure: Literal["required"] = "required"
    conflict_policy: Literal["block_trusted_rendering"] = (
        "block_trusted_rendering"
    )
    source_transcript_mutation: Literal["prohibited"] = "prohibited"


class SpeakerAttributionSpan(Contract):
    span_id: str = Field(pattern=r"^speakerattrspan_[a-f0-9]{32}$")
    source_interval: MediaInterval
    normalized_audio_interval: MediaInterval
    speaker_turn_ids: tuple[str, ...]
    transcript_segment_ids: tuple[str, ...]
    transcript_word_ids: tuple[str, ...] = ()
    attribution_kind: SpeakerAttributionKind
    original_machine_labels: tuple[str, ...] = ()
    reviewed_labels: tuple[str, ...] = ()
    identity_ids: tuple[str, ...] = ()
    identity_view_entry_ids: tuple[str, ...] = ()
    overlap_disclosed: bool
    findings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def span_mapping_and_labels_are_consistent(
        self,
    ) -> "SpeakerAttributionSpan":
        if (
            self.source_interval.domain != TimeDomain.SOURCE_MEDIA
            or self.normalized_audio_interval.domain
            != TimeDomain.NORMALIZED_CORPUS
            or self.source_interval.duration_microseconds
            != self.normalized_audio_interval.duration_microseconds
        ):
            raise ValueError("speaker attribution span mapping is invalid")
        for label in self.reviewed_labels:
            if not label.startswith("REVIEWED: "):
                raise ValueError("reviewed speaker labels require visible prefix")
        for values, label in (
            (self.speaker_turn_ids, "turn"),
            (self.transcript_segment_ids, "segment"),
            (self.transcript_word_ids, "word"),
            (self.identity_ids, "identity"),
            (self.identity_view_entry_ids, "identity-view entry"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"speaker attribution {label}s must be unique")
        if len(self.speaker_turn_ids) > 1 and not self.overlap_disclosed:
            raise ValueError("multiple speaker turns require overlap disclosure")
        return self


class SpeakerLabeledTranscriptSegment(Contract):
    segment_id: str = Field(
        pattern=r"^(txsegment|txviewsegment)_[a-f0-9]{32}$"
    )
    source_interval: MediaInterval
    normalized_audio_interval: MediaInterval
    source_text: str = Field(min_length=1)
    normalized_text: str = Field(min_length=1)
    attribution_spans: tuple[SpeakerAttributionSpan, ...] = Field(min_length=1)
    rendered_text: str = Field(min_length=1)

    @model_validator(mode="after")
    def attribution_spans_cover_segment(
        self,
    ) -> "SpeakerLabeledTranscriptSegment":
        if (
            self.source_interval.domain != TimeDomain.SOURCE_MEDIA
            or self.normalized_audio_interval.domain
            != TimeDomain.NORMALIZED_CORPUS
            or self.source_interval.duration_microseconds
            != self.normalized_audio_interval.duration_microseconds
        ):
            raise ValueError("speaker-labeled segment mapping is invalid")
        cursor = self.normalized_audio_interval.start_microseconds
        source_cursor = self.source_interval.start_microseconds
        for span in self.attribution_spans:
            if (
                span.normalized_audio_interval.start_microseconds != cursor
                or span.source_interval.start_microseconds != source_cursor
            ):
                raise ValueError(
                    "speaker attribution spans must be contiguous and ordered"
                )
            cursor += span.normalized_audio_interval.duration_microseconds
            source_cursor += span.source_interval.duration_microseconds
        if cursor != (
            self.normalized_audio_interval.start_microseconds
            + self.normalized_audio_interval.duration_microseconds
        ):
            raise ValueError("speaker attribution spans must cover the segment")
        return self


class SpeakerLabeledTranscriptView(Contract):
    format_version: Literal["1.0.0"] = SPEAKER_TRANSCRIPT_FORMAT_VERSION
    view_id: str = Field(pattern=r"^speakertranscript_[a-f0-9]{32}$")
    source_assembly_id: str = Field(pattern=r"^txassembly_[a-f0-9]{32}$")
    source_transcript_version_id: str = Field(
        pattern=r"^txversion_[a-f0-9]{32}$"
    )
    source_transcript_view_kind: TranscriptViewKind
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
    policy: SpeakerLabeledTranscriptPolicy
    configuration_hash: Sha256
    segments: tuple[SpeakerLabeledTranscriptSegment, ...]
    rendered_text: str
    trusted_for_participant_rendering: bool
    blocking_findings: tuple[str, ...] = ()
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def trust_and_source_view_agree(self) -> "SpeakerLabeledTranscriptView":
        if self.blocking_findings and self.trusted_for_participant_rendering:
            raise ValueError("blocked speaker transcript cannot be trusted")
        if self.source_transcript_view_kind != self.policy.transcript_view_kind:
            raise ValueError("speaker transcript source view disagrees with policy")
        corrected = (
            self.source_transcript_view_kind
            == TranscriptViewKind.CURRENT_CORRECTED
        )
        if corrected != (self.source_revision_id is not None):
            raise ValueError(
                "corrected speaker transcript requires revision lineage"
            )
        return self


class SpeakerLabeledTranscriptReport(Contract):
    format_version: Literal["1.0.0"] = SPEAKER_TRANSCRIPT_FORMAT_VERSION
    report_id: str = Field(pattern=r"^speakertranscriptreport_[a-f0-9]{32}$")
    view_id: str = Field(pattern=r"^speakertranscript_[a-f0-9]{32}$")
    generated_at: datetime
    segment_count: int = Field(ge=0)
    attribution_span_count: int = Field(ge=0)
    reviewed_span_count: int = Field(ge=0)
    machine_span_count: int = Field(ge=0)
    unknown_span_count: int = Field(ge=0)
    unattributed_span_count: int = Field(ge=0)
    multiple_candidate_span_count: int = Field(ge=0)
    conflict_span_count: int = Field(ge=0)
    overlap_disclosure_count: int = Field(ge=0)
    findings: tuple[str, ...]
    limitations: tuple[str, ...]
    status: Literal["complete", "warning", "blocked"]
    integrity_sha256: Sha256


SPEAKER_TRANSCRIPT_CONTRACT_MODELS = (
    SpeakerLabeledTranscriptPolicy,
    SpeakerAttributionSpan,
    SpeakerLabeledTranscriptSegment,
    SpeakerLabeledTranscriptView,
    SpeakerLabeledTranscriptReport,
)
