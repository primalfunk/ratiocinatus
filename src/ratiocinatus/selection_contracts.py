"""Versioned deterministic stream-selection contracts."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract
from .phase1_contracts import StreamKind

STREAM_SELECTION_POLICY_VERSION = "1.0.0"


class CandidateDisposition(str, Enum):
    SELECTED = "selected"
    REJECTED = "rejected"
    DISQUALIFIED = "disqualified"


class StreamSelectionPolicy(Contract):
    policy_version: Literal["1.0.0"] = STREAM_SELECTION_POLICY_VERSION
    explicit_audio_stream_index: int | None = Field(default=None, ge=0)
    explicit_video_stream_index: int | None = Field(default=None, ge=0)
    preferred_languages: tuple[str, ...] = ()
    preferred_audio_layouts: tuple[str, ...] = ()
    require_audio: bool = True
    allow_audio_only: bool = True


class StreamCandidateAssessment(Contract):
    stream_id: str = Field(pattern=r"^stream_[a-f0-9]{32}$")
    stream_index: int = Field(ge=0)
    stream_type: StreamKind
    eligible: bool
    decode_supported: bool
    attached_picture: bool
    default: bool
    language_match: bool
    layout_match: bool
    explicit_index_match: bool
    rank: tuple[int, ...]
    rejection_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    final_disposition: CandidateDisposition


class StreamSelectionDecision(Contract):
    media_type: Literal["audio", "video"]
    policy_version: Literal["1.0.0"]
    candidates: tuple[StreamCandidateAssessment, ...]
    selected_stream_id: str | None = Field(
        default=None, pattern=r"^stream_[a-f0-9]{32}$"
    )
    selected_stream_index: int | None = Field(default=None, ge=0)
    valid: bool
    deterministic: bool = True
    explanation: str

    @model_validator(mode="after")
    def selected_fields_are_consistent(self) -> "StreamSelectionDecision":
        selected = [
            item
            for item in self.candidates
            if item.final_disposition == CandidateDisposition.SELECTED
        ]
        if self.selected_stream_id is None:
            if self.selected_stream_index is not None or selected:
                raise ValueError("an unselected decision cannot contain selection data")
        elif (
            self.selected_stream_index is None
            or len(selected) != 1
            or selected[0].stream_id != self.selected_stream_id
            or selected[0].stream_index != self.selected_stream_index
        ):
            raise ValueError("selected decision must identify one selected candidate")
        return self


class StreamSelectionResult(Contract):
    policy: StreamSelectionPolicy
    audio: StreamSelectionDecision
    video: StreamSelectionDecision
    valid: bool

    @model_validator(mode="after")
    def validity_matches_decisions(self) -> "StreamSelectionResult":
        if self.valid != (self.audio.valid and self.video.valid):
            raise ValueError("result validity must match decision validity")
        return self


SELECTION_CONTRACT_MODELS = (
    StreamSelectionPolicy,
    StreamCandidateAssessment,
    StreamSelectionDecision,
    StreamSelectionResult,
)
