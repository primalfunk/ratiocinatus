"""Strict controlled-reference and transcript-evaluation contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .addressing_contracts import MediaInterval, TimeDomain
from .contracts import Contract, Sha256
from .correction_contracts import TranscriptViewKind

TRANSCRIPT_EVALUATION_FORMAT_VERSION = "1.0.0"
TRANSCRIPT_EVALUATION_POLICY_VERSION = "1.0.0"


class EvaluationStratum(str, Enum):
    CLEAN_SPEECH = "clean_speech"
    NOISE = "noise"
    MUSIC = "music"
    OVERLAPPING_SPEECH = "overlapping_speech"
    RAPID_SPEECH = "rapid_speech"
    QUIET_SPEECH = "quiet_speech"
    CLIPPED_BOUNDARY = "clipped_boundary"
    ACCENTED_SPEECH = "accented_speech"
    NON_SPEECH_VOCALIZATION = "non_speech_vocalization"
    LONG_RECORDING_CHUNK_BOUNDARY = "long_recording_chunk_boundary"
    OTHER_CONTROLLED = "other_controlled"


class EvaluationAvailability(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE_REFERENCE = "unavailable_reference"
    UNAVAILABLE_HYPOTHESIS = "unavailable_hypothesis"
    NOT_REQUESTED = "not_requested"


class TranscriptEvaluationPolicy(Contract):
    policy_version: Literal["1.0.0"] = TRANSCRIPT_EVALUATION_POLICY_VERSION
    text_normalization: Literal[
        "unicode_nfkc_casefold_alphanumeric_apostrophe_v1"
    ] = "unicode_nfkc_casefold_alphanumeric_apostrophe_v1"
    word_error_unit: Literal["normalized_word"] = "normalized_word"
    character_error_unit: Literal[
        "space_joined_normalized_words"
    ] = "space_joined_normalized_words"
    timing_match_policy: Literal[
        "maximum_interval_overlap_then_nearest_midpoint"
    ] = "maximum_interval_overlap_then_nearest_midpoint"
    confidence_bin_edges: tuple[float, ...] = (
        0.0,
        0.2,
        0.4,
        0.6,
        0.8,
        1.0,
    )

    @model_validator(mode="after")
    def bins_are_valid(self) -> "TranscriptEvaluationPolicy":
        if (
            self.confidence_bin_edges[0] != 0.0
            or self.confidence_bin_edges[-1] != 1.0
            or len(self.confidence_bin_edges) < 2
            or tuple(sorted(set(self.confidence_bin_edges)))
            != self.confidence_bin_edges
        ):
            raise ValueError(
                "confidence bin edges must uniquely increase from zero to one"
            )
        return self


class ReferenceWord(Contract):
    reference_word_id: str = Field(min_length=1)
    surface_text: str = Field(min_length=1)
    normalized_audio_interval: MediaInterval | None = None
    source_interval: MediaInterval | None = None

    @model_validator(mode="after")
    def timing_is_paired(self) -> "ReferenceWord":
        if (self.source_interval is None) != (
            self.normalized_audio_interval is None
        ):
            raise ValueError("reference word timing must provide both domains")
        if self.source_interval is not None:
            if self.source_interval.domain != TimeDomain.SOURCE_MEDIA:
                raise ValueError("reference word source domain is invalid")
            if (
                self.normalized_audio_interval is None
                or self.normalized_audio_interval.domain
                != TimeDomain.NORMALIZED_CORPUS
                or self.source_interval.duration_microseconds
                != self.normalized_audio_interval.duration_microseconds
            ):
                raise ValueError("reference word mapping is invalid")
        return self


class ReferenceTranscriptSegment(Contract):
    reference_segment_id: str = Field(min_length=1)
    source_interval: MediaInterval
    normalized_audio_interval: MediaInterval
    text: str = Field(min_length=1)
    strata: tuple[EvaluationStratum, ...] = Field(min_length=1)
    words: tuple[ReferenceWord, ...] = ()
    expected_candidate_id: str | None = None

    @model_validator(mode="after")
    def mapping_is_valid(self) -> "ReferenceTranscriptSegment":
        if self.source_interval.domain != TimeDomain.SOURCE_MEDIA:
            raise ValueError("reference segment source domain is invalid")
        if (
            self.normalized_audio_interval.domain
            != TimeDomain.NORMALIZED_CORPUS
        ):
            raise ValueError("reference segment normalized domain is invalid")
        if (
            self.source_interval.duration_microseconds
            != self.normalized_audio_interval.duration_microseconds
        ):
            raise ValueError("reference segment mapped durations disagree")
        if len(self.strata) != len(set(self.strata)):
            raise ValueError("reference segment strata must be unique")
        return self


class ReferenceTranscript(Contract):
    format_version: Literal["1.0.0"] = (
        TRANSCRIPT_EVALUATION_FORMAT_VERSION
    )
    reference_id: str = Field(pattern=r"^txreference_[a-f0-9]{32}$")
    fixture_id: str = Field(min_length=1)
    variant: str = Field(min_length=1)
    corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    source_id: str = Field(pattern=r"^src_[a-f0-9]{32}$")
    source_sha256: Sha256
    normalized_audio_sha256: Sha256
    normalized_audio_duration_microseconds: int = Field(gt=0)
    source_mapping_offset_microseconds: int
    source_document_sha256: Sha256
    schedule_document_sha256: Sha256
    provenance: str = Field(min_length=1)
    independence_statement: str = Field(min_length=1)
    segments: tuple[ReferenceTranscriptSegment, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def segments_are_addressable(self) -> "ReferenceTranscript":
        previous_start = -1
        for segment in self.segments:
            start = segment.normalized_audio_interval.start_microseconds
            end = start + segment.normalized_audio_interval.duration_microseconds
            if start < previous_start:
                raise ValueError("reference segments must not regress")
            if end > self.normalized_audio_duration_microseconds:
                raise ValueError("reference segment exceeds audio duration")
            if (
                segment.source_interval.start_microseconds
                != start + self.source_mapping_offset_microseconds
            ):
                raise ValueError("reference segment source mapping disagrees")
            previous_start = start
        return self


class EditMetrics(Contract):
    reference_word_count: int = Field(ge=0)
    hypothesis_word_count: int = Field(ge=0)
    word_substitution_count: int = Field(ge=0)
    word_deletion_count: int = Field(ge=0)
    word_insertion_count: int = Field(ge=0)
    word_error_rate: float | None = Field(default=None, ge=0.0)
    reference_character_count: int = Field(ge=0)
    hypothesis_character_count: int = Field(ge=0)
    character_edit_count: int = Field(ge=0)
    character_error_rate: float | None = Field(default=None, ge=0.0)

    @model_validator(mode="after")
    def rates_match_counts(self) -> "EditMetrics":
        word_edits = (
            self.word_substitution_count
            + self.word_deletion_count
            + self.word_insertion_count
        )
        expected_wer = (
            word_edits / self.reference_word_count
            if self.reference_word_count
            else None
        )
        expected_cer = (
            self.character_edit_count / self.reference_character_count
            if self.reference_character_count
            else None
        )
        for actual, expected, name in (
            (self.word_error_rate, expected_wer, "WER"),
            (self.character_error_rate, expected_cer, "CER"),
        ):
            if (actual is None) != (expected is None) or (
                actual is not None
                and expected is not None
                and abs(actual - expected) > 1e-12
            ):
                raise ValueError(f"{name} disagrees with edit counts")
        return self


class TimingErrorMetrics(Contract):
    availability: EvaluationAvailability
    evaluated_item_count: int = Field(ge=0)
    unmatched_reference_count: int = Field(ge=0)
    mean_start_error_microseconds: float | None = Field(default=None, ge=0.0)
    median_start_error_microseconds: float | None = Field(default=None, ge=0.0)
    maximum_start_error_microseconds: int | None = Field(default=None, ge=0)
    mean_end_error_microseconds: float | None = Field(default=None, ge=0.0)
    median_end_error_microseconds: float | None = Field(default=None, ge=0.0)
    maximum_end_error_microseconds: int | None = Field(default=None, ge=0)
    unavailable_reason: str | None = None

    @model_validator(mode="after")
    def availability_matches_values(self) -> "TimingErrorMetrics":
        values = (
            self.mean_start_error_microseconds,
            self.median_start_error_microseconds,
            self.maximum_start_error_microseconds,
            self.mean_end_error_microseconds,
            self.median_end_error_microseconds,
            self.maximum_end_error_microseconds,
        )
        if self.availability == EvaluationAvailability.AVAILABLE:
            if not self.evaluated_item_count or any(v is None for v in values):
                raise ValueError("available timing metrics require values")
            if self.unavailable_reason is not None:
                raise ValueError("available timing metrics cannot give a reason")
        elif any(v is not None for v in values) or not self.unavailable_reason:
            raise ValueError("unavailable timing metrics require only a reason")
        return self


class ConfidenceReliabilityBin(Contract):
    lower_inclusive: float = Field(ge=0.0, le=1.0)
    upper_inclusive: float = Field(gt=0.0, le=1.0)
    item_count: int = Field(gt=0)
    mean_claimed_confidence: float = Field(ge=0.0, le=1.0)
    mean_observed_word_accuracy: float = Field(ge=0.0, le=1.0)
    absolute_reliability_gap: float = Field(ge=0.0, le=1.0)


class ConfidenceReliabilityAnalysis(Contract):
    availability: EvaluationAvailability
    confidence_origin: str
    bins: tuple[ConfidenceReliabilityBin, ...] = ()
    excluded_unavailable_count: int = Field(ge=0)
    method: str = Field(min_length=1)
    unavailable_reason: str | None = None


class CandidateSelectionMetrics(Contract):
    availability: EvaluationAvailability
    evaluated_segment_count: int = Field(ge=0)
    correct_selection_count: int = Field(ge=0)
    accuracy: float | None = Field(default=None, ge=0.0, le=1.0)
    unavailable_reason: str | None = None

    @model_validator(mode="after")
    def availability_is_consistent(self) -> "CandidateSelectionMetrics":
        if self.availability == EvaluationAvailability.AVAILABLE:
            if not self.evaluated_segment_count or self.accuracy is None:
                raise ValueError("available candidate metrics require results")
            if self.correct_selection_count > self.evaluated_segment_count:
                raise ValueError("candidate correct count exceeds evaluated")
            expected = self.correct_selection_count / self.evaluated_segment_count
            if abs(self.accuracy - expected) > 1e-12:
                raise ValueError("candidate accuracy disagrees with counts")
            if self.unavailable_reason is not None:
                raise ValueError("available candidate metrics cannot give a reason")
        elif (
            self.evaluated_segment_count
            or self.correct_selection_count
            or self.accuracy is not None
            or not self.unavailable_reason
        ):
            raise ValueError("unavailable candidate metrics require only a reason")
        return self


class SubtitleCueEvaluation(Contract):
    availability: EvaluationAvailability
    export_id: str | None = Field(
        default=None, pattern=r"^subtitleexport_[a-f0-9]{32}$"
    )
    cue_count: int = Field(ge=0)
    valid: bool | None = None
    unavailable_reason: str | None = None

    @model_validator(mode="after")
    def availability_is_consistent(self) -> "SubtitleCueEvaluation":
        if self.availability == EvaluationAvailability.AVAILABLE:
            if self.export_id is None or self.valid is None:
                raise ValueError("available subtitle metrics require an export")
            if self.unavailable_reason is not None:
                raise ValueError("available subtitle metrics cannot give a reason")
        elif (
            self.export_id is not None
            or self.cue_count
            or self.valid is not None
            or not self.unavailable_reason
        ):
            raise ValueError("unavailable subtitle metrics require only a reason")
        return self


class CorrectionImpact(Contract):
    availability: EvaluationAvailability
    base_version_id: str
    corrected_version_id: str | None = None
    original: EditMetrics | None = None
    corrected: EditMetrics | None = None
    word_error_rate_change: float | None = None
    character_error_rate_change: float | None = None
    correction_count: int = Field(ge=0)
    unavailable_reason: str | None = None


class StratumEvaluation(Contract):
    stratum: EvaluationStratum
    reference_segment_count: int = Field(gt=0)
    metrics: EditMetrics
    segment_timing: TimingErrorMetrics


class TranscriptEvaluationReport(Contract):
    format_version: Literal["1.0.0"] = (
        TRANSCRIPT_EVALUATION_FORMAT_VERSION
    )
    evaluation_id: str = Field(pattern=r"^txevaluation_[a-f0-9]{32}$")
    base_assembly_id: str = Field(pattern=r"^txassembly_[a-f0-9]{32}$")
    revision_id: str | None = Field(
        default=None, pattern=r"^txrevision_[a-f0-9]{32}$"
    )
    transcript_version_id: str = Field(pattern=r"^txversion_[a-f0-9]{32}$")
    view_kind: TranscriptViewKind
    reference: ReferenceTranscript
    policy: TranscriptEvaluationPolicy
    generated_at: datetime
    aggregate: EditMetrics
    strata: tuple[StratumEvaluation, ...]
    segment_timing: TimingErrorMetrics
    word_timing: TimingErrorMetrics
    confidence_reliability: ConfidenceReliabilityAnalysis
    candidate_selection: CandidateSelectionMetrics
    subtitle_cues: SubtitleCueEvaluation
    correction_impact: CorrectionImpact
    reviewed_reference_segment_count: int = Field(ge=0)
    findings: tuple[str, ...]
    status: Literal["complete", "warning"]
    integrity_sha256: Sha256


EVALUATION_CONTRACT_MODELS = (
    TranscriptEvaluationPolicy,
    ReferenceWord,
    ReferenceTranscriptSegment,
    ReferenceTranscript,
    EditMetrics,
    TimingErrorMetrics,
    ConfidenceReliabilityBin,
    ConfidenceReliabilityAnalysis,
    CandidateSelectionMetrics,
    SubtitleCueEvaluation,
    CorrectionImpact,
    StratumEvaluation,
    TranscriptEvaluationReport,
)
