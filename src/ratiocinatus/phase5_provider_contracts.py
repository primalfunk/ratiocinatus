"""Typed provider-boundary contracts for Phase 5 discourse proposals."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract, Sha256
from .phase5_contracts import (
    PHASE5_FORMAT_VERSION,
    DiscourseActObservation,
    DiscourseAnalysisPolicy,
    DiscourseProviderIdentity,
)


class DiscourseProviderFailureKind(str, Enum):
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    MODEL_UNAVAILABLE = "model_unavailable"
    TIMEOUT = "timeout"
    MALFORMED_STRUCTURED_OUTPUT = "malformed_structured_output"
    UNSUPPORTED_INPUT = "unsupported_input"
    VALIDATION_FAILURE = "validation_failure"
    INTERNAL_FAILURE = "internal_failure"


class DiscourseProviderRequest(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    request_id: str = Field(pattern=r"^discourserequest_[a-f0-9]{32}$")
    requested_at: datetime
    phase4_utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    utterance_id: str = Field(pattern=r"^utterance_[a-f0-9]{32}$")
    utterance_text_view_id: str = Field(
        pattern=r"^utterancetext_[a-f0-9]{32}$"
    )
    displayed_text: str
    context_window_id: str = Field(
        pattern=r"^contextwindow_[a-f0-9]{32}$"
    )
    context_utterance_ids: tuple[str, ...]
    policy: DiscourseAnalysisPolicy
    provider: DiscourseProviderIdentity
    deterministic_seed: int | None = None
    configuration_hash: Sha256

    @model_validator(mode="after")
    def context_is_bounded(self) -> "DiscourseProviderRequest":
        if (
            len(self.context_utterance_ids)
            > self.policy.maximum_context_utterances
        ):
            raise ValueError("provider request exceeds context utterance budget")
        if len(self.context_utterance_ids) != len(
            set(self.context_utterance_ids)
        ):
            raise ValueError("provider context utterance ids must be unique")
        return self


class DiscourseProviderResponse(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    response_id: str = Field(pattern=r"^discourseresponse_[a-f0-9]{32}$")
    request_id: str = Field(pattern=r"^discourserequest_[a-f0-9]{32}$")
    provider: DiscourseProviderIdentity
    observations: tuple[DiscourseActObservation, ...]
    raw_output_retained: bool
    raw_output_sha256: Sha256 | None = None
    failure_kind: DiscourseProviderFailureKind | None = None
    failure_message: str | None = None
    completed_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def response_state_is_coherent(self) -> "DiscourseProviderResponse":
        failed = self.failure_kind is not None
        if failed != (self.failure_message is not None):
            raise ValueError("provider failure requires kind and message")
        if failed and self.observations:
            raise ValueError("failed provider response cannot claim observations")
        if self.raw_output_retained != (self.raw_output_sha256 is not None):
            raise ValueError("raw-output retention and digest disagree")
        if any(item.provider != self.provider for item in self.observations):
            raise ValueError("provider response observation provenance differs")
        return self


PHASE5_PROVIDER_CONTRACT_MODELS = (
    DiscourseProviderRequest,
    DiscourseProviderResponse,
)
