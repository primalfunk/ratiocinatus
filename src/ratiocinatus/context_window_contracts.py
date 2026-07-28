"""Phase 4 deterministic context-window contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .addressing_contracts import MediaInterval, TimeDomain
from .contracts import Contract, Sha256
from .phase4_contracts import PHASE4_FORMAT_VERSION

CONTEXT_WINDOW_POLICY_VERSION = "1.0.0"


class ContextWindowKind(str, Enum):
    PRECEDING = "preceding_utterances"
    FOLLOWING = "following_utterances"
    SAME_SPEAKER_HISTORY = "same_speaker_history"
    CURRENT_TURN_NEIGHBORHOOD = "current_turn_neighborhood"
    EXCHANGE = "exchange_window"
    QUESTION_RESPONSE = "question_response_window"
    INTERRUPTION = "interruption_neighborhood"
    QUOTATION = "quotation_neighborhood"
    BOUNDED_TEMPORAL = "bounded_temporal_window"


class ContextInclusionReason(str, Enum):
    TARGET = "target"
    PRECEDING = "preceding"
    FOLLOWING = "following"
    SAME_SPEAKER = "same_speaker"
    CURRENT_TURN = "current_turn"
    EXCHANGE_NEIGHBOR = "exchange_neighbor"
    QUESTION = "question"
    RESPONSE = "response"
    INTERRUPTION = "interruption"
    CONTINUATION = "continuation"
    QUOTATION = "quotation"
    QUOTATION_NEIGHBOR = "quotation_neighbor"
    TEMPORAL_PROXIMITY = "temporal_proximity"
    SIMULTANEOUS_OVERLAP = "simultaneous_overlap"


class ContextExclusionKind(str, Enum):
    OUTSIDE_WINDOW_POLICY = "outside_window_policy"
    STRUCTURE_UNAVAILABLE = "structure_unavailable"
    MAXIMUM_UTTERANCE_COUNT = "maximum_utterance_count"
    MAXIMUM_TOKEN_ESTIMATE = "maximum_token_estimate"
    MAXIMUM_SOURCE_DURATION = "maximum_source_duration"


class ContextWindowPolicy(Contract):
    policy_version: Literal["1.0.0"] = CONTEXT_WINDOW_POLICY_VERSION
    preceding_utterance_count: int = Field(default=4, ge=0, le=100)
    following_utterance_count: int = Field(default=4, ge=0, le=100)
    same_speaker_history_count: int = Field(default=6, ge=0, le=100)
    temporal_radius_microseconds: int = Field(
        default=30_000_000, ge=1, le=3_600_000_000
    )
    maximum_utterance_count: int = Field(default=12, ge=1, le=1_000)
    maximum_token_estimate: int = Field(default=1_200, ge=1)
    maximum_source_duration_microseconds: int = Field(
        default=120_000_000, ge=1
    )
    token_estimate_characters_per_token: int = Field(default=4, ge=1)
    speaker_balanced_selection: bool = True
    recency_weighting: Literal["nearest_first"] = "nearest_first"
    preserve_question_response: bool = True
    preserve_interruption_relations: bool = True
    preserve_quotation_sources: bool = True
    preserve_simultaneous_overlap: bool = True
    truncation_must_be_explicit: Literal[True] = True


class ContextWindowMember(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    member_id: str = Field(pattern=r"^contextmember_[a-f0-9]{32}$")
    utterance_id: str = Field(pattern=r"^utterance_[a-f0-9]{32}$")
    order_position: int = Field(ge=0)
    corpus_sequence_position: int = Field(ge=0)
    temporal_group_id: str = Field(pattern=r"^temporalgroup_[a-f0-9]{32}$")
    temporal_lane: int = Field(ge=0)
    simultaneous_with_utterance_ids: tuple[str, ...] = ()
    source_intervals: tuple[MediaInterval, ...] = Field(min_length=1)
    normalized_audio_intervals: tuple[MediaInterval, ...] = Field(min_length=1)
    inclusion_reasons: tuple[ContextInclusionReason, ...] = Field(min_length=1)
    character_count: int = Field(ge=0)
    token_estimate: int = Field(ge=0)
    evidence_references: tuple[str, ...] = Field(min_length=1)
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def addressing_and_reasons_are_valid(self) -> "ContextWindowMember":
        for intervals, domain in (
            (self.source_intervals, TimeDomain.SOURCE_MEDIA),
            (self.normalized_audio_intervals, TimeDomain.NORMALIZED_CORPUS),
        ):
            if any(item.domain != domain for item in intervals):
                raise ValueError("context member interval has invalid domain")
        if len(self.inclusion_reasons) != len(set(self.inclusion_reasons)):
            raise ValueError("context inclusion reasons must be unique")
        if len(self.simultaneous_with_utterance_ids) != len(
            set(self.simultaneous_with_utterance_ids)
        ):
            raise ValueError("simultaneous references must be unique")
        if self.utterance_id in self.simultaneous_with_utterance_ids:
            raise ValueError("context member cannot be simultaneous with itself")
        return self


class ContextExclusionSummary(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    summary_id: str = Field(pattern=r"^contextomission_[a-f0-9]{32}$")
    kind: ContextExclusionKind
    omitted_utterance_count: int = Field(ge=0)
    omitted_utterance_ids: tuple[str, ...] = ()
    identifiers_complete: bool
    explanation: str = Field(min_length=1)
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def omission_count_is_coherent(self) -> "ContextExclusionSummary":
        if len(self.omitted_utterance_ids) != len(
            set(self.omitted_utterance_ids)
        ):
            raise ValueError("omitted utterance identifiers must be unique")
        if self.identifiers_complete and self.omitted_utterance_count != len(
            self.omitted_utterance_ids
        ):
            raise ValueError("complete omission identifiers must match count")
        return self


class UtteranceContextWindow(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    context_window_id: str = Field(pattern=r"^contextwindow_[a-f0-9]{32}$")
    context_bundle_id: str = Field(pattern=r"^contextbundle_[a-f0-9]{32}$")
    utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    transcript_view_bundle_id: str = Field(
        pattern=r"^utteranceviewbundle_[a-f0-9]{32}$"
    )
    target_utterance_id: str = Field(pattern=r"^utterance_[a-f0-9]{32}$")
    kind: ContextWindowKind
    policy: ContextWindowPolicy
    members: tuple[ContextWindowMember, ...] = Field(min_length=1)
    source_intervals: tuple[MediaInterval, ...] = Field(min_length=1)
    character_count: int = Field(ge=0)
    token_estimate: int = Field(ge=0)
    source_duration_microseconds: int = Field(ge=0)
    structurally_available: bool
    truncated: bool
    complete_exchange_considered: bool
    exclusions: tuple[ContextExclusionSummary, ...] = ()
    ordering_basis: str = Field(min_length=1)
    integrity_status: Literal["valid"] = "valid"
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def membership_and_budget_are_coherent(self) -> "UtteranceContextWindow":
        positions = [item.order_position for item in self.members]
        if positions != list(range(len(self.members))):
            raise ValueError("context member positions must be contiguous")
        identifiers = [item.utterance_id for item in self.members]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("context window cannot duplicate utterances")
        if identifiers.count(self.target_utterance_id) != 1:
            raise ValueError("context window must contain its target once")
        if self.character_count != sum(item.character_count for item in self.members):
            raise ValueError("context character count is invalid")
        if self.token_estimate != sum(item.token_estimate for item in self.members):
            raise ValueError("context token estimate is invalid")
        budget_kinds = {
            ContextExclusionKind.MAXIMUM_UTTERANCE_COUNT,
            ContextExclusionKind.MAXIMUM_TOKEN_ESTIMATE,
            ContextExclusionKind.MAXIMUM_SOURCE_DURATION,
        }
        if self.truncated != any(item.kind in budget_kinds for item in self.exclusions):
            raise ValueError("context truncation must match budget exclusions")
        if self.complete_exchange_considered == self.truncated:
            raise ValueError("complete-exchange flag must disclose truncation")
        return self


class ContextWindowBundle(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    context_bundle_id: str = Field(pattern=r"^contextbundle_[a-f0-9]{32}$")
    utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    utterance_run_id: str = Field(pattern=r"^utterancerun_[a-f0-9]{32}$")
    utterance_relation_run_id: str = Field(
        pattern=r"^utterancerelations_[a-f0-9]{32}$"
    )
    quotation_run_id: str = Field(pattern=r"^quotationrun_[a-f0-9]{32}$")
    transcript_view_bundle_id: str = Field(
        pattern=r"^utteranceviewbundle_[a-f0-9]{32}$"
    )
    policy: ContextWindowPolicy
    configuration_hash: Sha256
    windows: tuple[UtteranceContextWindow, ...]
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def required_windows_are_present(self) -> "ContextWindowBundle":
        pairs = [(item.target_utterance_id, item.kind) for item in self.windows]
        if len(pairs) != len(set(pairs)):
            raise ValueError("context target and kind pairs must be unique")
        targets = {item.target_utterance_id for item in self.windows}
        for target in targets:
            kinds = {kind for item_target, kind in pairs if item_target == target}
            if kinds != set(ContextWindowKind):
                raise ValueError("each context target requires all window kinds")
        if any(item.context_bundle_id != self.context_bundle_id for item in self.windows):
            raise ValueError("context window belongs to another bundle")
        return self


class ContextWindowReport(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    report_id: str = Field(pattern=r"^contextreport_[a-f0-9]{32}$")
    context_bundle_id: str = Field(pattern=r"^contextbundle_[a-f0-9]{32}$")
    utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    created_at: datetime
    target_utterance_count: int = Field(ge=0)
    window_count: int = Field(ge=0)
    truncated_window_count: int = Field(ge=0)
    structurally_unavailable_window_count: int = Field(ge=0)
    omitted_utterance_count: int = Field(ge=0)
    maximum_observed_token_estimate: int = Field(ge=0)
    maximum_observed_source_duration_microseconds: int = Field(ge=0)
    status: Literal["complete", "warning", "failed"]
    limitations: tuple[str, ...] = ()
    integrity_sha256: Sha256


CONTEXT_WINDOW_CONTRACT_MODELS = (
    ContextWindowPolicy,
    ContextWindowMember,
    ContextExclusionSummary,
    UtteranceContextWindow,
    ContextWindowBundle,
    ContextWindowReport,
)
