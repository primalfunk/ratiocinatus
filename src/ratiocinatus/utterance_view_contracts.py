"""Phase 4 canonical speaker-attributed transcript view contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .addressing_contracts import MediaInterval, TimeDomain
from .contracts import Contract, Sha256
from .phase4_contracts import (
    PHASE4_FORMAT_VERSION,
    UtteranceAttributionStatus,
    UtteranceReviewStatus,
)

UTTERANCE_VIEW_POLICY_VERSION = "1.0.0"


class SpeakerAttributedViewKind(str, Enum):
    MACHINE_CLUSTER = "machine_speaker_cluster"
    REVIEWED_IDENTITY = "reviewed_participant_identity"
    UNKNOWN_PRESERVING = "unknown_preserving"
    CORRECTION_AWARE = "correction_aware"
    OVERLAP_EXPANDED = "overlap_expanded"
    COMPACT_READING = "compact_reading"


class UtterancePresentationMarker(str, Enum):
    INCOMPLETE = "incomplete"
    INTERRUPTED = "interrupted"
    INTERRUPTING = "interrupting"
    RESUMES = "resumes"
    CONTINUATION = "continuation"
    OVERLAP = "overlap"
    QUOTATION = "quotation"
    EMBEDDED_SOURCE = "embedded_source"
    REPAIR_PROPOSED = "repair_proposed"
    REPAIR_ACCEPTED = "repair_accepted"
    UNKNOWN_SPEAKER = "unknown_speaker"
    CONFLICTING_SPEAKER = "conflicting_speaker"
    REVIEW_REQUIRED = "review_required"


class UtterancePresentationLossKind(str, Enum):
    OVERLAP_LINEARIZED = "overlap_linearized"
    MACHINE_CLUSTER_LABEL_UNAVAILABLE = "machine_cluster_label_unavailable"
    REVIEWED_IDENTITY_LABEL_UNAVAILABLE = "reviewed_identity_label_unavailable"
    CORRECTED_TEXT_UNAVAILABLE = "corrected_text_unavailable"
    COMPACT_MARKER_OMISSION = "compact_marker_omission"
    NONCONTIGUOUS_INTERVALS_LINEARIZED = "noncontiguous_intervals_linearized"


class SpeakerAttributedTranscriptPolicy(Contract):
    policy_version: Literal["1.0.0"] = UTTERANCE_VIEW_POLICY_VERSION
    source_timestamp_precision_microseconds: int = Field(default=1_000, ge=1)
    unknown_label: Literal["UNKNOWN"] = "UNKNOWN"
    conflict_label: Literal["CONFLICT"] = "CONFLICT"
    preserve_utterance_identifiers: Literal[True] = True
    preserve_source_intervals: Literal[True] = True
    preserve_unknown_speakers: Literal[True] = True
    overlap_linearization_must_be_disclosed: Literal[True] = True
    authoritative_replacement: Literal[False] = False


class RenderedUtterance(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    rendered_utterance_id: str = Field(
        pattern=r"^renderedutterance_[a-f0-9]{32}$"
    )
    utterance_id: str = Field(pattern=r"^utterance_[a-f0-9]{32}$")
    sequence_position: int = Field(ge=0)
    temporal_group_id: str = Field(pattern=r"^temporalgroup_[a-f0-9]{32}$")
    temporal_lane: int = Field(ge=0)
    simultaneous_with_utterance_ids: tuple[str, ...] = ()
    source_intervals: tuple[MediaInterval, ...] = Field(min_length=1)
    normalized_audio_intervals: tuple[MediaInterval, ...] = Field(min_length=1)
    source_timestamp_text: str = Field(min_length=1)
    speaker_label: str = Field(min_length=1)
    attribution_status: UtteranceAttributionStatus
    text: str
    markers: tuple[UtterancePresentationMarker, ...] = ()
    marker_details: tuple[str, ...] = ()
    rendered_line: str = Field(min_length=1)
    review_status: UtteranceReviewStatus
    evidence_references: tuple[str, ...] = Field(min_length=1)
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def addressing_and_markers_are_valid(self) -> "RenderedUtterance":
        for intervals, domain in (
            (self.source_intervals, TimeDomain.SOURCE_MEDIA),
            (self.normalized_audio_intervals, TimeDomain.NORMALIZED_CORPUS),
        ):
            if any(item.domain != domain for item in intervals):
                raise ValueError("rendered utterance interval has invalid domain")
        if len(self.simultaneous_with_utterance_ids) != len(
            set(self.simultaneous_with_utterance_ids)
        ):
            raise ValueError("simultaneous utterance references must be unique")
        if self.utterance_id in self.simultaneous_with_utterance_ids:
            raise ValueError("rendered utterance cannot be simultaneous with itself")
        if len(self.markers) != len(set(self.markers)):
            raise ValueError("rendered utterance markers must be unique")
        return self


class UtterancePresentationLoss(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    loss_id: str = Field(pattern=r"^utteranceviewloss_[a-f0-9]{32}$")
    kind: UtterancePresentationLossKind
    affected_utterance_ids: tuple[str, ...] = Field(min_length=1)
    explanation: str = Field(min_length=1)
    underlying_evidence_preserved: Literal[True] = True
    integrity_sha256: Sha256


class SpeakerAttributedTranscriptView(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    view_id: str = Field(pattern=r"^utteranceview_[a-f0-9]{32}$")
    bundle_id: str = Field(pattern=r"^utteranceviewbundle_[a-f0-9]{32}$")
    utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    kind: SpeakerAttributedViewKind
    policy: SpeakerAttributedTranscriptPolicy
    rendered_utterances: tuple[RenderedUtterance, ...]
    losses: tuple[UtterancePresentationLoss, ...] = ()
    rendered_text: str
    preserves_overlap_partial_order: bool
    order_basis: str = Field(min_length=1)
    generated_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def rendered_sequence_is_complete(self) -> "SpeakerAttributedTranscriptView":
        positions = [item.sequence_position for item in self.rendered_utterances]
        if positions != list(range(len(self.rendered_utterances))):
            raise ValueError("rendered utterance positions must be contiguous")
        identifiers = [item.utterance_id for item in self.rendered_utterances]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("view cannot duplicate utterances")
        expected = "\n".join(item.rendered_line for item in self.rendered_utterances)
        if self.rendered_text != expected:
            raise ValueError("rendered transcript text disagrees with records")
        return self


class SpeakerAttributedTranscriptBundle(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    bundle_id: str = Field(pattern=r"^utteranceviewbundle_[a-f0-9]{32}$")
    utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    utterance_run_id: str = Field(pattern=r"^utterancerun_[a-f0-9]{32}$")
    utterance_analysis_id: str = Field(
        pattern=r"^utteranceanalysis_[a-f0-9]{32}$"
    )
    utterance_relation_run_id: str = Field(
        pattern=r"^utterancerelations_[a-f0-9]{32}$"
    )
    turn_repair_run_id: str = Field(pattern=r"^turnrepairrun_[a-f0-9]{32}$")
    quotation_run_id: str = Field(pattern=r"^quotationrun_[a-f0-9]{32}$")
    configuration_hash: Sha256
    views: tuple[SpeakerAttributedTranscriptView, ...] = Field(min_length=6)
    generated_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def required_views_are_present(self) -> "SpeakerAttributedTranscriptBundle":
        kinds = [item.kind for item in self.views]
        if set(kinds) != set(SpeakerAttributedViewKind) or len(kinds) != 6:
            raise ValueError("bundle requires exactly all six transcript views")
        if any(item.bundle_id != self.bundle_id for item in self.views):
            raise ValueError("transcript view belongs to another bundle")
        return self


class SpeakerAttributedTranscriptReport(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    report_id: str = Field(pattern=r"^utteranceviewreport_[a-f0-9]{32}$")
    bundle_id: str = Field(pattern=r"^utteranceviewbundle_[a-f0-9]{32}$")
    utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    generated_at: datetime
    view_count: int = Field(ge=0)
    utterance_count_per_view: int = Field(ge=0)
    overlap_group_count: int = Field(ge=0)
    marked_interruption_count: int = Field(ge=0)
    marked_continuation_count: int = Field(ge=0)
    marked_quotation_count: int = Field(ge=0)
    marked_embedded_source_count: int = Field(ge=0)
    unknown_preserved_count: int = Field(ge=0)
    loss_record_count: int = Field(ge=0)
    limitations: tuple[str, ...] = ()
    status: Literal["complete", "warning", "failed"]
    integrity_sha256: Sha256


UTTERANCE_VIEW_CONTRACT_MODELS = (
    SpeakerAttributedTranscriptPolicy,
    RenderedUtterance,
    UtterancePresentationLoss,
    SpeakerAttributedTranscriptView,
    SpeakerAttributedTranscriptBundle,
    SpeakerAttributedTranscriptReport,
)
