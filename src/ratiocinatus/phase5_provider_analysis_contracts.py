"""Bounded-context provider proposal and normalized evidence contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from .addressing_contracts import MediaInterval, TimeDomain
from .contracts import Contract, Sha256
from .phase5_contracts import (
    PHASE5_FORMAT_VERSION,
    DiscourseActFamily,
    DiscourseActObservation,
    DiscourseActType,
    DiscourseAnalysisPolicy,
    DiscourseEvidenceSpanRole,
    DiscourseProviderIdentity,
    DiscourseRelationType,
    DiscourseTargetStatus,
    DiscourseTargetType,
)
from .phase5_provider_contracts import DiscourseProviderFailureKind


class ProviderContextItem(Contract):
    utterance_id: str = Field(pattern=r"^utterance_[a-f0-9]{32}$")
    utterance_text_view_id: str = Field(
        pattern=r"^utterancetext_[a-f0-9]{32}$"
    )
    displayed_text: str
    source_intervals: tuple[MediaInterval, ...] = Field(min_length=1)
    is_target: bool
    order_position: int = Field(ge=0)

    @model_validator(mode="after")
    def source_time_is_valid(self) -> "ProviderContextItem":
        if any(
            item.domain != TimeDomain.SOURCE_MEDIA
            for item in self.source_intervals
        ):
            raise ValueError("provider context requires source-media intervals")
        return self


class ProviderSpanProposal(Contract):
    proposal_span_id: str = Field(
        pattern=r"^providerspan_[a-f0-9]{32}$"
    )
    start_text_offset: int = Field(ge=0)
    end_text_offset: int = Field(gt=0)
    exact_displayed_text: str = Field(min_length=1)
    role: DiscourseEvidenceSpanRole
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def offsets_are_ordered(self) -> "ProviderSpanProposal":
        if self.end_text_offset <= self.start_text_offset:
            raise ValueError("provider span offsets must be ordered")
        return self


class ProviderTargetProposal(Contract):
    provider_target_id: str = Field(
        pattern=r"^providertarget_[a-f0-9]{32}$"
    )
    target_type: DiscourseTargetType
    target_status: DiscourseTargetStatus
    target_id: str | None = None
    alternative_target_ids: tuple[str, ...] = ()
    relation_type: DiscourseRelationType
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    basis: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def target_state_is_coherent(self) -> "ProviderTargetProposal":
        if self.target_status in {
            DiscourseTargetStatus.IDENTIFIED,
            DiscourseTargetStatus.PROBABLE,
        } and self.target_id is None:
            raise ValueError("identified provider target requires an id")
        if self.target_status in {
            DiscourseTargetStatus.IMPLICIT,
            DiscourseTargetStatus.UNRESOLVED,
        } and self.target_id is not None:
            raise ValueError("unresolved provider target cannot force an id")
        if (
            self.target_status == DiscourseTargetStatus.MULTIPLE_CANDIDATES
            and len(self.alternative_target_ids) < 2
        ):
            raise ValueError("multiple provider targets require candidates")
        if len(self.alternative_target_ids) != len(
            set(self.alternative_target_ids)
        ):
            raise ValueError("provider alternative targets must be unique")
        return self


class ProviderActProposal(Contract):
    provider_proposal_id: str = Field(
        pattern=r"^providerproposal_[a-f0-9]{32}$"
    )
    act_family: DiscourseActFamily
    act_type: DiscourseActType
    spans: tuple[ProviderSpanProposal, ...] = Field(min_length=1)
    targets: tuple[ProviderTargetProposal, ...] = ()
    classification_confidence: float | None = Field(
        default=None, ge=0.0, le=1.0
    )
    rank: int = Field(ge=1)
    alternative_group: str | None = Field(default=None, min_length=1)
    evidence_for: tuple[str, ...] = Field(min_length=1)
    contrary_evidence: tuple[str, ...] = ()
    modifiers: tuple[str, ...] = ()

    @model_validator(mode="after")
    def proposal_is_coherent(self) -> "ProviderActProposal":
        span_ids = [item.proposal_span_id for item in self.spans]
        target_ids = [item.provider_target_id for item in self.targets]
        if len(span_ids) != len(set(span_ids)):
            raise ValueError("provider proposal spans must be unique")
        if len(target_ids) != len(set(target_ids)):
            raise ValueError("provider proposal targets must be unique")
        return self


class BoundedDiscourseProviderRequest(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    request_id: str = Field(pattern=r"^discourserequest_[a-f0-9]{32}$")
    requested_at: datetime
    discourse_run_id: str = Field(pattern=r"^discourserun_[a-f0-9]{32}$")
    phase4_utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    phase4_utterance_corpus_sha256: Sha256
    target_utterance_id: str = Field(pattern=r"^utterance_[a-f0-9]{32}$")
    context_bundle_id: str = Field(pattern=r"^contextbundle_[a-f0-9]{32}$")
    context_window_id: str = Field(
        pattern=r"^contextwindow_[a-f0-9]{32}$"
    )
    context_window_kind: Literal["bounded_temporal_window"] = (
        "bounded_temporal_window"
    )
    context_items: tuple[ProviderContextItem, ...] = Field(min_length=1)
    context_truncated: bool
    policy: DiscourseAnalysisPolicy
    provider: DiscourseProviderIdentity
    deterministic_seed: int | None = None
    configuration_hash: Sha256

    @model_validator(mode="after")
    def context_is_bounded_and_ordered(
        self,
    ) -> "BoundedDiscourseProviderRequest":
        if len(self.context_items) > self.policy.maximum_context_utterances:
            raise ValueError("provider request exceeds context item budget")
        positions = [item.order_position for item in self.context_items]
        if positions != list(range(len(self.context_items))):
            raise ValueError("provider context positions must be contiguous")
        ids = [item.utterance_id for item in self.context_items]
        if len(ids) != len(set(ids)):
            raise ValueError("provider context cannot duplicate utterances")
        targets = [item for item in self.context_items if item.is_target]
        if (
            len(targets) != 1
            or targets[0].utterance_id != self.target_utterance_id
        ):
            raise ValueError("provider context must contain its target once")
        return self


class ProviderAnalysisResponse(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    response_id: str = Field(pattern=r"^discourseresponse_[a-f0-9]{32}$")
    request_id: str = Field(pattern=r"^discourserequest_[a-f0-9]{32}$")
    provider: DiscourseProviderIdentity
    proposals: tuple[ProviderActProposal, ...]
    raw_output_sha256: Sha256
    raw_output_retained: bool
    completed_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def proposals_are_unique(self) -> "ProviderAnalysisResponse":
        ids = [item.provider_proposal_id for item in self.proposals]
        if len(ids) != len(set(ids)):
            raise ValueError("provider proposal ids must be unique")
        ranks = [item.rank for item in self.proposals]
        if len(ranks) != len(set(ranks)):
            raise ValueError("provider proposal ranks must be unique")
        return self


class DiscourseProviderFailure(Contract):
    failure_id: str = Field(pattern=r"^discoursefailure_[a-f0-9]{32}$")
    request_id: str = Field(pattern=r"^discourserequest_[a-f0-9]{32}$")
    provider: DiscourseProviderIdentity
    kind: DiscourseProviderFailureKind
    attempt: int = Field(ge=1)
    retryable: bool
    message: str = Field(min_length=1)
    occurred_at: datetime


class ProviderDiscourseRun(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    provider_run_id: str = Field(
        pattern=r"^discourseproviderrun_[a-f0-9]{32}$"
    )
    discourse_run_id: str = Field(pattern=r"^discourserun_[a-f0-9]{32}$")
    phase4_utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    phase4_utterance_corpus_sha256: Sha256
    context_bundle_id: str = Field(pattern=r"^contextbundle_[a-f0-9]{32}$")
    context_bundle_sha256: Sha256
    provider: DiscourseProviderIdentity
    policy: DiscourseAnalysisPolicy
    configuration_hash: Sha256
    requests: tuple[BoundedDiscourseProviderRequest, ...]
    responses: tuple[ProviderAnalysisResponse, ...]
    failures: tuple[DiscourseProviderFailure, ...]
    observations: tuple[DiscourseActObservation, ...]
    created_at: datetime
    complete: bool
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def run_lineage_is_coherent(self) -> "ProviderDiscourseRun":
        request_ids = [item.request_id for item in self.requests]
        response_ids = [item.response_id for item in self.responses]
        observation_ids = [item.observation_id for item in self.observations]
        failure_ids = [item.failure_id for item in self.failures]
        for values in (
            request_ids, response_ids, observation_ids, failure_ids
        ):
            if len(values) != len(set(values)):
                raise ValueError("provider run child ids must be unique")
        known_requests = set(request_ids)
        if any(item.request_id not in known_requests for item in self.responses):
            raise ValueError("provider response references unknown request")
        if any(item.request_id not in known_requests for item in self.failures):
            raise ValueError("provider failure references unknown request")
        if any(item.provider != self.provider for item in self.responses):
            raise ValueError("provider response identity changed within run")
        if any(item.provider != self.provider for item in self.failures):
            raise ValueError("provider failure identity changed within run")
        if any(
            item.discourse_run_id != self.discourse_run_id
            or item.phase4_utterance_corpus_id
            != self.phase4_utterance_corpus_id
            or item.provider != self.provider
            for item in self.observations
        ):
            raise ValueError("normalized provider observation lineage differs")
        return self


class ProviderDiscourseReport(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    report_id: str = Field(
        pattern=r"^discourseproviderreport_[a-f0-9]{32}$"
    )
    provider_run_id: str = Field(
        pattern=r"^discourseproviderrun_[a-f0-9]{32}$"
    )
    generated_at: datetime
    request_count: int = Field(ge=0)
    response_count: int = Field(ge=0)
    proposal_count: int = Field(ge=0)
    observation_count: int = Field(ge=0)
    failed_request_count: int = Field(ge=0)
    retry_count: int = Field(ge=0)
    truncated_context_count: int = Field(ge=0)
    unavailable_confidence_count: int = Field(ge=0)
    limitations: tuple[str, ...] = Field(min_length=1)
    status: Literal["complete", "warning", "failed"]
    integrity_sha256: Sha256


PHASE5_PROVIDER_ANALYSIS_CONTRACT_MODELS = (
    ProviderContextItem,
    ProviderSpanProposal,
    ProviderTargetProposal,
    ProviderActProposal,
    BoundedDiscourseProviderRequest,
    ProviderAnalysisResponse,
    DiscourseProviderFailure,
    ProviderDiscourseRun,
    ProviderDiscourseReport,
)
