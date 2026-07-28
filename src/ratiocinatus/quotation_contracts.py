"""Phase 4 spoken-quotation and embedded-speech contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .addressing_contracts import MediaInterval, TimeDomain
from .contracts import Contract, Sha256
from .phase2_contracts import ConfidenceMeasure
from .phase4_contracts import (
    PHASE4_FORMAT_VERSION,
    SpeechSourceType,
    UtteranceReviewStatus,
)

QUOTATION_POLICY_VERSION = "1.0.0"


class SpokenQuotationType(str, Enum):
    DIRECT = "direct_quotation"
    PARTIAL = "partial_quotation"
    PARAPHRASE = "paraphrase"
    ATTRIBUTED_PROPOSITION = "attributed_proposition"
    REPORTED_SPEECH = "reported_speech"
    READING_DOCUMENT = "reading_from_document"
    RECITATION = "recitation"
    IMITATION = "imitation_or_impersonation"
    HYPOTHETICAL = "hypothetical_speech"
    SELF_QUOTATION = "self_quotation"
    UNCERTAIN = "uncertain_quotation"


class QuotedSpeakerAttributionSource(str, Enum):
    EXPLICIT_UTTERANCE_WORDING = "explicit_utterance_wording"
    TRANSCRIPT_MARKER = "transcript_marker"
    EXTERNAL_SOURCE_MATCH = "external_source_match"
    REVIEWER = "reviewer"
    UNKNOWN = "unknown"


class EmbeddedSpeechKind(str, Enum):
    VIDEO_CLIP = "video_clip"
    ARCHIVAL_RECORDING = "archival_recording"
    ADVERTISEMENT = "advertisement"
    REMOTE_FEED = "remote_feed"
    VOICEMAIL = "voice_mail"
    TRANSLATED_PLAYBACK = "translated_playback"
    PUBLIC_ADDRESS = "public_address"
    SYNTHESIZED_VOICE = "synthesized_voice"
    REPLAYED_SPEECH = "replayed_speech"
    UNCERTAIN = "uncertain"


class QuotationDetectionPolicy(Contract):
    policy_version: Literal["1.0.0"] = QUOTATION_POLICY_VERSION
    attribution_cues: tuple[str, ...] = (
        "said",
        "says",
        "asked",
        "wrote",
        "reported",
        "i quote",
        "quote",
    )
    reported_speech_cues: tuple[str, ...] = (
        "said that",
        "says that",
        "reported that",
        "told us that",
    )
    embedded_source_markers: tuple[str, ...] = (
        "[video]",
        "[recording]",
        "[advertisement]",
        "[remote]",
        "[voicemail]",
        "[translated playback]",
        "[public address]",
        "[synthetic voice]",
        "[replay]",
    )
    quotation_marks_alone_sufficient: Literal[False] = False
    automatic_paraphrase_inference: Literal["prohibited"] = "prohibited"
    automatic_quoted_identity_binding: Literal["prohibited"] = "prohibited"
    acoustic_attribution_mutation: Literal["prohibited"] = "prohibited"

    @model_validator(mode="after")
    def cues_are_normalized_and_unique(self) -> "QuotationDetectionPolicy":
        for values in (
            self.attribution_cues,
            self.reported_speech_cues,
            self.embedded_source_markers,
        ):
            if any(not item or item != item.casefold() for item in values):
                raise ValueError("quotation policy cues must be casefolded")
            if len(values) != len(set(values)):
                raise ValueError("quotation policy cues must be unique")
        return self


class QuotedTextSpan(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    span_id: str = Field(pattern=r"^quotedspan_[a-f0-9]{32}$")
    utterance_id: str = Field(pattern=r"^utterance_[a-f0-9]{32}$")
    text_view_id: str = Field(pattern=r"^utterancetext_[a-f0-9]{32}$")
    character_start: int = Field(ge=0)
    character_end: int = Field(gt=0)
    quoted_text: str = Field(min_length=1)
    transcript_word_ids: tuple[str, ...] = ()
    source_intervals: tuple[MediaInterval, ...] = Field(min_length=1)
    normalized_audio_intervals: tuple[MediaInterval, ...] = Field(min_length=1)
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def span_addressing_is_valid(self) -> "QuotedTextSpan":
        if self.character_end <= self.character_start:
            raise ValueError("quoted span character range is empty")
        if len(self.transcript_word_ids) != len(set(self.transcript_word_ids)):
            raise ValueError("quoted word references must be unique")
        for intervals, domain in (
            (self.source_intervals, TimeDomain.SOURCE_MEDIA),
            (self.normalized_audio_intervals, TimeDomain.NORMALIZED_CORPUS),
        ):
            if any(item.domain != domain for item in intervals):
                raise ValueError("quoted span interval has invalid domain")
        return self


class SpokenQuotation(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    quotation_id: str = Field(pattern=r"^quotation_[a-f0-9]{32}$")
    utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    quoting_utterance_id: str = Field(pattern=r"^utterance_[a-f0-9]{32}$")
    quoted_span: QuotedTextSpan
    quotation_type: SpokenQuotationType
    acoustic_attribution_id: str = Field(
        pattern=r"^utteranceattr_[a-f0-9]{32}$"
    )
    acoustic_speaker_target_id: str | None = None
    quoted_speaker_target_id: str | None = None
    attribution_text: str | None = None
    attribution_source: QuotedSpeakerAttributionSource
    acoustically_present_only_through_current_speaker: bool
    external_source_match_exists: bool
    external_source_match_reference: str | None = None
    acoustic_attribution_preserved: Literal[True] = True
    evidence_references: tuple[str, ...] = Field(min_length=1)
    confidence: ConfidenceMeasure
    review_status: UtteranceReviewStatus
    policy_version: Literal["1.0.0"] = QUOTATION_POLICY_VERSION
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def quotation_attribution_is_explicit(self) -> "SpokenQuotation":
        if self.external_source_match_exists != (
            self.external_source_match_reference is not None
        ):
            raise ValueError("external quotation match reference is inconsistent")
        if (
            self.quotation_type == SpokenQuotationType.SELF_QUOTATION
            and self.quoted_speaker_target_id
            != self.acoustic_speaker_target_id
        ):
            raise ValueError("self-quotation target must match acoustic target")
        return self


class EmbeddedSpeechSource(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    embedded_source_id: str = Field(
        pattern=r"^embeddedspeech_[a-f0-9]{32}$"
    )
    utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    utterance_id: str = Field(pattern=r"^utterance_[a-f0-9]{32}$")
    acoustic_attribution_id: str = Field(
        pattern=r"^utteranceattr_[a-f0-9]{32}$"
    )
    acoustic_speaker_target_id: str | None = None
    source_type: SpeechSourceType
    kind: EmbeddedSpeechKind
    marker_text: str = Field(min_length=1)
    source_intervals: tuple[MediaInterval, ...] = Field(min_length=1)
    normalized_audio_intervals: tuple[MediaInterval, ...] = Field(min_length=1)
    embedded_speaker_target_id: str | None = None
    external_media_reference: str | None = None
    acoustic_attribution_preserved: Literal[True] = True
    evidence_references: tuple[str, ...] = Field(min_length=1)
    confidence: ConfidenceMeasure
    review_status: UtteranceReviewStatus
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def embedded_source_is_not_primary(self) -> "EmbeddedSpeechSource":
        if self.source_type == SpeechSourceType.PRIMARY_SOURCE_PARTICIPANT:
            raise ValueError("embedded speech cannot be primary participant speech")
        for intervals, domain in (
            (self.source_intervals, TimeDomain.SOURCE_MEDIA),
            (self.normalized_audio_intervals, TimeDomain.NORMALIZED_CORPUS),
        ):
            if any(item.domain != domain for item in intervals):
                raise ValueError("embedded speech interval has invalid domain")
        return self


class QuotationEvidenceRun(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    quotation_run_id: str = Field(pattern=r"^quotationrun_[a-f0-9]{32}$")
    utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    utterance_run_id: str = Field(pattern=r"^utterancerun_[a-f0-9]{32}$")
    phase2_transcript_assembly_id: str = Field(
        pattern=r"^txassembly_[a-f0-9]{32}$"
    )
    policy: QuotationDetectionPolicy
    configuration_hash: Sha256
    quotations: tuple[SpokenQuotation, ...]
    embedded_sources: tuple[EmbeddedSpeechSource, ...]
    created_at: datetime
    complete: bool
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def child_identifiers_are_unique(self) -> "QuotationEvidenceRun":
        for values in (
            tuple(item.quotation_id for item in self.quotations),
            tuple(item.embedded_source_id for item in self.embedded_sources),
        ):
            if len(values) != len(set(values)):
                raise ValueError("quotation evidence identifiers must be unique")
        return self


class QuotationEvidenceReport(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    report_id: str = Field(pattern=r"^quotationreport_[a-f0-9]{32}$")
    quotation_run_id: str = Field(pattern=r"^quotationrun_[a-f0-9]{32}$")
    utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    generated_at: datetime
    quotation_count: int = Field(ge=0)
    direct_count: int = Field(ge=0)
    reported_speech_count: int = Field(ge=0)
    self_quotation_count: int = Field(ge=0)
    embedded_source_count: int = Field(ge=0)
    remote_source_count: int = Field(ge=0)
    replayed_source_count: int = Field(ge=0)
    unresolved_count: int = Field(ge=0)
    review_required_count: int = Field(ge=0)
    limitations: tuple[str, ...] = ()
    status: Literal["complete", "warning", "failed"]
    integrity_sha256: Sha256


QUOTATION_CONTRACT_MODELS = (
    QuotationDetectionPolicy,
    QuotedTextSpan,
    SpokenQuotation,
    EmbeddedSpeechSource,
    QuotationEvidenceRun,
    QuotationEvidenceReport,
)
