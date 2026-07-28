"""Phase 4 speaker-attributed utterance corpus evidence boundaries."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .addressing_contracts import MediaInterval, TimeDomain
from .contracts import Contract, Severity, Sha256
from .phase2_contracts import ConfidenceMeasure

PHASE4_FORMAT_VERSION = "1.0.0"
UTTERANCE_SEGMENTATION_POLICY_VERSION = "1.0.0"
UTTERANCE_NORMALIZATION_POLICY_VERSION = "1.0.0"
UTTERANCE_ANALYSIS_POLICY_VERSION = "1.0.0"


class UtteranceTextKind(str, Enum):
    RAW_MACHINE_TRANSCRIPT = "raw_machine_transcript"
    CURRENT_CORRECTED_TRANSCRIPT = "current_corrected_transcript"
    DISPLAY = "display"
    MINIMALLY_NORMALIZED_ANALYSIS = "minimally_normalized_analysis"
    REVIEW_MARKUP = "review_markup"


class UtteranceAttributionStatus(str, Enum):
    MACHINE_CLUSTERED = "machine_clustered"
    IDENTITY_HYPOTHESIZED = "identity_hypothesized"
    MANUALLY_BOUND = "manually_bound"
    ROLE_LABELED = "role_labeled"
    CONFLICTING = "conflicting"
    UNKNOWN = "unknown"


class UtteranceAttributionTargetKind(str, Enum):
    SPEAKER_CLUSTER = "speaker_cluster"
    PARTICIPANT_IDENTITY = "participant_identity"
    ROLE = "role"
    MULTIPLE_CANDIDATES = "multiple_candidates"
    UNKNOWN = "unknown"


class UtteranceCompletenessClassification(str, Enum):
    COMPLETE = "complete"
    GRAMMATICALLY_INCOMPLETE_DISCOURSE_COMPLETE = (
        "grammatically_incomplete_discourse_complete"
    )
    INTERRUPTED = "interrupted"
    ABANDONED = "abandoned"
    TRAILING_OFF = "trailing_off"
    CLIPPED_BY_SOURCE_BOUNDARY = "clipped_by_source_boundary"
    CLIPPED_BY_PROCESSING_BOUNDARY = "clipped_by_processing_boundary"
    TRANSCRIPTION_INCOMPLETE = "transcription_incomplete"
    INAUDIBLE_ENDING = "inaudible_ending"
    RESUMED_LATER = "resumed_later"
    FRAGMENT = "fragment"
    NON_LEXICAL = "non_lexical"
    UNKNOWN = "unknown"


class UtteranceInterruptionStatus(str, Enum):
    NONE = "none"
    INTERRUPTED = "interrupted"
    INTERRUPTING = "interrupting"
    BOTH = "both"
    UNCERTAIN = "uncertain"


class UtteranceRepairStatus(str, Enum):
    NONE = "none"
    CANDIDATE = "candidate"
    REVIEWED = "reviewed"
    ACCEPTED_SUCCESSOR = "accepted_successor"
    UNRESOLVED = "unresolved"


class UtteranceOverlapStatus(str, Enum):
    NONE = "none"
    PRESERVED = "preserved"
    MIXED_TRANSCRIPT = "mixed_transcript"
    UNCERTAIN_WORD_ATTRIBUTION = "uncertain_word_attribution"
    UNTRANSCRIBED_OVERLAP = "untranscribed_overlap"


class UtteranceQuotationStatus(str, Enum):
    NONE = "none"
    CANDIDATE = "candidate"
    REVIEWED = "reviewed"
    UNCERTAIN = "uncertain"


class UtteranceReviewStatus(str, Enum):
    UNREVIEWED = "unreviewed"
    REVIEW_REQUIRED = "review_required"
    APPROVED = "approved"
    REVISED = "revised"
    DEFERRED = "deferred"
    CONFLICTED = "conflicted"


class UtteranceCreationProcess(str, Enum):
    DETERMINISTIC_SEGMENTATION = "deterministic_segmentation"
    RULE_ASSISTED_PROPOSAL = "rule_assisted_proposal"
    MODEL_ASSISTED_PROPOSAL = "model_assisted_proposal"
    MANUAL_SUCCESSOR = "manual_successor"
    CORRECTION_PROPAGATION = "correction_propagation"
    IMPORTED_REVIEW = "imported_review"


class SpeechSourceType(str, Enum):
    PRIMARY_SOURCE_PARTICIPANT = "primary_source_participant"
    EMBEDDED_MEDIA = "embedded_media"
    REMOTE_PARTICIPANT = "remote_participant"
    SYNTHESIZED = "synthesized"
    REPLAYED = "replayed"
    UNCERTAIN = "uncertain"


class DisfluencyKind(str, Enum):
    FALSE_START = "false_start"
    RESTART = "restart"
    REPETITION = "repetition"
    SUBSTITUTION = "substitution"
    INSERTION = "insertion"
    ABANDONMENT = "deletion_like_abandonment"
    HESITATION = "hesitation"
    FILLER = "filler"
    STUTTER_LIKE_REPETITION = "stutter_like_repetition"
    EXPLICIT_CORRECTION = "explicit_correction"


class SelfRepairKind(str, Enum):
    RESTART = "restart"
    SUBSTITUTION = "substitution"
    INSERTION = "insertion"
    ABANDONMENT = "deletion_like_abandonment"
    EXPLICIT_CORRECTION = "explicit_correction"
    UNCERTAIN = "uncertain"


class UtteranceSegmentationPolicy(Contract):
    policy_version: Literal["1.0.0"] = UTTERANCE_SEGMENTATION_POLICY_VERSION
    maximum_gap_microseconds: int = Field(default=750_000, ge=0)
    minimum_utterance_duration_microseconds: int = Field(default=1, gt=0)
    maximum_utterance_duration_microseconds: int = Field(
        default=45_000_000, gt=0
    )
    speaker_change_is_hard_boundary: bool = True
    confirmed_overlap_prohibits_merge: bool = True
    incompatible_attribution_prohibits_merge: bool = True
    source_discontinuity_prohibits_merge: bool = True
    punctuation_is_soft_indicator: bool = True
    syntactic_completion_is_soft_indicator: bool = True
    discourse_markers_are_soft_indicators: bool = True
    semantic_continuity_enabled: bool = False
    fillers_attach_to_neighboring_speech: bool = True
    non_lexical_vocalizations_standalone: bool = True
    uncertain_speaker_change_requires_review: bool = True
    cross_chunk_continuity_enabled: bool = True
    non_contiguous_continuation_enabled: bool = False
    interruption_requires_temporal_evidence: bool = True
    moderator_intervention_is_soft_boundary: bool = True
    configuration_notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def duration_bounds_are_ordered(self) -> "UtteranceSegmentationPolicy":
        if (
            self.minimum_utterance_duration_microseconds
            > self.maximum_utterance_duration_microseconds
        ):
            raise ValueError("minimum utterance duration exceeds maximum")
        return self


class UtteranceNormalizationPolicy(Contract):
    policy_version: Literal["1.0.0"] = UTTERANCE_NORMALIZATION_POLICY_VERSION
    normalize_whitespace: bool = True
    normalize_capitalization: bool = False
    normalize_punctuation: bool = False
    retain_repeated_fillers: bool = True
    retain_meaningful_repetitions: bool = True
    retain_disfluency_markers: bool = True
    retain_uncertain_tokens: bool = True
    strip_subtitle_line_breaks: bool = True
    additions_prohibited: bool = True


class UtteranceAnalysisPolicy(Contract):
    policy_version: Literal["1.0.0"] = UTTERANCE_ANALYSIS_POLICY_VERSION
    short_fragment_max_microseconds: int = Field(default=500_000, ge=1)
    source_boundary_tolerance_microseconds: int = Field(default=1, ge=0)
    maximum_repetition_window_words: int = Field(default=1, ge=1, le=3)
    filler_tokens: tuple[str, ...] = ("um", "uh", "erm", "hmm")
    repair_marker_tokens: tuple[str, ...] = ("i mean", "rather", "sorry")
    hesitation_tokens: tuple[str, ...] = ("...", "…")
    terminal_punctuation_enabled: bool = True
    semantic_inference: Literal["prohibited"] = "prohibited"
    clinical_diagnosis: Literal["prohibited"] = "prohibited"

    @model_validator(mode="after")
    def token_sets_are_normalized_and_unique(self) -> "UtteranceAnalysisPolicy":
        for values in (
            self.filler_tokens,
            self.repair_marker_tokens,
            self.hesitation_tokens,
        ):
            if any(not item or item != item.casefold() for item in values):
                raise ValueError(
                    "analysis policy tokens must be non-empty casefold"
                )
            if len(values) != len(set(values)):
                raise ValueError("analysis policy tokens must be unique")
        return self


class UtteranceTextView(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    view_id: str = Field(pattern=r"^utterancetext_[a-f0-9]{32}$")
    kind: UtteranceTextKind
    text: str
    derivation_policy: str = Field(min_length=1)
    source_transcript_segment_ids: tuple[str, ...] = ()
    source_transcript_word_ids: tuple[str, ...] = ()
    correction_revision_id: str | None = None
    review_action_ids: tuple[str, ...] = ()
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def source_references_are_unique(self) -> "UtteranceTextView":
        for values in (
            self.source_transcript_segment_ids,
            self.source_transcript_word_ids,
            self.review_action_ids,
        ):
            if len(values) != len(set(values)):
                raise ValueError("utterance text references must be unique")
        return self


class UtteranceAttribution(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    attribution_id: str = Field(pattern=r"^utteranceattr_[a-f0-9]{32}$")
    status: UtteranceAttributionStatus
    target_kind: UtteranceAttributionTargetKind
    target_id: str | None = None
    candidate_target_ids: tuple[str, ...] = ()
    display_label: str = Field(min_length=1)
    confidence: ConfidenceMeasure
    phase3_identity_view_assembly_id: str = Field(
        pattern=r"^identityviewassembly_[a-f0-9]{32}$"
    )
    phase3_reviewed_identity_view_id: str = Field(
        pattern=r"^identityview_[a-f0-9]{32}$"
    )
    speaker_turn_ids: tuple[str, ...] = ()
    speaker_observation_ids: tuple[str, ...] = ()
    evidence_references: tuple[str, ...] = Field(min_length=1)
    findings: tuple[str, ...] = ()
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def target_matches_status(self) -> "UtteranceAttribution":
        if self.status == UtteranceAttributionStatus.UNKNOWN:
            if (
                self.target_kind != UtteranceAttributionTargetKind.UNKNOWN
                or self.target_id is not None
                or self.candidate_target_ids
            ):
                raise ValueError("unknown attribution cannot force a target")
        elif self.status == UtteranceAttributionStatus.CONFLICTING:
            if (
                self.target_kind
                != UtteranceAttributionTargetKind.MULTIPLE_CANDIDATES
                or len(self.candidate_target_ids) < 2
                or self.target_id is not None
            ):
                raise ValueError(
                    "conflicting attribution requires multiple candidates"
                )
        elif self.target_id is None:
            raise ValueError("resolved attribution requires one target")
        if len(self.candidate_target_ids) != len(
            set(self.candidate_target_ids)
        ):
            raise ValueError("attribution candidates must be unique")
        return self


class UtteranceComponent(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    component_id: str = Field(pattern=r"^utterancecomponent_[a-f0-9]{32}$")
    sequence_position: int = Field(ge=0)
    source_interval: MediaInterval
    normalized_audio_interval: MediaInterval
    transcript_segment_ids: tuple[str, ...] = Field(min_length=1)
    transcript_word_ids: tuple[str, ...] = ()
    speaker_turn_ids: tuple[str, ...] = ()
    speaker_observation_ids: tuple[str, ...] = ()
    verbatim_text: str
    uncertain_word_attribution: bool = False
    processing_chunk_ids: tuple[str, ...] = ()
    findings: tuple[str, ...] = ()
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def domains_and_references_are_valid(self) -> "UtteranceComponent":
        if self.source_interval.domain != TimeDomain.SOURCE_MEDIA:
            raise ValueError("component source interval has invalid domain")
        if (
            self.normalized_audio_interval.domain
            != TimeDomain.NORMALIZED_CORPUS
        ):
            raise ValueError("component normalized interval has invalid domain")
        for values in (
            self.transcript_segment_ids,
            self.transcript_word_ids,
            self.speaker_turn_ids,
            self.speaker_observation_ids,
            self.processing_chunk_ids,
        ):
            if len(values) != len(set(values)):
                raise ValueError("component references must be unique")
        return self


class Utterance(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    utterance_id: str = Field(pattern=r"^utterance_[a-f0-9]{32}$")
    utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    source_corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    source_id: str = Field(pattern=r"^src_[a-f0-9]{32}$")
    phase2_transcript_assembly_id: str = Field(
        pattern=r"^txassembly_[a-f0-9]{32}$"
    )
    phase2_transcript_version_id: str = Field(
        pattern=r"^txversion_[a-f0-9]{32}$"
    )
    phase3_identity_view_assembly_id: str = Field(
        pattern=r"^identityviewassembly_[a-f0-9]{32}$"
    )
    phase3_reviewed_identity_view_id: str = Field(
        pattern=r"^identityview_[a-f0-9]{32}$"
    )
    components: tuple[UtteranceComponent, ...] = Field(min_length=1)
    source_intervals: tuple[MediaInterval, ...] = Field(min_length=1)
    normalized_audio_intervals: tuple[MediaInterval, ...] = Field(min_length=1)
    attribution: UtteranceAttribution
    text_views: tuple[UtteranceTextView, ...] = Field(min_length=1)
    displayed_text_view_id: str = Field(
        pattern=r"^utterancetext_[a-f0-9]{32}$"
    )
    completeness: UtteranceCompletenessClassification
    completeness_evidence_references: tuple[str, ...] = Field(min_length=1)
    interruption_status: UtteranceInterruptionStatus
    repair_status: UtteranceRepairStatus
    overlap_status: UtteranceOverlapStatus
    quotation_status: UtteranceQuotationStatus
    speech_source_type: SpeechSourceType
    context_reference_ids: tuple[str, ...] = ()
    review_status: UtteranceReviewStatus
    creation_process: UtteranceCreationProcess
    segmentation_policy_version: Literal["1.0.0"] = (
        UTTERANCE_SEGMENTATION_POLICY_VERSION
    )
    normalization_policy_version: Literal["1.0.0"] = (
        UTTERANCE_NORMALIZATION_POLICY_VERSION
    )
    configuration_hash: Sha256
    predecessor_utterance_ids: tuple[str, ...] = ()
    invalidates_utterance_ids: tuple[str, ...] = ()
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def construction_is_coherent(self) -> "Utterance":
        component_ids = [item.component_id for item in self.components]
        positions = [item.sequence_position for item in self.components]
        if len(component_ids) != len(set(component_ids)):
            raise ValueError("utterance component identifiers must be unique")
        if positions != list(range(len(self.components))):
            raise ValueError("utterance component positions must be contiguous")
        for intervals, domain in (
            (self.source_intervals, TimeDomain.SOURCE_MEDIA),
            (self.normalized_audio_intervals, TimeDomain.NORMALIZED_CORPUS),
        ):
            if any(item.domain != domain for item in intervals):
                raise ValueError("utterance interval has invalid time domain")
            starts = [item.start_microseconds for item in intervals]
            if starts != sorted(starts):
                raise ValueError("utterance intervals must be ordered")
        text_ids = [item.view_id for item in self.text_views]
        if len(text_ids) != len(set(text_ids)):
            raise ValueError("utterance text-view identifiers must be unique")
        kinds = [item.kind for item in self.text_views]
        for required in (
            UtteranceTextKind.RAW_MACHINE_TRANSCRIPT,
            UtteranceTextKind.DISPLAY,
            UtteranceTextKind.MINIMALLY_NORMALIZED_ANALYSIS,
        ):
            if kinds.count(required) != 1:
                raise ValueError(f"utterance requires exactly one {required.value}")
        display = next(
            item
            for item in self.text_views
            if item.kind == UtteranceTextKind.DISPLAY
        )
        if self.displayed_text_view_id != display.view_id:
            raise ValueError("displayed text view must reference the display view")
        if (
            self.attribution.phase3_identity_view_assembly_id
            != self.phase3_identity_view_assembly_id
            or self.attribution.phase3_reviewed_identity_view_id
            != self.phase3_reviewed_identity_view_id
        ):
            raise ValueError("utterance attribution lineage is incompatible")
        if (
            self.completeness
            == UtteranceCompletenessClassification.INTERRUPTED
            and self.interruption_status
            not in {
                UtteranceInterruptionStatus.INTERRUPTED,
                UtteranceInterruptionStatus.BOTH,
                UtteranceInterruptionStatus.UNCERTAIN,
            }
        ):
            raise ValueError(
                "interrupted completeness requires interruption state"
            )
        return self


class UtteranceRun(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    run_id: str = Field(pattern=r"^utterancerun_[a-f0-9]{32}$")
    utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    source_corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    phase2_transcript_assembly_id: str = Field(
        pattern=r"^txassembly_[a-f0-9]{32}$"
    )
    phase2_transcript_version_id: str = Field(
        pattern=r"^txversion_[a-f0-9]{32}$"
    )
    phase3_diarization_run_id: str = Field(
        pattern=r"^diarun_[a-f0-9]{32}$"
    )
    phase3_identity_view_assembly_id: str = Field(
        pattern=r"^identityviewassembly_[a-f0-9]{32}$"
    )
    phase3_reviewed_identity_view_id: str = Field(
        pattern=r"^identityview_[a-f0-9]{32}$"
    )
    segmentation_policy: UtteranceSegmentationPolicy
    normalization_policy: UtteranceNormalizationPolicy
    configuration_hash: Sha256
    utterance_ids: tuple[str, ...]
    created_at: datetime
    complete: bool
    integrity_sha256: Sha256


class UtteranceCorpus(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    corpus_id: str = Field(pattern=r"^utterancecorpus_[a-f0-9]{32}$")
    run_id: str = Field(pattern=r"^utterancerun_[a-f0-9]{32}$")
    source_corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    source_id: str = Field(pattern=r"^src_[a-f0-9]{32}$")
    phase2_transcript_assembly_id: str = Field(
        pattern=r"^txassembly_[a-f0-9]{32}$"
    )
    phase2_transcript_version_id: str = Field(
        pattern=r"^txversion_[a-f0-9]{32}$"
    )
    phase3_identity_view_assembly_id: str = Field(
        pattern=r"^identityviewassembly_[a-f0-9]{32}$"
    )
    phase3_reviewed_identity_view_id: str = Field(
        pattern=r"^identityview_[a-f0-9]{32}$"
    )
    utterances: tuple[Utterance, ...]
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def canonical_ownership_and_lineage_are_valid(self) -> "UtteranceCorpus":
        utterance_ids = [item.utterance_id for item in self.utterances]
        if len(utterance_ids) != len(set(utterance_ids)):
            raise ValueError("utterance identifiers must be unique")
        owned_words: set[str] = set()
        for utterance in self.utterances:
            if (
                utterance.utterance_corpus_id != self.corpus_id
                or utterance.source_corpus_id != self.source_corpus_id
                or utterance.source_id != self.source_id
                or utterance.phase2_transcript_assembly_id
                != self.phase2_transcript_assembly_id
                or utterance.phase2_transcript_version_id
                != self.phase2_transcript_version_id
                or utterance.phase3_identity_view_assembly_id
                != self.phase3_identity_view_assembly_id
                or utterance.phase3_reviewed_identity_view_id
                != self.phase3_reviewed_identity_view_id
            ):
                raise ValueError("utterance corpus lineage is incompatible")
            for component in utterance.components:
                overlap = owned_words.intersection(component.transcript_word_ids)
                if overlap:
                    raise ValueError(
                        "canonical transcript word has duplicate ownership"
                    )
                owned_words.update(component.transcript_word_ids)
        return self


class Phase4IntegrityFinding(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    finding_id: str = Field(pattern=r"^phase4finding_[a-f0-9]{32}$")
    code: str = Field(pattern=r"^phase4\.[a-z0-9_.-]+$")
    severity: Severity
    message: str = Field(min_length=1)
    artifact_ids: tuple[str, ...] = ()
    evidence_references: tuple[str, ...] = ()


class Phase4IntegrityResult(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    result_id: str = Field(pattern=r"^phase4integrity_[a-f0-9]{32}$")
    utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    checked_at: datetime
    findings: tuple[Phase4IntegrityFinding, ...] = ()
    valid: bool
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def validity_matches_findings(self) -> "Phase4IntegrityResult":
        blocking = any(
            item.severity in {Severity.ERROR, Severity.FATAL}
            for item in self.findings
        )
        if self.valid == blocking:
            raise ValueError("integrity validity disagrees with findings")
        return self


class UtteranceCorpusReport(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    report_id: str = Field(pattern=r"^utterancereport_[a-f0-9]{32}$")
    utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    run_id: str = Field(pattern=r"^utterancerun_[a-f0-9]{32}$")
    generated_at: datetime
    utterance_count: int = Field(ge=0)
    complete_count: int = Field(ge=0)
    incomplete_count: int = Field(ge=0)
    unknown_attribution_count: int = Field(ge=0)
    conflicting_attribution_count: int = Field(ge=0)
    overlap_aware_count: int = Field(ge=0)
    review_required_count: int = Field(ge=0)
    findings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    status: Literal["complete", "partial", "warning", "failed"]
    integrity_sha256: Sha256


class UtteranceCompletenessAssessment(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    assessment_id: str = Field(pattern=r"^utterancecomplete_[a-f0-9]{32}$")
    utterance_id: str = Field(pattern=r"^utterance_[a-f0-9]{32}$")
    utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    classification: UtteranceCompletenessClassification
    observed_signals: tuple[str, ...] = Field(min_length=1)
    evidence_references: tuple[str, ...] = Field(min_length=1)
    confidence: ConfidenceMeasure
    review_status: UtteranceReviewStatus
    policy_version: Literal["1.0.0"] = UTTERANCE_ANALYSIS_POLICY_VERSION
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def evidence_is_unique(self) -> "UtteranceCompletenessAssessment":
        if len(self.evidence_references) != len(set(self.evidence_references)):
            raise ValueError("completeness evidence references must be unique")
        return self


class DisfluencySpan(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    disfluency_id: str = Field(pattern=r"^disfluency_[a-f0-9]{32}$")
    utterance_id: str = Field(pattern=r"^utterance_[a-f0-9]{32}$")
    utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    kind: DisfluencyKind
    transcript_word_ids: tuple[str, ...] = Field(min_length=1)
    source_intervals: tuple[MediaInterval, ...] = Field(min_length=1)
    normalized_audio_intervals: tuple[MediaInterval, ...] = Field(min_length=1)
    surface_text: str = Field(min_length=1)
    evidence_references: tuple[str, ...] = Field(min_length=1)
    confidence: ConfidenceMeasure
    review_status: UtteranceReviewStatus
    policy_version: Literal["1.0.0"] = UTTERANCE_ANALYSIS_POLICY_VERSION
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def addressing_is_valid(self) -> "DisfluencySpan":
        if len(self.transcript_word_ids) != len(set(self.transcript_word_ids)):
            raise ValueError("disfluency word references must be unique")
        for intervals, domain in (
            (self.source_intervals, TimeDomain.SOURCE_MEDIA),
            (self.normalized_audio_intervals, TimeDomain.NORMALIZED_CORPUS),
        ):
            if any(item.domain != domain for item in intervals):
                raise ValueError("disfluency interval has invalid time domain")
            if [item.start_microseconds for item in intervals] != sorted(
                item.start_microseconds for item in intervals
            ):
                raise ValueError("disfluency intervals must be ordered")
        return self


class SelfRepair(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    self_repair_id: str = Field(pattern=r"^selfrepair_[a-f0-9]{32}$")
    utterance_id: str = Field(pattern=r"^utterance_[a-f0-9]{32}$")
    utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    kind: SelfRepairKind
    reparandum_word_ids: tuple[str, ...] = Field(min_length=1)
    repair_marker_word_ids: tuple[str, ...] = ()
    repair_word_ids: tuple[str, ...] = ()
    interruption_point_normalized_microseconds: int = Field(ge=0)
    evidence_references: tuple[str, ...] = Field(min_length=1)
    confidence: ConfidenceMeasure
    review_status: UtteranceReviewStatus
    policy_version: Literal["1.0.0"] = UTTERANCE_ANALYSIS_POLICY_VERSION
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def repair_parts_are_disjoint(self) -> "SelfRepair":
        groups = (
            self.reparandum_word_ids,
            self.repair_marker_word_ids,
            self.repair_word_ids,
        )
        if any(len(values) != len(set(values)) for values in groups):
            raise ValueError("self-repair word references must be unique")
        if any(set(left).intersection(right) for index, left in enumerate(groups)
               for right in groups[index + 1:]):
            raise ValueError("self-repair parts must be disjoint")
        if (
            self.kind != SelfRepairKind.ABANDONMENT
            and not self.repair_word_ids
        ):
            raise ValueError("bounded self-repair requires repair words")
        return self


class UtteranceAnalysisRun(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    analysis_id: str = Field(pattern=r"^utteranceanalysis_[a-f0-9]{32}$")
    utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    utterance_run_id: str = Field(pattern=r"^utterancerun_[a-f0-9]{32}$")
    phase2_transcript_assembly_id: str = Field(
        pattern=r"^txassembly_[a-f0-9]{32}$"
    )
    policy: UtteranceAnalysisPolicy
    configuration_hash: Sha256
    completeness_assessments: tuple[UtteranceCompletenessAssessment, ...]
    disfluency_spans: tuple[DisfluencySpan, ...]
    self_repairs: tuple[SelfRepair, ...]
    created_at: datetime
    complete: bool
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def child_identifiers_are_unique(self) -> "UtteranceAnalysisRun":
        for values in (
            tuple(item.assessment_id for item in self.completeness_assessments),
            tuple(item.disfluency_id for item in self.disfluency_spans),
            tuple(item.self_repair_id for item in self.self_repairs),
        ):
            if len(values) != len(set(values)):
                raise ValueError("analysis child identifiers must be unique")
        return self


class UtteranceAnalysisReport(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    report_id: str = Field(pattern=r"^utteranceanalysisreport_[a-f0-9]{32}$")
    analysis_id: str = Field(pattern=r"^utteranceanalysis_[a-f0-9]{32}$")
    utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    generated_at: datetime
    assessment_count: int = Field(ge=0)
    complete_count: int = Field(ge=0)
    unresolved_count: int = Field(ge=0)
    disfluency_count: int = Field(ge=0)
    filler_count: int = Field(ge=0)
    repetition_count: int = Field(ge=0)
    hesitation_count: int = Field(ge=0)
    self_repair_count: int = Field(ge=0)
    review_required_count: int = Field(ge=0)
    findings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    status: Literal["complete", "partial", "warning", "failed"]
    integrity_sha256: Sha256


PHASE4_CONTRACT_MODELS = (
    UtteranceSegmentationPolicy,
    UtteranceNormalizationPolicy,
    UtteranceAnalysisPolicy,
    UtteranceTextView,
    UtteranceAttribution,
    UtteranceComponent,
    Utterance,
    UtteranceRun,
    UtteranceCorpus,
    Phase4IntegrityFinding,
    Phase4IntegrityResult,
    UtteranceCorpusReport,
    UtteranceCompletenessAssessment,
    DisfluencySpan,
    SelfRepair,
    UtteranceAnalysisRun,
    UtteranceAnalysisReport,
)
