"""Phase 2 speech-evidence contracts and conservative confidence semantics."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
import math
from typing import Literal

from pydantic import Field, model_validator

from .addressing_contracts import MediaInterval, TimeDomain
from .chunk_contracts import ProcessingChunk
from .contracts import Contract, Sha256
from .phase1_contracts import ToolInvocationRecord

PHASE2_FORMAT_VERSION = "1.0.0"
SPEECH_ACTIVITY_POLICY_VERSION = "1.0.0"
TRANSCRIPTION_POLICY_VERSION = "1.0.0"


class SpeechEvidenceCapability(str, Enum):
    SPEECH_ACTIVITY = "speech_activity"
    TRANSCRIPTION = "transcription"


class ConfidenceOrigin(str, Enum):
    PROVIDER_NATIVE = "provider_native"
    DERIVED = "derived"
    UNAVAILABLE = "unavailable"


class TimestampOrigin(str, Enum):
    PROVIDER_NATIVE = "provider_native"
    ESTIMATED = "estimated"
    EXTERNAL_ALIGNMENT = "external_alignment"
    UNAVAILABLE = "unavailable"


class SpeechActivityClassification(str, Enum):
    PROBABLE_SPEECH = "probable_speech"
    PROBABLE_NON_SPEECH = "probable_non_speech"
    UNCERTAIN = "uncertain"
    NON_LEXICAL_VOCALIZATION = "non_lexical_vocalization"
    INTERFERING_MUSIC_OR_NOISE = "interfering_music_or_noise"
    PROVIDER_FAILURE = "provider_failure"


class LanguageMode(str, Enum):
    EXPLICIT = "explicit"
    AUTOMATIC_PROPOSAL = "automatic_proposal"
    UNKNOWN = "unknown"


class WordTimestampPolicy(str, Enum):
    REQUEST_PROVIDER_NATIVE = "request_provider_native"
    SEGMENT_ONLY = "segment_only"


class RawEvidenceDisposition(str, Enum):
    RETAINED = "retained"
    HASH_ONLY = "hash_only"
    UNAVAILABLE = "unavailable"


class SpeechEvidenceFailureKind(str, Enum):
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    MODEL_UNAVAILABLE = "model_unavailable"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    MALFORMED_OUTPUT = "malformed_output"
    UNSUPPORTED_LANGUAGE = "unsupported_language"
    UNSUPPORTED_AUDIO = "unsupported_audio"
    VALIDATION_FAILURE = "validation_failure"
    INTERNAL_FAILURE = "internal_failure"


class ConfidenceMeasure(Contract):
    """A non-comparable confidence claim with explicit origin and basis."""

    value: float | None = Field(default=None, ge=0.0, le=1.0)
    origin: ConfidenceOrigin
    basis: str = Field(min_length=1)
    calibrated: bool = False
    calibration_id: str | None = None

    @model_validator(mode="after")
    def availability_is_explicit(self) -> "ConfidenceMeasure":
        if self.origin == ConfidenceOrigin.UNAVAILABLE and self.value is not None:
            raise ValueError("unavailable confidence cannot have a value")
        if self.origin != ConfidenceOrigin.UNAVAILABLE and self.value is None:
            raise ValueError("available confidence requires a value")
        if self.calibrated != (self.calibration_id is not None):
            raise ValueError(
                "calibrated confidence requires exactly one calibration identity"
            )
        return self


class SpeechEvidenceProviderIdentity(Contract):
    provider_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    display_name: str = Field(min_length=1)
    provider_version: str = Field(min_length=1)
    model_id: str | None = None
    model_version: str | None = None
    model_fingerprint: Sha256 | None = None
    runtime_fingerprint: Sha256 | None = None
    local: bool
    license_expression: str | None = None
    model_redistributed: bool = False


class SpeechEvidenceProviderCapabilities(Contract):
    format_version: Literal["1.0.0"] = PHASE2_FORMAT_VERSION
    identity: SpeechEvidenceProviderIdentity
    capabilities: tuple[SpeechEvidenceCapability, ...]
    available: bool
    supported_languages: tuple[str, ...] = ()
    automatic_language_proposal: bool = False
    segment_timestamps: bool = False
    word_timestamps: bool = False
    alternative_candidates: bool = False
    speech_confidence: bool = False
    text_confidence: bool = False
    timing_confidence: bool = False
    maximum_candidate_count: int = Field(default=1, ge=1, le=100)
    raw_response_retention: bool = False
    cancellation_boundaries: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def capability_claims_are_consistent(
        self,
    ) -> "SpeechEvidenceProviderCapabilities":
        if (
            SpeechEvidenceCapability.TRANSCRIPTION not in self.capabilities
            and (
                self.segment_timestamps
                or self.word_timestamps
                or self.alternative_candidates
                or self.text_confidence
                or self.timing_confidence
            )
        ):
            raise ValueError(
                "transcription features require transcription capability"
            )
        if (
            SpeechEvidenceCapability.SPEECH_ACTIVITY not in self.capabilities
            and self.speech_confidence
        ):
            raise ValueError(
                "speech confidence requires speech-activity capability"
            )
        if self.word_timestamps and not self.segment_timestamps:
            raise ValueError("word timestamps require segment timestamps")
        return self


class RawProviderEvidence(Contract):
    disposition: RawEvidenceDisposition
    media_type: str | None = None
    content_sha256: Sha256 | None = None
    byte_size: int | None = Field(default=None, ge=0)
    relative_path: str | None = None
    explanation: str

    @model_validator(mode="after")
    def retained_fields_are_consistent(self) -> "RawProviderEvidence":
        if self.disposition == RawEvidenceDisposition.RETAINED:
            if (
                self.content_sha256 is None
                or self.byte_size is None
                or self.relative_path is None
            ):
                raise ValueError("retained raw evidence requires hash, size, and path")
        elif self.disposition == RawEvidenceDisposition.HASH_ONLY:
            if self.content_sha256 is None or self.relative_path is not None:
                raise ValueError("hash-only evidence requires a hash and no path")
        elif any(
            value is not None
            for value in (
                self.content_sha256,
                self.byte_size,
                self.relative_path,
            )
        ):
            raise ValueError("unavailable raw evidence cannot claim stored content")
        return self


class SpeechActivityPolicy(Contract):
    policy_version: Literal["1.0.0"] = SPEECH_ACTIVITY_POLICY_VERSION
    speech_threshold: float = Field(default=0.65, ge=0.0, le=1.0)
    non_speech_threshold: float = Field(default=0.35, ge=0.0, le=1.0)
    minimum_speech_microseconds: int = Field(default=100_000, gt=0)
    minimum_silence_microseconds: int = Field(default=100_000, gt=0)
    boundary_uncertainty_microseconds: int = Field(default=20_000, ge=0)
    ownership_policy: Literal["inherit_phase1_earliest_chunk"] = (
        "inherit_phase1_earliest_chunk"
    )
    timeout_seconds: int = Field(default=120, ge=1, le=86_400)
    retain_raw_evidence: bool = True

    @model_validator(mode="after")
    def thresholds_leave_uncertain_band(self) -> "SpeechActivityPolicy":
        if self.non_speech_threshold >= self.speech_threshold:
            raise ValueError(
                "non-speech threshold must be below speech threshold"
            )
        return self


class TranscriptionPolicy(Contract):
    policy_version: Literal["1.0.0"] = TRANSCRIPTION_POLICY_VERSION
    language_mode: LanguageMode = LanguageMode.UNKNOWN
    language: str | None = None
    maximum_candidates: int = Field(default=1, ge=1, le=20)
    word_timestamps: WordTimestampPolicy = (
        WordTimestampPolicy.REQUEST_PROVIDER_NATIVE
    )
    maximum_segment_microseconds: int = Field(
        default=30_000_000, gt=0, le=600_000_000
    )
    merge_gap_microseconds: int = Field(default=300_000, ge=0, le=5_000_000)
    minimum_clip_microseconds: int = Field(default=200_000, gt=0, le=5_000_000)
    decoding_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    timeout_seconds: int = Field(default=300, ge=1, le=86_400)
    retain_raw_evidence: bool = True

    @model_validator(mode="after")
    def language_configuration_is_consistent(self) -> "TranscriptionPolicy":
        if self.language_mode == LanguageMode.EXPLICIT and not self.language:
            raise ValueError("explicit language mode requires a language")
        if self.language_mode != LanguageMode.EXPLICIT and self.language:
            raise ValueError(
                "only explicit language mode may prescribe a language"
            )
        return self


class SpeechActivityRequest(Contract):
    format_version: Literal["1.0.0"] = PHASE2_FORMAT_VERSION
    request_id: str = Field(pattern=r"^sareq_[a-f0-9]{32}$")
    requested_at: datetime
    corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    source_id: str = Field(pattern=r"^src_[a-f0-9]{32}$")
    normalized_audio_sha256: Sha256
    normalized_audio_duration_microseconds: int = Field(gt=0)
    audio_derivative_duration_microseconds: int = Field(gt=0)
    chunk_plan_id: str = Field(pattern=r"^chunkplan_[a-f0-9]{32}$")
    chunks: tuple[ProcessingChunk, ...]
    source_mapping_offset_microseconds: int
    policy: SpeechActivityPolicy
    provider: SpeechEvidenceProviderIdentity
    configuration_hash: Sha256


class TranscriptionRequest(Contract):
    format_version: Literal["1.0.0"] = PHASE2_FORMAT_VERSION
    request_id: str = Field(pattern=r"^txreq_[a-f0-9]{32}$")
    requested_at: datetime
    corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    source_id: str = Field(pattern=r"^src_[a-f0-9]{32}$")
    normalized_audio_sha256: Sha256
    normalized_audio_duration_microseconds: int = Field(gt=0)
    source_mapping_offset_microseconds: int
    speech_activity_run_id: str = Field(pattern=r"^sarun_[a-f0-9]{32}$")
    speech_interval_ids: tuple[str, ...]
    speech_intervals: tuple["SpeechActivityInterval", ...]
    policy: TranscriptionPolicy
    provider: SpeechEvidenceProviderIdentity
    configuration_hash: Sha256

    @model_validator(mode="after")
    def selected_intervals_are_embedded(self) -> "TranscriptionRequest":
        if not self.speech_interval_ids:
            raise ValueError("transcription request requires speech intervals")
        embedded = tuple(item.interval_id for item in self.speech_intervals)
        if embedded != self.speech_interval_ids:
            raise ValueError(
                "transcription interval identities and embedded evidence disagree"
            )
        if any(item.corpus_id != self.corpus_id for item in self.speech_intervals):
            raise ValueError("transcription interval belongs to another corpus")
        return self

class SpeechBoundaryEvidence(Contract):
    format_version: Literal["1.0.0"] = PHASE2_FORMAT_VERSION
    boundary_id: str = Field(pattern=r"^boundary_[a-f0-9]{32}$")
    normalized_audio_microseconds: int = Field(ge=0)
    source_microseconds: int
    uncertainty_microseconds: int = Field(ge=0)
    confidence: ConfidenceMeasure
    provider_reference: str | None = None


class SpeechActivityInterval(Contract):
    format_version: Literal["1.0.0"] = PHASE2_FORMAT_VERSION
    interval_id: str = Field(pattern=r"^speech_[a-f0-9]{32}$")
    corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    source_interval: MediaInterval
    normalized_audio_interval: MediaInterval
    processing_chunk_id: str = Field(pattern=r"^chunk_[a-f0-9]{32}$")
    classification: SpeechActivityClassification
    speech_presence_confidence: ConfidenceMeasure
    start_boundary_id: str = Field(pattern=r"^boundary_[a-f0-9]{32}$")
    end_boundary_id: str = Field(pattern=r"^boundary_[a-f0-9]{32}$")
    canonical_owner: bool = True
    provider_reference: str | None = None
    findings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def mapped_intervals_are_consistent(self) -> "SpeechActivityInterval":
        if self.source_interval.domain != TimeDomain.SOURCE_MEDIA:
            raise ValueError("speech source interval must use source-media time")
        if (
            self.normalized_audio_interval.domain
            != TimeDomain.NORMALIZED_CORPUS
        ):
            raise ValueError(
                "speech normalized interval must use normalized-corpus time"
            )
        if (
            self.source_interval.duration_microseconds
            != self.normalized_audio_interval.duration_microseconds
        ):
            raise ValueError("mapped speech interval durations must agree")
        return self


class SpeechActivityRun(Contract):
    format_version: Literal["1.0.0"] = PHASE2_FORMAT_VERSION
    run_id: str = Field(pattern=r"^sarun_[a-f0-9]{32}$")
    request: SpeechActivityRequest
    provider: SpeechEvidenceProviderIdentity
    started_at: datetime
    completed_at: datetime
    intervals: tuple[SpeechActivityInterval, ...]
    boundaries: tuple[SpeechBoundaryEvidence, ...]
    raw_evidence: RawProviderEvidence
    invocations: tuple[ToolInvocationRecord, ...] = ()
    failure: SpeechEvidenceFailureKind | None = None
    failure_message: str | None = None
    complete: bool

    @model_validator(mode="after")
    def result_and_lineage_are_consistent(self) -> "SpeechActivityRun":
        if self.completed_at < self.started_at:
            raise ValueError("speech activity run completes before it starts")
        if self.complete == (self.failure is not None):
            raise ValueError(
                "complete run requires no failure; failed run requires failure"
            )
        if self.complete and not self.intervals:
            raise ValueError(
                "complete speech activity run must represent the full timeline"
            )
        if any(
            item.corpus_id != self.request.corpus_id
            for item in self.intervals
        ):
            raise ValueError("speech interval belongs to a different corpus")
        ordered = sorted(
            self.intervals,
            key=lambda item: item.normalized_audio_interval.start_microseconds,
        )
        if tuple(ordered) != self.intervals:
            raise ValueError("speech activity intervals regress in time")
        if self.complete:
            if any(not item.canonical_owner for item in ordered):
                raise ValueError("canonical activity run contains non-owned output")
            cursor = 0
            chunks = {item.chunk_id: item for item in self.request.chunks}
            for item in ordered:
                normalized = item.normalized_audio_interval
                if normalized.start_microseconds != cursor:
                    raise ValueError(
                        "canonical activity intervals must be contiguous"
                    )
                cursor += normalized.duration_microseconds
                chunk = chunks.get(item.processing_chunk_id)
                if chunk is None:
                    raise ValueError("speech interval references an unknown chunk")
                ownership = chunk.ownership_interval
                if (
                    normalized.start_microseconds
                    < ownership.start_microseconds
                    or cursor
                    > ownership.start_microseconds
                    + ownership.duration_microseconds
                ):
                    raise ValueError("speech interval exceeds chunk ownership")
                if (
                    item.source_interval.start_microseconds
                    != normalized.start_microseconds
                    + self.request.source_mapping_offset_microseconds
                ):
                    raise ValueError("speech interval source mapping is invalid")
            if cursor != self.request.normalized_audio_duration_microseconds:
                raise ValueError("activity intervals do not cover normalized audio")
        boundary_ids = {item.boundary_id for item in self.boundaries}
        if any(
            item.start_boundary_id not in boundary_ids
            or item.end_boundary_id not in boundary_ids
            for item in self.intervals
        ):
            raise ValueError("speech interval references an unknown boundary")
        return self


class SpeechActivitySummary(Contract):
    classification: SpeechActivityClassification
    interval_count: int = Field(ge=0)
    duration_microseconds: int = Field(ge=0)


class SpeechActivityReport(Contract):
    format_version: Literal["1.0.0"] = PHASE2_FORMAT_VERSION
    report_id: str = Field(pattern=r"^speechreport_[a-f0-9]{32}$")
    run_id: str = Field(pattern=r"^sarun_[a-f0-9]{32}$")
    corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    generated_at: datetime
    provider: SpeechEvidenceProviderIdentity
    measured: tuple[SpeechActivitySummary, ...]
    configured_thresholds: tuple[tuple[str, float], ...]
    provider_claims: tuple[str, ...]
    inferred_classifications: tuple[str, ...]
    coverage_complete: bool
    duplicate_owned_interval_count: int = Field(ge=0)
    validation_findings: tuple[str, ...] = ()
    unresolved_limitations: tuple[str, ...] = ()
    status: Literal["complete", "partial", "warning", "failed"]

class SpeechActivityReference(Contract):
    """Independently prepared speech-presence intervals for evaluation."""

    format_version: Literal["1.0.0"] = PHASE2_FORMAT_VERSION
    reference_id: str = Field(pattern=r"^saref_[a-f0-9]{32}$")
    fixture_id: str = Field(min_length=1)
    variant: str = Field(min_length=1)
    normalized_audio_sha256: Sha256
    normalized_audio_duration_microseconds: int = Field(gt=0)
    schedule_sha256: Sha256
    intervals: tuple[MediaInterval, ...]
    provenance: str = Field(min_length=1)

    @model_validator(mode="after")
    def intervals_are_valid(self) -> "SpeechActivityReference":
        if not self.intervals:
            raise ValueError("speech activity reference requires intervals")
        previous_end = 0
        for interval in self.intervals:
            if interval.domain != TimeDomain.NORMALIZED_CORPUS:
                raise ValueError(
                    "reference intervals must use normalized-corpus time"
                )
            end = interval.start_microseconds + interval.duration_microseconds
            if interval.start_microseconds < previous_end:
                raise ValueError(
                    "reference intervals must be ordered and non-overlapping"
                )
            if end > self.normalized_audio_duration_microseconds:
                raise ValueError("reference interval exceeds source duration")
            previous_end = end
        return self


class SpeechActivityEvaluationMetrics(Contract):
    true_positive_microseconds: int = Field(ge=0)
    false_positive_microseconds: int = Field(ge=0)
    false_negative_microseconds: int = Field(ge=0)
    true_negative_microseconds: int = Field(ge=0)
    precision: float | None = Field(default=None, ge=0.0, le=1.0)
    recall: float | None = Field(default=None, ge=0.0, le=1.0)
    f1: float | None = Field(default=None, ge=0.0, le=1.0)
    mean_boundary_error_microseconds: float | None = Field(
        default=None, ge=0.0
    )
    median_boundary_error_microseconds: float | None = Field(
        default=None, ge=0.0
    )
    maximum_boundary_error_microseconds: int | None = Field(
        default=None, ge=0
    )
    predicted_speech_interval_count: int = Field(ge=0)
    reference_speech_interval_count: int = Field(ge=0)


class SpeechActivityEvaluationReport(Contract):
    format_version: Literal["1.0.0"] = PHASE2_FORMAT_VERSION
    evaluation_id: str = Field(pattern=r"^saeval_[a-f0-9]{32}$")
    generated_at: datetime
    run_id: str = Field(pattern=r"^sarun_[a-f0-9]{32}$")
    reference: SpeechActivityReference
    provider: SpeechEvidenceProviderIdentity
    metrics: SpeechActivityEvaluationMetrics
    positive_classification: Literal["probable_speech"] = "probable_speech"
    uncertain_treatment: Literal["evaluated_as_non_positive"] = (
        "evaluated_as_non_positive"
    )
    findings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def metrics_are_internally_consistent(
        self,
    ) -> "SpeechActivityEvaluationReport":
        metrics = self.metrics
        total = (
            metrics.true_positive_microseconds
            + metrics.false_positive_microseconds
            + metrics.false_negative_microseconds
            + metrics.true_negative_microseconds
        )
        if total != self.reference.normalized_audio_duration_microseconds:
            raise ValueError(
                "evaluation confusion durations must cover the reference"
            )
        precision_denominator = (
            metrics.true_positive_microseconds
            + metrics.false_positive_microseconds
        )
        recall_denominator = (
            metrics.true_positive_microseconds
            + metrics.false_negative_microseconds
        )
        expected_precision = (
            metrics.true_positive_microseconds / precision_denominator
            if precision_denominator
            else None
        )
        expected_recall = (
            metrics.true_positive_microseconds / recall_denominator
            if recall_denominator
            else None
        )
        expected_f1 = (
            2
            * expected_precision
            * expected_recall
            / (expected_precision + expected_recall)
            if expected_precision is not None
            and expected_recall is not None
            and expected_precision + expected_recall
            else None
        )
        for name, actual, expected in (
            ("precision", metrics.precision, expected_precision),
            ("recall", metrics.recall, expected_recall),
            ("f1", metrics.f1, expected_f1),
        ):
            if (actual is None) != (expected is None) or (
                actual is not None
                and expected is not None
                and not math.isclose(actual, expected, rel_tol=1e-12)
            ):
                raise ValueError(f"evaluation {name} disagrees with durations")
        return self


class ProviderWordObservation(Contract):
    """Provider-normalized word evidence; not yet a canonical transcript word."""

    provider_word_id: str = Field(min_length=1)
    surface_text: str = Field(min_length=1)
    sequence_position: int = Field(ge=0)
    source_interval: MediaInterval | None = None
    normalized_audio_interval: MediaInterval | None = None
    timestamp_origin: TimestampOrigin
    recognition_confidence: ConfidenceMeasure
    timing_confidence: ConfidenceMeasure
    provider_token_reference: str | None = None
    boundary_uncertainty_microseconds: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def timestamp_availability_is_consistent(self) -> "ProviderWordObservation":
        unavailable = self.timestamp_origin == TimestampOrigin.UNAVAILABLE
        if unavailable and (
            self.normalized_audio_interval is not None or self.source_interval is not None
        ):
            raise ValueError("unavailable word timestamp cannot have intervals")
        if not unavailable and (
            self.normalized_audio_interval is None or self.source_interval is None
        ):
            raise ValueError("available word timestamp requires mapped intervals")
        if self.normalized_audio_interval is not None:
            if self.normalized_audio_interval.domain != TimeDomain.NORMALIZED_CORPUS:
                raise ValueError("provider word interval uses wrong domain")
            if self.source_interval.domain != TimeDomain.SOURCE_MEDIA:
                raise ValueError("provider word source interval uses wrong domain")
            if self.source_interval.duration_microseconds != self.normalized_audio_interval.duration_microseconds:
                raise ValueError("provider word mapped durations disagree")
        return self


class ProviderTranscriptCandidate(Contract):
    provider_candidate_id: str = Field(min_length=1)
    proposed_text: str
    language: str | None = None
    rank: int | None = Field(default=None, ge=1)
    provider_score: float | None = None
    text_confidence: ConfidenceMeasure
    selected: bool
    comparison_basis: str = Field(default="single_provider_candidate", min_length=1)
    selection_reason: str | None = None
    words: tuple[ProviderWordObservation, ...] = ()

    @model_validator(mode="after")
    def selection_and_words_are_consistent(self) -> "ProviderTranscriptCandidate":
        if self.selected and not self.selection_reason:
            raise ValueError("selected transcript candidate requires a reason")
        positions = tuple(item.sequence_position for item in self.words)
        if positions != tuple(range(len(self.words))):
            raise ValueError("provider word positions must be contiguous")
        return self


class ProviderTranscriptObservation(Contract):
    observation_id: str = Field(pattern=r"^txobs_[a-f0-9]{32}$")
    speech_interval_ids: tuple[str, ...] = Field(min_length=1)
    source_interval: MediaInterval
    normalized_audio_interval: MediaInterval
    processing_chunk_ids: tuple[str, ...] = Field(min_length=1)
    provider_segment_reference: str | None = None
    candidates: tuple[ProviderTranscriptCandidate, ...]
    selected_candidate_id: str | None = None
    timing_confidence: ConfidenceMeasure
    boundary_confidence: ConfidenceMeasure
    findings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def selection_is_explicit(self) -> "ProviderTranscriptObservation":
        if self.normalized_audio_interval.domain != TimeDomain.NORMALIZED_CORPUS:
            raise ValueError("transcript observation must use normalized-corpus time")
        if self.source_interval.domain != TimeDomain.SOURCE_MEDIA:
            raise ValueError("transcript observation must use source-media time")
        if self.source_interval.duration_microseconds != self.normalized_audio_interval.duration_microseconds:
            raise ValueError("transcript observation mapped durations disagree")
        if len(self.speech_interval_ids) != len(set(self.speech_interval_ids)):
            raise ValueError("speech evidence references must be unique")
        if len(self.processing_chunk_ids) != len(set(self.processing_chunk_ids)):
            raise ValueError("processing chunk references must be unique")
        identifiers = [item.provider_candidate_id for item in self.candidates]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("provider candidate identifiers must be unique")
        selected = [item.provider_candidate_id for item in self.candidates if item.selected]
        if self.selected_candidate_id is None and selected:
            raise ValueError("unresolved observation cannot select a candidate")
        if self.selected_candidate_id is not None and (
            selected != [self.selected_candidate_id]
            or self.selected_candidate_id not in identifiers
        ):
            raise ValueError("selected candidate identity and marker must agree")
        start = self.normalized_audio_interval.start_microseconds
        limit = start + self.normalized_audio_interval.duration_microseconds
        for candidate in self.candidates:
            previous_end = start
            for word in candidate.words:
                if word.normalized_audio_interval is None:
                    continue
                word_start = word.normalized_audio_interval.start_microseconds
                word_end = word_start + word.normalized_audio_interval.duration_microseconds
                if word_start < previous_end or word_end > limit:
                    raise ValueError("provider words must be ordered within observation")
                previous_end = word_end
        return self


class TranscriptionProviderResponse(Contract):
    format_version: Literal["1.0.0"] = PHASE2_FORMAT_VERSION
    response_id: str = Field(pattern=r"^txresponse_[a-f0-9]{32}$")
    request_id: str = Field(pattern=r"^txreq_[a-f0-9]{32}$")
    provider: SpeechEvidenceProviderIdentity
    started_at: datetime
    completed_at: datetime
    observations: tuple[ProviderTranscriptObservation, ...]
    normalized_evidence_sha256: Sha256
    raw_evidence: RawProviderEvidence
    invocations: tuple[ToolInvocationRecord, ...] = ()
    failure: SpeechEvidenceFailureKind | None = None
    failure_message: str | None = None
    complete: bool

    @model_validator(mode="after")
    def response_state_is_consistent(self) -> "TranscriptionProviderResponse":
        if self.completed_at < self.started_at:
            raise ValueError("transcription response completes before it starts")
        if self.complete == (self.failure is not None):
            raise ValueError("complete response requires no failure; failed response requires failure")
        identifiers = tuple(item.observation_id for item in self.observations)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("transcript observation identifiers must be unique")
        starts = tuple(item.normalized_audio_interval.start_microseconds for item in self.observations)
        if starts != tuple(sorted(starts)):
            raise ValueError("transcript observations regress in time")
        return self


class TranscriptionReport(Contract):
    format_version: Literal["1.0.0"] = PHASE2_FORMAT_VERSION
    report_id: str = Field(pattern=r"^txreport_[a-f0-9]{32}$")
    response_id: str = Field(pattern=r"^txresponse_[a-f0-9]{32}$")
    request_id: str = Field(pattern=r"^txreq_[a-f0-9]{32}$")
    corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    generated_at: datetime
    provider: SpeechEvidenceProviderIdentity
    observation_count: int = Field(ge=0)
    selected_candidate_count: int = Field(ge=0)
    unresolved_observation_count: int = Field(ge=0)
    word_observation_count: int = Field(ge=0)
    languages: tuple[str, ...] = ()
    configured_policy: TranscriptionPolicy
    measured: tuple[str, ...] = ()
    provider_claims: tuple[str, ...] = ()
    inferred_classifications: tuple[str, ...] = ()
    validation_findings: tuple[str, ...] = ()
    unresolved_limitations: tuple[str, ...] = ()
    status: Literal["complete", "partial", "warning", "failed"]

PHASE2_CONTRACT_MODELS = (
    ConfidenceMeasure,
    SpeechEvidenceProviderIdentity,
    SpeechEvidenceProviderCapabilities,
    RawProviderEvidence,
    SpeechActivityPolicy,
    TranscriptionPolicy,
    SpeechActivityRequest,
    TranscriptionRequest,
    SpeechBoundaryEvidence,
    SpeechActivityInterval,
    SpeechActivityRun,
    SpeechActivitySummary,
    SpeechActivityReport,
    SpeechActivityReference,
    SpeechActivityEvaluationMetrics,
    SpeechActivityEvaluationReport,
    ProviderWordObservation,
    ProviderTranscriptCandidate,
    ProviderTranscriptObservation,
    TranscriptionProviderResponse,
    TranscriptionReport,
)
