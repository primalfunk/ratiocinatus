"""Descriptive procedural event and conversation-state contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .addressing_contracts import MediaInterval, TimeDomain
from .contracts import Contract, Sha256
from .phase2_contracts import ConfidenceMeasure
from .phase5_contracts import (
    FAMILY_TYPES,
    PHASE5_FORMAT_VERSION,
    DiscourseActFamily,
    DiscourseActType,
    DiscourseReviewStatus,
    DiscourseTargetStatus,
)

PROCEDURAL_STATE_POLICY_VERSION = "1.0.0"


class ProceduralEventKind(str, Enum):
    FLOOR_REQUEST = "floor_request"
    FLOOR_GRANT = "floor_grant"
    FLOOR_DENIAL = "floor_denial"
    TURN_YIELD = "turn_yield"
    TIME_WARNING = "time_warning"
    TIME_EXPIRED = "time_expired"
    TOPIC_TRANSITION = "topic_transition"
    AGENDA_SETTING = "agenda_setting"
    ANSWER_REQUEST = "answer_request"
    CLARIFICATION_REQUEST = "clarification_request"
    STOP_REQUEST = "stop_request"
    MODERATOR_INSTRUCTION = "moderator_instruction"
    RULE_EVENT = "rule_event"
    PROCEDURE_ACKNOWLEDGMENT = "procedure_acknowledgment"
    OPENING_OR_CLOSING = "opening_or_closing"
    SOCIAL_PROCEDURAL = "social_procedural"
    TECHNICAL_INTERRUPTION = "technical_interruption"
    PROCEDURAL_QUESTION = "procedural_question"
    UNRESOLVED = "unresolved"


class ProceduralStatePolicy(Contract):
    policy_version: Literal["1.0.0"] = PROCEDURAL_STATE_POLICY_VERSION
    order_basis: Literal["source_media_time_then_act_id"] = (
        "source_media_time_then_act_id"
    )
    observed_speaker_distinct_from_recognized_speaker: Literal[True] = True
    unresolved_floor_target_is_valid: Literal[True] = True
    every_event_requires_source_interval: Literal[True] = True
    every_state_change_requires_event: Literal[True] = True
    descriptive_only: Literal[True] = True
    violation_assignment: Literal[False] = False
    fault_assignment: Literal[False] = False
    blame_assignment: Literal[False] = False
    sanction_assignment: Literal[False] = False
    intent_inference: Literal["prohibited"] = "prohibited"


class ProceduralEvent(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    event_id: str = Field(pattern=r"^proceduralevent_[a-f0-9]{32}$")
    discourse_corpus_id: str = Field(
        pattern=r"^discoursecorpus_[a-f0-9]{32}$"
    )
    source_act_id: str = Field(pattern=r"^discourseact_[a-f0-9]{32}$")
    utterance_id: str = Field(pattern=r"^utterance_[a-f0-9]{32}$")
    procedural_act_type: DiscourseActType
    event_kind: ProceduralEventKind
    source_intervals: tuple[MediaInterval, ...] = Field(min_length=1)
    evidence_span_ids: tuple[str, ...] = Field(min_length=1)
    observed_attribution_id: str = Field(
        pattern=r"^utteranceattr_[a-f0-9]{32}$"
    )
    observed_speaker_target_id: str | None = None
    observed_speaker_display_label: str = Field(min_length=1)
    procedural_target_status: DiscourseTargetStatus
    procedural_target_ids: tuple[str, ...]
    alternative_procedural_target_ids: tuple[str, ...] = ()
    descriptive_effects: tuple[str, ...] = Field(min_length=1)
    confidence: ConfidenceMeasure
    review_status: DiscourseReviewStatus
    violation_assigned: Literal[False] = False
    fault_assigned: Literal[False] = False
    blame_assigned: Literal[False] = False
    sanction_assigned: Literal[False] = False
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def event_is_coherent(self) -> "ProceduralEvent":
        if self.procedural_act_type not in FAMILY_TYPES[
            DiscourseActFamily.PROCEDURAL
        ] and self.procedural_act_type != DiscourseActType.PROCEDURAL_QUESTION:
            raise ValueError("procedural event requires procedural source act")
        if any(
            item.domain != TimeDomain.SOURCE_MEDIA
            for item in self.source_intervals
        ):
            raise ValueError("procedural event requires source-media intervals")
        if (
            self.procedural_target_status
            == DiscourseTargetStatus.MULTIPLE_CANDIDATES
            and len(self.alternative_procedural_target_ids) < 2
        ):
            raise ValueError("ambiguous procedural target requires alternatives")
        return self


class ProceduralStateSnapshot(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    snapshot_id: str = Field(
        pattern=r"^proceduralstate_[a-f0-9]{32}$"
    )
    procedural_state_run_id: str = Field(
        pattern=r"^proceduralstaterun_[a-f0-9]{32}$"
    )
    sequence_position: int = Field(ge=0)
    triggering_event_id: str = Field(
        pattern=r"^proceduralevent_[a-f0-9]{32}$"
    )
    effective_source_microseconds: int = Field(ge=0)
    observed_speaker_target_id: str | None = None
    observed_speaker_display_label: str = Field(min_length=1)
    recognized_speaker_target_id: str | None = None
    recognized_speaker_status: DiscourseTargetStatus
    pending_question_act_ids: tuple[str, ...] = ()
    alternative_pending_question_act_ids: tuple[str, ...] = ()
    active_response: bool
    active_response_started_microseconds: int | None = Field(
        default=None, ge=0
    )
    active_response_target_id: str | None = None
    latest_moderator_instruction_act_id: str | None = Field(
        default=None, pattern=r"^discourseact_[a-f0-9]{32}$"
    )
    latest_time_warning_act_id: str | None = Field(
        default=None, pattern=r"^discourseact_[a-f0-9]{32}$"
    )
    time_expired: bool
    granted_extension: bool
    latest_clarification_request_act_id: str | None = Field(
        default=None, pattern=r"^discourseact_[a-f0-9]{32}$"
    )
    latest_topic_transition_act_id: str | None = Field(
        default=None, pattern=r"^discourseact_[a-f0-9]{32}$"
    )
    unresolved_event_ids: tuple[str, ...] = ()
    descriptive_only: Literal[True] = True
    violation_assigned: Literal[False] = False
    fault_assigned: Literal[False] = False
    blame_assigned: Literal[False] = False
    sanction_assigned: Literal[False] = False
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def state_is_coherent(self) -> "ProceduralStateSnapshot":
        if self.active_response != (
            self.active_response_started_microseconds is not None
        ):
            raise ValueError("active response requires a start time")
        if self.recognized_speaker_status in {
            DiscourseTargetStatus.IMPLICIT,
            DiscourseTargetStatus.UNRESOLVED,
        } and self.recognized_speaker_target_id is not None:
            raise ValueError("unresolved recognized speaker cannot force id")
        return self


class ProceduralStateRun(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    procedural_state_run_id: str = Field(
        pattern=r"^proceduralstaterun_[a-f0-9]{32}$"
    )
    discourse_corpus_id: str = Field(
        pattern=r"^discoursecorpus_[a-f0-9]{32}$"
    )
    discourse_corpus_sha256: Sha256
    phase4_utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    phase4_utterance_corpus_sha256: Sha256
    policy: ProceduralStatePolicy
    configuration_hash: Sha256
    events: tuple[ProceduralEvent, ...]
    snapshots: tuple[ProceduralStateSnapshot, ...]
    final_snapshot_id: str | None = Field(
        default=None, pattern=r"^proceduralstate_[a-f0-9]{32}$"
    )
    created_at: datetime
    complete: bool
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def run_is_coherent(self) -> "ProceduralStateRun":
        event_ids = [item.event_id for item in self.events]
        snapshot_ids = [item.snapshot_id for item in self.snapshots]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("procedural event ids must be unique")
        if len(snapshot_ids) != len(set(snapshot_ids)):
            raise ValueError("procedural snapshot ids must be unique")
        if len(self.events) != len(self.snapshots):
            raise ValueError("every procedural event requires one snapshot")
        if [item.sequence_position for item in self.snapshots] != list(
            range(len(self.snapshots))
        ):
            raise ValueError("procedural snapshots must be contiguous")
        if any(
            snapshot.triggering_event_id != event.event_id
            for event, snapshot in zip(self.events, self.snapshots)
        ):
            raise ValueError("procedural snapshot event inventory is stale")
        expected_final = snapshot_ids[-1] if snapshot_ids else None
        if self.final_snapshot_id != expected_final:
            raise ValueError("procedural final snapshot is stale")
        return self


class ProceduralStateReport(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    report_id: str = Field(
        pattern=r"^proceduralstatereport_[a-f0-9]{32}$"
    )
    procedural_state_run_id: str = Field(
        pattern=r"^proceduralstaterun_[a-f0-9]{32}$"
    )
    generated_at: datetime
    event_count: int = Field(ge=0)
    floor_event_count: int = Field(ge=0)
    timing_event_count: int = Field(ge=0)
    moderator_instruction_count: int = Field(ge=0)
    pending_question_event_count: int = Field(ge=0)
    topic_transition_count: int = Field(ge=0)
    technical_interruption_count: int = Field(ge=0)
    unresolved_event_count: int = Field(ge=0)
    final_active_response: bool
    final_time_expired: bool
    violation_count: Literal[0] = 0
    fault_count: Literal[0] = 0
    blame_count: Literal[0] = 0
    sanction_count: Literal[0] = 0
    limitations: tuple[str, ...] = Field(min_length=1)
    status: Literal["complete", "warning", "failed"]
    integrity_sha256: Sha256


PHASE5_PROCEDURAL_STATE_CONTRACT_MODELS = (
    ProceduralStatePolicy,
    ProceduralEvent,
    ProceduralStateSnapshot,
    ProceduralStateRun,
    ProceduralStateReport,
)
