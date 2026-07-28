"""Controlled temporal diarization evaluation contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .addressing_contracts import MediaInterval, TimeDomain
from .contracts import Contract, Sha256

DIARIZATION_EVALUATION_FORMAT_VERSION = "1.0.0"
DIARIZATION_EVALUATION_POLICY_VERSION = "1.0.0"


class ReferenceSpeechKind(str, Enum):
    PRIMARY_SPEECH = "primary_speech"
    UNKNOWN_SPEAKER = "unknown_speaker"
    NON_LEXICAL_VOCALIZATION = "non_lexical_vocalization"
    BACKGROUND_SPEECH = "background_speech"
    AUDIENCE_REACTION = "audience_reaction"
    REPLAYED_SPEECH = "replayed_speech"


class DiarizationScoringPolicy(Contract):
    policy_version: Literal["1.0.0"] = DIARIZATION_EVALUATION_POLICY_VERSION
    collar_microseconds: int = Field(default=250_000, ge=0)
    boundary_tolerance_microseconds: int = Field(default=500_000, ge=0)
    speaker_mapping: Literal["maximum_duration_one_to_one_v1"] = (
        "maximum_duration_one_to_one_v1"
    )
    maximum_mapping_speakers: int = Field(default=12, ge=1, le=20)
    overlap_scoring: Literal["include_in_der_and_score_duration"] = (
        "include_in_der_and_score_duration"
    )
    unknown_speaker_treatment: Literal["score_as_local_speaker"] = (
        "score_as_local_speaker"
    )
    non_lexical_vocalization_treatment: Literal["exclude"] = "exclude"
    audience_reaction_treatment: Literal["exclude"] = "exclude"
    background_speech_treatment: Literal["exclude"] = "exclude"
    replayed_speech_treatment: Literal["score_separately"] = "score_separately"
    reference_label_semantics: Literal["local_speakers_not_identities"] = (
        "local_speakers_not_identities"
    )


class TemporalReferenceTurn(Contract):
    reference_turn_id: str = Field(pattern=r"^diarefturn_[a-f0-9]{32}$")
    reference_speaker_key: str = Field(
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$"
    )
    normalized_audio_interval: MediaInterval
    speech_kind: ReferenceSpeechKind = ReferenceSpeechKind.PRIMARY_SPEECH
    strata: tuple[str, ...] = ()
    annotation_basis: str = Field(min_length=1)

    @model_validator(mode="after")
    def interval_and_strata_are_valid(self) -> "TemporalReferenceTurn":
        if self.normalized_audio_interval.domain != TimeDomain.NORMALIZED_CORPUS:
            raise ValueError("reference turns use normalized-corpus time")
        if len(self.strata) != len(set(self.strata)):
            raise ValueError("reference turn strata must be unique")
        return self


class TemporalReferenceBoundary(Contract):
    reference_boundary_id: str = Field(
        pattern=r"^diarefboundary_[a-f0-9]{32}$"
    )
    normalized_audio_microseconds: int = Field(ge=0)
    uncertainty_microseconds: int = Field(default=0, ge=0)
    preceding_speaker_keys: tuple[str, ...] = Field(min_length=1)
    following_speaker_keys: tuple[str, ...] = Field(min_length=1)
    strata: tuple[str, ...] = ()
    annotation_basis: str = Field(min_length=1)

    @model_validator(mode="after")
    def boundary_changes_active_speakers(
        self,
    ) -> "TemporalReferenceBoundary":
        if len(self.preceding_speaker_keys) != len(
            set(self.preceding_speaker_keys)
        ) or len(self.following_speaker_keys) != len(
            set(self.following_speaker_keys)
        ):
            raise ValueError("boundary speaker keys must be unique")
        if set(self.preceding_speaker_keys) == set(self.following_speaker_keys):
            raise ValueError("reference boundary must change active speakers")
        if len(self.strata) != len(set(self.strata)):
            raise ValueError("reference boundary strata must be unique")
        return self


class TemporalReferenceOverlap(Contract):
    reference_overlap_id: str = Field(
        pattern=r"^diarefoverlap_[a-f0-9]{32}$"
    )
    normalized_audio_interval: MediaInterval
    reference_speaker_keys: tuple[str, ...] = Field(min_length=2)
    strata: tuple[str, ...] = ()
    annotation_basis: str = Field(min_length=1)

    @model_validator(mode="after")
    def overlap_is_valid(self) -> "TemporalReferenceOverlap":
        if self.normalized_audio_interval.domain != TimeDomain.NORMALIZED_CORPUS:
            raise ValueError("reference overlap uses normalized-corpus time")
        if len(self.reference_speaker_keys) != len(
            set(self.reference_speaker_keys)
        ):
            raise ValueError("reference overlap speakers must be unique")
        if len(self.strata) != len(set(self.strata)):
            raise ValueError("reference overlap strata must be unique")
        return self


class TemporalDiarizationReference(Contract):
    format_version: Literal["1.0.0"] = DIARIZATION_EVALUATION_FORMAT_VERSION
    reference_id: str = Field(pattern=r"^diatempref_[a-f0-9]{32}$")
    corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    diarization_run_id: str = Field(pattern=r"^diarun_[a-f0-9]{32}$")
    source_artifact_sha256: Sha256
    normalized_audio_duration_microseconds: int = Field(gt=0)
    turns: tuple[TemporalReferenceTurn, ...] = Field(min_length=1)
    boundaries: tuple[TemporalReferenceBoundary, ...] = ()
    overlaps: tuple[TemporalReferenceOverlap, ...] = ()
    provenance: tuple[str, ...] = Field(min_length=1)
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def annotations_are_bounded_and_unique(
        self,
    ) -> "TemporalDiarizationReference":
        identifiers = (
            [item.reference_turn_id for item in self.turns]
            + [item.reference_boundary_id for item in self.boundaries]
            + [item.reference_overlap_id for item in self.overlaps]
        )
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("temporal reference identifiers must be unique")
        duration = self.normalized_audio_duration_microseconds
        if any(
            item.normalized_audio_interval.start_microseconds
            + item.normalized_audio_interval.duration_microseconds
            > duration
            for item in (*self.turns, *self.overlaps)
        ) or any(
            item.normalized_audio_microseconds > duration
            for item in self.boundaries
        ):
            raise ValueError("temporal reference annotation exceeds audio")
        ordered = tuple(
            item.normalized_audio_microseconds for item in self.boundaries
        )
        if ordered != tuple(sorted(ordered)) or len(ordered) != len(set(ordered)):
            raise ValueError("reference boundaries must be strictly ordered")
        for left in self.turns:
            for right in self.turns:
                if (
                    left.reference_turn_id < right.reference_turn_id
                    and left.reference_speaker_key == right.reference_speaker_key
                    and _overlap_duration(
                        left.normalized_audio_interval,
                        right.normalized_audio_interval,
                    )
                ):
                    raise ValueError(
                        "one reference speaker cannot overlap itself"
                    )
        return self


class DiarizationSpeakerMapping(Contract):
    system_speaker_key: str = Field(min_length=1)
    reference_speaker_key: str | None = None
    shared_duration_microseconds: int = Field(ge=0)


class DiarizationTemporalMetrics(Contract):
    scored_duration_microseconds: int = Field(gt=0)
    reference_speaker_time_microseconds: int = Field(gt=0)
    system_speaker_time_microseconds: int = Field(ge=0)
    correct_speaker_time_microseconds: int = Field(ge=0)
    missed_speech_microseconds: int = Field(ge=0)
    false_alarm_microseconds: int = Field(ge=0)
    speaker_confusion_microseconds: int = Field(ge=0)
    diarization_error_rate: float = Field(ge=0.0)
    missed_speech_rate: float = Field(ge=0.0)
    false_alarm_rate: float = Field(ge=0.0)
    speaker_confusion_rate: float = Field(ge=0.0)
    reference_boundary_count: int = Field(ge=0)
    system_boundary_count: int = Field(ge=0)
    matched_boundary_count: int = Field(ge=0)
    speaker_change_precision: float | None = Field(
        default=None, ge=0.0, le=1.0
    )
    speaker_change_recall: float | None = Field(
        default=None, ge=0.0, le=1.0
    )
    boundary_mean_absolute_error_microseconds: float | None = Field(
        default=None, ge=0.0
    )
    boundary_maximum_error_microseconds: int | None = Field(
        default=None, ge=0
    )
    reference_overlap_duration_microseconds: int = Field(ge=0)
    system_overlap_duration_microseconds: int = Field(ge=0)
    overlap_intersection_duration_microseconds: int = Field(ge=0)
    overlap_precision: float | None = Field(default=None, ge=0.0, le=1.0)
    overlap_recall: float | None = Field(default=None, ge=0.0, le=1.0)
    overlap_duration_error_microseconds: int = Field(ge=0)

    @model_validator(mode="after")
    def counts_and_rates_are_consistent(self) -> "DiarizationTemporalMetrics":
        if self.matched_boundary_count > min(
            self.reference_boundary_count, self.system_boundary_count
        ):
            raise ValueError("matched boundaries exceed available boundaries")
        if self.overlap_intersection_duration_microseconds > min(
            self.reference_overlap_duration_microseconds,
            self.system_overlap_duration_microseconds,
        ):
            raise ValueError("overlap intersection exceeds available duration")
        return self


class DiarizationStratumResult(Contract):
    stratum: str = Field(min_length=1)
    scored_window_microseconds: int = Field(gt=0)
    reference_speaker_time_microseconds: int = Field(gt=0)
    missed_speech_microseconds: int = Field(ge=0)
    false_alarm_microseconds: int = Field(ge=0)
    speaker_confusion_microseconds: int = Field(ge=0)
    diarization_error_rate: float = Field(ge=0.0)


class ControlledDiarizationEvaluation(Contract):
    format_version: Literal["1.0.0"] = DIARIZATION_EVALUATION_FORMAT_VERSION
    evaluation_id: str = Field(pattern=r"^diatempeval_[a-f0-9]{32}$")
    diarization_run_id: str = Field(pattern=r"^diarun_[a-f0-9]{32}$")
    provider_response_id: str = Field(pattern=r"^diaresponse_[a-f0-9]{32}$")
    corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    reference: TemporalDiarizationReference
    policy: DiarizationScoringPolicy
    speaker_mapping: tuple[DiarizationSpeakerMapping, ...]
    metrics: DiarizationTemporalMetrics
    strata: tuple[DiarizationStratumResult, ...]
    generated_at: datetime
    findings: tuple[str, ...]
    limitations: tuple[str, ...]
    status: Literal["complete", "warning", "blocked"]
    integrity_sha256: Sha256


class ControlledDiarizationEvaluationReport(Contract):
    format_version: Literal["1.0.0"] = DIARIZATION_EVALUATION_FORMAT_VERSION
    report_id: str = Field(pattern=r"^diatempreport_[a-f0-9]{32}$")
    evaluation_id: str = Field(pattern=r"^diatempeval_[a-f0-9]{32}$")
    diarization_run_id: str = Field(pattern=r"^diarun_[a-f0-9]{32}$")
    reference_id: str = Field(pattern=r"^diatempref_[a-f0-9]{32}$")
    generated_at: datetime
    diarization_error_rate: float = Field(ge=0.0)
    speaker_change_precision: float | None = Field(
        default=None, ge=0.0, le=1.0
    )
    speaker_change_recall: float | None = Field(
        default=None, ge=0.0, le=1.0
    )
    overlap_precision: float | None = Field(default=None, ge=0.0, le=1.0)
    overlap_recall: float | None = Field(default=None, ge=0.0, le=1.0)
    stratum_count: int = Field(ge=0)
    findings: tuple[str, ...]
    limitations: tuple[str, ...]
    status: Literal["complete", "warning", "blocked"]
    integrity_sha256: Sha256


def _overlap_duration(left: MediaInterval, right: MediaInterval) -> int:
    start = max(left.start_microseconds, right.start_microseconds)
    end = min(
        left.start_microseconds + left.duration_microseconds,
        right.start_microseconds + right.duration_microseconds,
    )
    return max(0, end - start)


DIARIZATION_EVALUATION_CONTRACT_MODELS = (
    DiarizationScoringPolicy,
    TemporalReferenceTurn,
    TemporalReferenceBoundary,
    TemporalReferenceOverlap,
    TemporalDiarizationReference,
    DiarizationSpeakerMapping,
    DiarizationTemporalMetrics,
    DiarizationStratumResult,
    ControlledDiarizationEvaluation,
    ControlledDiarizationEvaluationReport,
)
