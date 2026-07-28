"""Bounded provider invocation and non-authoritative proposal normalization."""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path

from .context_window_contracts import (
    ContextWindowBundle,
    ContextWindowKind,
    UtteranceContextWindow,
)
from .discourse_providers import (
    DiscourseModelUnavailable,
    DiscourseProvider,
    DiscourseProviderError,
    DiscourseProviderTimeout,
    DiscourseProviderUnavailable,
    MalformedDiscourseProviderOutput,
)
from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase2_contracts import ConfidenceMeasure, ConfidenceOrigin
from .phase4_contracts import Utterance, UtteranceCorpus, UtteranceTextKind
from .phase5_contracts import (
    DiscourseActObservation,
    DiscourseAnalysisMethod,
    DiscourseAnalysisPolicy,
    DiscourseConfidence,
    DiscourseEvidenceSpan,
    DiscourseProviderCapability,
    DiscourseRelationTargetProposal,
    DiscourseReviewStatus,
    DiscourseTargetStatus,
    DiscourseTargetType,
)
from .phase5_provider_analysis_contracts import (
    BoundedDiscourseProviderRequest,
    DiscourseProviderFailure,
    ProviderActProposal,
    ProviderAnalysisResponse,
    ProviderContextItem,
    ProviderDiscourseReport,
    ProviderDiscourseRun,
)
from .phase5_provider_contracts import DiscourseProviderFailureKind


class ProviderDiscourseIntegrityError(RuntimeError):
    """Provider discourse evidence is malformed, stale, or incompatible."""


def _seal(model, payload: dict):
    provisional = model(**payload, integrity_sha256="0" * 64)
    return provisional.model_copy(
        update={
            "integrity_sha256": canonical_hash(
                provisional.model_copy(
                    update={"integrity_sha256": "0" * 64}
                )
            )
        }
    )


def _verify_seal(item, label: str) -> None:
    expected = _seal(
        type(item),
        item.model_dump(mode="python", exclude={"integrity_sha256"}),
    )
    if expected != item:
        raise ProviderDiscourseIntegrityError(f"{label} integrity is invalid")


def seal_provider_response(
    response: ProviderAnalysisResponse,
) -> ProviderAnalysisResponse:
    return _seal(
        ProviderAnalysisResponse,
        response.model_dump(mode="python", exclude={"integrity_sha256"}),
    )


def _display(utterance: Utterance):
    return next(
        item
        for item in utterance.text_views
        if item.kind == UtteranceTextKind.DISPLAY
    )


def _bounded_windows(
    corpus: UtteranceCorpus,
    bundle: ContextWindowBundle,
) -> dict[str, UtteranceContextWindow]:
    if bundle.utterance_corpus_id != corpus.corpus_id:
        raise ProviderDiscourseIntegrityError(
            "context bundle belongs to another utterance corpus"
        )
    windows = {
        item.target_utterance_id: item
        for item in bundle.windows
        if item.kind == ContextWindowKind.BOUNDED_TEMPORAL
    }
    expected = {item.utterance_id for item in corpus.utterances}
    if set(windows) != expected:
        raise ProviderDiscourseIntegrityError(
            "every utterance requires one bounded temporal context window"
        )
    return windows


def prepare_provider_request(
    corpus: UtteranceCorpus,
    bundle: ContextWindowBundle,
    window: UtteranceContextWindow,
    provider: DiscourseProvider,
    *,
    discourse_run_id: str,
    requested_at: datetime,
    policy: DiscourseAnalysisPolicy,
    deterministic_seed: int | None = None,
) -> BoundedDiscourseProviderRequest:
    utterances = {item.utterance_id: item for item in corpus.utterances}
    if (
        bundle.utterance_corpus_id != corpus.corpus_id
        or window.context_bundle_id != bundle.context_bundle_id
        or window.utterance_corpus_id != corpus.corpus_id
        or window.kind != ContextWindowKind.BOUNDED_TEMPORAL
    ):
        raise ProviderDiscourseIntegrityError(
            "provider request context lineage is incompatible"
        )
    if (
        len(window.members) > policy.maximum_context_utterances
        or window.token_estimate > policy.maximum_context_tokens
        or window.source_duration_microseconds
        > policy.maximum_context_duration_microseconds
    ):
        raise ProviderDiscourseIntegrityError(
            "Phase 4 context window exceeds provider policy budget"
        )
    items = []
    for position, member in enumerate(window.members):
        utterance = utterances.get(member.utterance_id)
        if utterance is None:
            raise ProviderDiscourseIntegrityError(
                "context window references an unknown utterance"
            )
        display = _display(utterance)
        items.append(
            ProviderContextItem(
                utterance_id=utterance.utterance_id,
                utterance_text_view_id=display.view_id,
                displayed_text=display.text,
                source_intervals=member.source_intervals,
                is_target=(
                    utterance.utterance_id == window.target_utterance_id
                ),
                order_position=position,
            )
        )
    configuration_hash = canonical_hash(
        {
            "operation": "discourse.provider_analyze",
            "phase4_utterance_corpus_sha256": canonical_hash(corpus),
            "context_window": window.model_dump(mode="json"),
            "provider": provider.capabilities.identity.model_dump(mode="json"),
            "policy": policy.model_dump(mode="json"),
            "deterministic_seed": deterministic_seed,
        }
    )
    return BoundedDiscourseProviderRequest(
        request_id=typed_id(
            "discourserequest",
            discourse_run_id,
            window.target_utterance_id,
            configuration_hash,
        ),
        requested_at=requested_at,
        discourse_run_id=discourse_run_id,
        phase4_utterance_corpus_id=corpus.corpus_id,
        phase4_utterance_corpus_sha256=canonical_hash(corpus),
        target_utterance_id=window.target_utterance_id,
        context_bundle_id=bundle.context_bundle_id,
        context_window_id=window.context_window_id,
        context_items=tuple(items),
        context_truncated=window.truncated,
        policy=policy,
        provider=provider.capabilities.identity,
        deterministic_seed=deterministic_seed,
        configuration_hash=configuration_hash,
    )


def _measure(
    value: float | None, basis: str
) -> ConfidenceMeasure:
    return ConfidenceMeasure(
        value=value,
        origin=(
            ConfidenceOrigin.PROVIDER_NATIVE
            if value is not None
            else ConfidenceOrigin.UNAVAILABLE
        ),
        basis=basis,
        calibrated=False,
    )


def _normalize_proposal(
    request: BoundedDiscourseProviderRequest,
    response: ProviderAnalysisResponse,
    proposal: ProviderActProposal,
    corpus: UtteranceCorpus,
    observation_ids: dict[str, str],
) -> DiscourseActObservation:
    utterances = {item.utterance_id: item for item in corpus.utterances}
    utterance = utterances[request.target_utterance_id]
    display = _display(utterance)
    spans = []
    for item in proposal.spans:
        if (
            item.end_text_offset > len(display.text)
            or display.text[item.start_text_offset:item.end_text_offset]
            != item.exact_displayed_text
        ):
            raise ProviderDiscourseIntegrityError(
                "provider evidence span does not reproduce target text"
            )
        spans.append(
            _seal(
                DiscourseEvidenceSpan,
                {
                    "span_id": typed_id(
                        "discoursespan",
                        request.request_id,
                        response.response_id,
                        proposal.provider_proposal_id,
                        item.proposal_span_id,
                    ),
                    "utterance_id": utterance.utterance_id,
                    "utterance_text_view_id": display.view_id,
                    "text_view_version": "phase4-display-1.0.0",
                    "start_text_offset": item.start_text_offset,
                    "end_text_offset": item.end_text_offset,
                    "transcript_word_ids": (),
                    "source_interval": utterance.source_intervals[0],
                    "exact_displayed_text": item.exact_displayed_text,
                    "role": item.role,
                    "confidence": _measure(
                        item.confidence,
                        "provider-native evidence-span confidence",
                    ),
                },
            )
        )
    span_ids = tuple(item.span_id for item in spans)
    targets = []
    context_ids = {item.utterance_id for item in request.context_items}
    for item in proposal.targets:
        if (
            item.target_status
            in {
                DiscourseTargetStatus.IDENTIFIED,
                DiscourseTargetStatus.PROBABLE,
            }
            and item.target_type == DiscourseTargetType.UTTERANCE
            and item.target_id not in context_ids
        ):
            raise ProviderDiscourseIntegrityError(
                "provider fabricated a target outside bounded context"
            )
        if (
            item.target_type == DiscourseTargetType.UTTERANCE
            and not set(item.alternative_target_ids).issubset(context_ids)
        ):
            raise ProviderDiscourseIntegrityError(
                "provider alternative target lies outside bounded context"
            )
        targets.append(
            DiscourseRelationTargetProposal(
                proposal_id=typed_id(
                    "discoursetarget",
                    request.request_id,
                    response.response_id,
                    item.provider_target_id,
                ),
                target_type=item.target_type,
                target_status=item.target_status,
                target_id=item.target_id,
                alternative_target_ids=item.alternative_target_ids,
                relation_type=item.relation_type,
                evidence_span_ids=span_ids,
                temporal_distance_microseconds=None,
                context_window_id=request.context_window_id,
                confidence=_measure(
                    item.confidence,
                    "provider-native relation-target confidence",
                ),
                basis=item.basis,
            )
        )
    act_measure = _measure(
        proposal.classification_confidence,
        "provider-native act-type confidence",
    )
    span_measure = _measure(
        (
            min(
                item.confidence
                for item in proposal.spans
                if item.confidence is not None
            )
            if any(item.confidence is not None for item in proposal.spans)
            else None
        ),
        "minimum available provider evidence-span confidence",
    )
    target_measure = _measure(
        (
            min(
                item.confidence
                for item in proposal.targets
                if item.confidence is not None
            )
            if any(item.confidence is not None for item in proposal.targets)
            else None
        ),
        "minimum available provider relation-target confidence",
    )
    unavailable = _measure(
        None, "Candidate selection occurs in a later Phase 5 stage."
    )
    confidence = DiscourseConfidence(
        act_type=act_measure,
        evidence_span=span_measure,
        target_relation=target_measure,
        selection=unavailable,
        question_type=(
            act_measure
            if proposal.act_family.value == "question"
            else None
        ),
        answer_link=(
            target_measure
            if proposal.act_family.value == "answer"
            else None
        ),
        quotation_use=(
            act_measure
            if proposal.act_family.value == "quotation_and_attribution"
            else None
        ),
        procedural_state=(
            act_measure
            if proposal.act_family.value == "procedural"
            else None
        ),
        derivation_method="normalized provider-native proposal",
        source_features=proposal.evidence_for,
        limitations=(
            "Provider confidence is not comparable across providers without "
            "calibration.",
            "The observation is non-authoritative until consolidation.",
        ),
    )
    alternatives = tuple(
        observation_id
        for provider_id, observation_id in observation_ids.items()
        if provider_id != proposal.provider_proposal_id
        and next(
            item
            for item in response.proposals
            if item.provider_proposal_id == provider_id
        ).alternative_group
        == proposal.alternative_group
        and proposal.alternative_group is not None
    )
    return _seal(
        DiscourseActObservation,
        {
            "observation_id": observation_ids[
                proposal.provider_proposal_id
            ],
            "discourse_run_id": request.discourse_run_id,
            "phase4_utterance_corpus_id": (
                request.phase4_utterance_corpus_id
            ),
            "utterance_id": request.target_utterance_id,
            "evidence_spans": tuple(spans),
            "act_family": proposal.act_family,
            "act_type": proposal.act_type,
            "act_modifiers": proposal.modifiers,
            "proposed_targets": tuple(targets),
            "confidence": confidence,
            "analysis_method": DiscourseAnalysisMethod.PROVIDER_PROPOSAL,
            "provider": response.provider,
            "raw_evidence_sha256": response.raw_output_sha256,
            "alternative_observation_ids": alternatives,
            "contrary_evidence": proposal.contrary_evidence,
            "context_window_id": request.context_window_id,
            "review_status": DiscourseReviewStatus.UNREVIEWED,
            "created_at": response.completed_at,
        },
    )


def normalize_provider_response(
    request: BoundedDiscourseProviderRequest,
    response: ProviderAnalysisResponse,
    corpus: UtteranceCorpus,
) -> tuple[DiscourseActObservation, ...]:
    if response.request_id != request.request_id:
        raise ProviderDiscourseIntegrityError(
            "provider response references another request"
        )
    if response.provider != request.provider:
        raise ProviderDiscourseIntegrityError(
            "provider response identity differs from request"
        )
    _verify_seal(response, "provider response")
    if len(response.proposals) > request.policy.maximum_candidates_per_span:
        raise ProviderDiscourseIntegrityError(
            "provider response exceeds candidate budget"
        )
    observation_ids = {
        item.provider_proposal_id: typed_id(
            "discourseobs",
            request.request_id,
            response.response_id,
            item.provider_proposal_id,
        )
        for item in response.proposals
    }
    return tuple(
        _normalize_proposal(
            request, response, item, corpus, observation_ids
        )
        for item in response.proposals
    )


def _failure_kind(exc: Exception) -> DiscourseProviderFailureKind:
    if isinstance(exc, DiscourseProviderTimeout):
        return DiscourseProviderFailureKind.TIMEOUT
    if isinstance(exc, DiscourseModelUnavailable):
        return DiscourseProviderFailureKind.MODEL_UNAVAILABLE
    if isinstance(exc, DiscourseProviderUnavailable):
        return DiscourseProviderFailureKind.PROVIDER_UNAVAILABLE
    if isinstance(exc, MalformedDiscourseProviderOutput):
        return DiscourseProviderFailureKind.MALFORMED_STRUCTURED_OUTPUT
    if isinstance(exc, ProviderDiscourseIntegrityError):
        return DiscourseProviderFailureKind.VALIDATION_FAILURE
    return DiscourseProviderFailureKind.INTERNAL_FAILURE


def run_provider_analysis(
    corpus: UtteranceCorpus,
    context_bundle: ContextWindowBundle,
    provider: DiscourseProvider,
    *,
    created_at: datetime,
    policy: DiscourseAnalysisPolicy | None = None,
    deterministic_seed: int | None = None,
) -> tuple[ProviderDiscourseRun, ProviderDiscourseReport]:
    """Invoke a provider with exact bounded contexts and normalize proposals."""
    policy = policy or DiscourseAnalysisPolicy(
        context_window_policy_version=context_bundle.policy.policy_version
    )
    capabilities = provider.capabilities
    required = {
        DiscourseProviderCapability.MULTI_LABEL_CLASSIFICATION,
        DiscourseProviderCapability.EVIDENCE_SPANS,
        DiscourseProviderCapability.STRUCTURED_OUTPUT,
    }
    if not required.issubset(capabilities.capabilities):
        raise ProviderDiscourseIntegrityError(
            "provider lacks required structured discourse capabilities"
        )
    windows = _bounded_windows(corpus, context_bundle)
    configuration_hash = canonical_hash(
        {
            "operation": "discourse.provider_run",
            "phase4_utterance_corpus_sha256": canonical_hash(corpus),
            "context_bundle_sha256": canonical_hash(context_bundle),
            "provider": capabilities.model_dump(mode="json"),
            "policy": policy.model_dump(mode="json"),
            "deterministic_seed": deterministic_seed,
        }
    )
    discourse_run_id = typed_id(
        "discourserun",
        corpus.corpus_id,
        context_bundle.context_bundle_id,
        configuration_hash,
    )
    requests = []
    responses = []
    failures = []
    observations = []
    for utterance in corpus.utterances:
        request = prepare_provider_request(
            corpus,
            context_bundle,
            windows[utterance.utterance_id],
            provider,
            discourse_run_id=discourse_run_id,
            requested_at=created_at,
            policy=policy,
            deterministic_seed=deterministic_seed,
        )
        requests.append(request)
        for attempt in range(1, policy.maximum_retries + 2):
            try:
                response = provider.analyze(request)
                if not isinstance(response, ProviderAnalysisResponse):
                    raise MalformedDiscourseProviderOutput(
                        "provider returned an unsupported response type"
                    )
                normalized = normalize_provider_response(
                    request, response, corpus
                )
                responses.append(response)
                observations.extend(normalized)
                break
            except (
                DiscourseProviderError,
                ProviderDiscourseIntegrityError,
            ) as exc:
                retryable = (
                    isinstance(exc, DiscourseProviderTimeout)
                    and attempt <= policy.maximum_retries
                )
                failures.append(
                    DiscourseProviderFailure(
                        failure_id=typed_id(
                            "discoursefailure",
                            request.request_id,
                            attempt,
                            _failure_kind(exc).value,
                            str(exc),
                        ),
                        request_id=request.request_id,
                        provider=capabilities.identity,
                        kind=_failure_kind(exc),
                        attempt=attempt,
                        retryable=retryable,
                        message=str(exc),
                        occurred_at=created_at,
                    )
                )
                if not retryable:
                    break
    run = _seal(
        ProviderDiscourseRun,
        {
            "provider_run_id": typed_id(
                "discourseproviderrun",
                discourse_run_id,
                tuple(item.request_id for item in requests),
                tuple(item.response_id for item in responses),
                tuple(item.failure_id for item in failures),
            ),
            "discourse_run_id": discourse_run_id,
            "phase4_utterance_corpus_id": corpus.corpus_id,
            "phase4_utterance_corpus_sha256": canonical_hash(corpus),
            "context_bundle_id": context_bundle.context_bundle_id,
            "context_bundle_sha256": canonical_hash(context_bundle),
            "provider": capabilities.identity,
            "policy": policy,
            "configuration_hash": configuration_hash,
            "requests": tuple(requests),
            "responses": tuple(responses),
            "failures": tuple(failures),
            "observations": tuple(observations),
            "created_at": created_at,
            "complete": True,
        },
    )
    failed_requests = {
        item.request_id
        for item in failures
        if not item.retryable
    }
    report = _seal(
        ProviderDiscourseReport,
        {
            "report_id": typed_id(
                "discourseproviderreport", run.provider_run_id
            ),
            "provider_run_id": run.provider_run_id,
            "generated_at": created_at,
            "request_count": len(requests),
            "response_count": len(responses),
            "proposal_count": sum(
                len(item.proposals) for item in responses
            ),
            "observation_count": len(observations),
            "failed_request_count": len(failed_requests),
            "retry_count": sum(
                item.kind == DiscourseProviderFailureKind.TIMEOUT
                and item.retryable
                for item in failures
            ),
            "truncated_context_count": sum(
                item.context_truncated for item in requests
            ),
            "unavailable_confidence_count": sum(
                item.confidence.act_type.value is None
                for item in observations
            ),
            "limitations": (
                "Provider proposals are non-authoritative observations.",
                "Provider confidence is not cross-provider comparable without "
                "calibration.",
                "Provider failure preserves an unclassified outcome.",
            ),
            "status": "warning" if failed_requests else "complete",
        },
    )
    return run, report


def validate_provider_analysis(
    run: ProviderDiscourseRun,
    report: ProviderDiscourseReport,
    corpus: UtteranceCorpus,
    context_bundle: ContextWindowBundle,
) -> None:
    _verify_seal(run, "provider discourse run")
    _verify_seal(report, "provider discourse report")
    if (
        run.phase4_utterance_corpus_id != corpus.corpus_id
        or run.phase4_utterance_corpus_sha256 != canonical_hash(corpus)
        or run.context_bundle_id != context_bundle.context_bundle_id
        or run.context_bundle_sha256 != canonical_hash(context_bundle)
    ):
        raise ProviderDiscourseIntegrityError(
            "provider run source lineage is incompatible"
        )
    if (
        report.provider_run_id != run.provider_run_id
        or report.request_count != len(run.requests)
        or report.response_count != len(run.responses)
        or report.observation_count != len(run.observations)
    ):
        raise ProviderDiscourseIntegrityError(
            "provider discourse report is stale"
        )
    windows = _bounded_windows(corpus, context_bundle)
    class _IdentityProvider:
        capabilities = type(
            "_Capabilities",
            (),
            {"identity": run.provider},
        )()

    provider = _IdentityProvider()
    for request in run.requests:
        expected = prepare_provider_request(
            corpus,
            context_bundle,
            windows[request.target_utterance_id],
            provider,  # type: ignore[arg-type]
            discourse_run_id=run.discourse_run_id,
            requested_at=request.requested_at,
            policy=run.policy,
            deterministic_seed=request.deterministic_seed,
        )
        if expected != request:
            raise ProviderDiscourseIntegrityError(
                "provider request no longer matches bounded context"
            )
    by_request = {item.request_id: item for item in run.requests}
    normalized = tuple(
        observation
        for response in run.responses
        for observation in normalize_provider_response(
            by_request[response.request_id], response, corpus
        )
    )
    if normalized != run.observations:
        raise ProviderDiscourseIntegrityError(
            "normalized provider observations are stale"
        )


def persist_provider_analysis(
    run: ProviderDiscourseRun,
    report: ProviderDiscourseReport,
    corpus: UtteranceCorpus,
    context_bundle: ContextWindowBundle,
    destination: Path,
) -> tuple[Path, Path, bool]:
    validate_provider_analysis(run, report, corpus, context_bundle)
    root = destination.expanduser().resolve()
    run_path = root / "provider-discourse-run.json"
    report_path = root / "provider-discourse-report.json"
    root.mkdir(parents=True, exist_ok=True)
    existing = (run_path.exists(), report_path.exists())
    if any(existing) and not all(existing):
        raise ProviderDiscourseIntegrityError(
            "persisted provider discourse pair is incomplete"
        )
    if all(existing):
        stored = load_provider_analysis(root)
        if stored != (run, report):
            raise ProviderDiscourseIntegrityError(
                "persisted provider discourse conflicts"
            )
        return run_path, report_path, True
    for path, item in ((run_path, run), (report_path, report)):
        temporary = path.with_name(
            f"{path.name}.partial-{uuid.uuid4().hex}"
        )
        temporary.write_bytes(canonical_bytes(item))
        os.replace(temporary, path)
    return run_path, report_path, False


def load_provider_analysis(
    root: Path,
) -> tuple[ProviderDiscourseRun, ProviderDiscourseReport]:
    resolved = root.expanduser().resolve(strict=True)
    run = load_contract(
        (resolved / "provider-discourse-run.json").read_bytes(),
        ProviderDiscourseRun,
    )
    report = load_contract(
        (resolved / "provider-discourse-report.json").read_bytes(),
        ProviderDiscourseReport,
    )
    _verify_seal(run, "provider discourse run")
    _verify_seal(report, "provider discourse report")
    return run, report
