from pathlib import Path

import pytest

from ratiocinatus.cli import main
from ratiocinatus.context_window_contracts import (
    ContextInclusionReason,
    ContextWindowBundle,
    ContextWindowKind,
    ContextWindowMember,
    ContextWindowPolicy,
    UtteranceContextWindow,
)
from ratiocinatus.discourse_provider_analysis import (
    ProviderDiscourseIntegrityError,
    load_provider_analysis,
    persist_provider_analysis,
    run_provider_analysis,
    seal_provider_response,
    validate_provider_analysis,
)
from ratiocinatus.discourse_providers import (
    DiscourseProvider,
    DiscourseProviderTimeout,
    UnconfiguredDiscourseProvider,
)
from ratiocinatus.kernel import canonical_hash, typed_id
from ratiocinatus.phase4_contracts import UtteranceTextKind
from ratiocinatus.phase5_contracts import (
    DiscourseActFamily,
    DiscourseActType,
    DiscourseEvidenceSpanRole,
    DiscourseProviderCapabilities,
    DiscourseProviderCapability,
    DiscourseProviderIdentity,
)
from ratiocinatus.phase5_provider_analysis_contracts import (
    ProviderActProposal,
    ProviderAnalysisResponse,
    ProviderSpanProposal,
)

from test_phase5_deterministic_baseline import _with_texts
from test_phase5_foundation import NOW


def _context_bundle(corpus) -> ContextWindowBundle:
    bundle_id = "contextbundle_" + "1" * 32
    policy = ContextWindowPolicy()
    windows = []
    for target_index, target in enumerate(corpus.utterances):
        for kind_index, kind in enumerate(ContextWindowKind):
            members = []
            for position, utterance in enumerate(corpus.utterances):
                members.append(
                    ContextWindowMember(
                        member_id=typed_id(
                            "contextmember",
                            target.utterance_id,
                            kind.value,
                            utterance.utterance_id,
                        ),
                        utterance_id=utterance.utterance_id,
                        order_position=position,
                        corpus_sequence_position=position,
                        temporal_group_id=(
                            "temporalgroup_"
                            + f"{target_index * 100 + kind_index * 10 + position + 1:032x}"
                        ),
                        temporal_lane=0,
                        source_intervals=utterance.source_intervals,
                        normalized_audio_intervals=(
                            utterance.normalized_audio_intervals
                        ),
                        inclusion_reasons=(
                            ContextInclusionReason.TARGET
                            if utterance.utterance_id == target.utterance_id
                            else ContextInclusionReason.TEMPORAL_PROXIMITY,
                        ),
                        character_count=len(
                            next(
                                view.text
                                for view in utterance.text_views
                                if view.kind == UtteranceTextKind.DISPLAY
                            )
                        ),
                        token_estimate=8,
                        evidence_references=(utterance.utterance_id,),
                        integrity_sha256="1" * 64,
                    )
                )
            windows.append(
                UtteranceContextWindow(
                    context_window_id=typed_id(
                        "contextwindow",
                        bundle_id,
                        target.utterance_id,
                        kind.value,
                    ),
                    context_bundle_id=bundle_id,
                    utterance_corpus_id=corpus.corpus_id,
                    transcript_view_bundle_id=(
                        "utteranceviewbundle_" + "2" * 32
                    ),
                    target_utterance_id=target.utterance_id,
                    kind=kind,
                    policy=policy,
                    members=tuple(members),
                    source_intervals=tuple(
                        interval
                        for utterance in corpus.utterances
                        for interval in utterance.source_intervals
                    ),
                    character_count=sum(
                        item.character_count for item in members
                    ),
                    token_estimate=sum(item.token_estimate for item in members),
                    source_duration_microseconds=3_000_000,
                    structurally_available=True,
                    truncated=False,
                    complete_exchange_considered=True,
                    ordering_basis="controlled chronological fixture",
                    created_at=NOW,
                    integrity_sha256="1" * 64,
                )
            )
    return ContextWindowBundle(
        context_bundle_id=bundle_id,
        utterance_corpus_id=corpus.corpus_id,
        utterance_run_id=corpus.run_id,
        utterance_relation_run_id="utterancerelations_" + "3" * 32,
        quotation_run_id="quotationrun_" + "4" * 32,
        transcript_view_bundle_id="utteranceviewbundle_" + "2" * 32,
        policy=policy,
        configuration_hash="1" * 64,
        windows=tuple(windows),
        created_at=NOW,
        integrity_sha256="1" * 64,
    )


class ControlledProvider(DiscourseProvider):
    def __init__(self, *, timeout_once=False, malformed_span=False):
        self.timeout_once = timeout_once
        self.malformed_span = malformed_span
        self.calls = 0
        self._identity = DiscourseProviderIdentity(
            provider_id="controlled.discourse",
            display_name="Controlled discourse proposal provider",
            provider_version="1.0.0",
            model_id="controlled-fixture",
            model_version="1",
            model_fingerprint="2" * 64,
            runtime_fingerprint="3" * 64,
            local=True,
        )

    @property
    def capabilities(self):
        return DiscourseProviderCapabilities(
            identity=self._identity,
            capabilities=(
                DiscourseProviderCapability.MULTI_LABEL_CLASSIFICATION,
                DiscourseProviderCapability.EVIDENCE_SPANS,
                DiscourseProviderCapability.RELATION_TARGETS,
                DiscourseProviderCapability.ALTERNATIVES,
                DiscourseProviderCapability.STRUCTURED_OUTPUT,
                DiscourseProviderCapability.DETERMINISTIC_SEED,
            ),
            available=True,
            deterministic=True,
            limitations=("Controlled fixture only.",),
        )

    def analyze(self, request):
        self.calls += 1
        if self.timeout_once and self.calls == 1:
            raise DiscourseProviderTimeout("controlled first-attempt timeout")
        target = next(item for item in request.context_items if item.is_target)
        text = target.displayed_text
        if text.startswith("Yes"):
            specs = (
                (
                    DiscourseActFamily.ANSWER,
                    DiscourseActType.AFFIRMATIVE_ANSWER,
                    0,
                    3,
                ),
                (
                    DiscourseActFamily.QUALIFICATION,
                    DiscourseActType.SCOPE_QUALIFICATION,
                    text.index("only"),
                    text.index("only") + 4,
                ),
            )
        else:
            specs = (
                (
                    DiscourseActFamily.QUESTION,
                    DiscourseActType.INFORMATION_QUESTION,
                    0,
                    len(text),
                ),
            )
        proposals = []
        for rank, (family, act_type, start, end) in enumerate(specs, start=1):
            if self.malformed_span:
                end = len(text) + 10
            proposals.append(
                ProviderActProposal(
                    provider_proposal_id=typed_id(
                        "providerproposal",
                        request.request_id,
                        rank,
                    ),
                    act_family=family,
                    act_type=act_type,
                    spans=(
                        ProviderSpanProposal(
                            proposal_span_id=typed_id(
                                "providerspan", request.request_id, rank
                            ),
                            start_text_offset=start,
                            end_text_offset=end,
                            exact_displayed_text=(
                                text[start:end]
                                if end <= len(text)
                                else "fabricated"
                            ),
                            role=DiscourseEvidenceSpanRole.ACT_CONTENT,
                            confidence=0.8,
                        ),
                    ),
                    classification_confidence=0.85,
                    rank=rank,
                    evidence_for=("controlled structured proposal",),
                )
            )
        raw_hash = canonical_hash(
            tuple(item.model_dump(mode="json") for item in proposals)
        )
        provisional = ProviderAnalysisResponse(
            response_id=typed_id(
                "discourseresponse", request.request_id, raw_hash
            ),
            request_id=request.request_id,
            provider=self._identity,
            proposals=tuple(proposals),
            raw_output_sha256=raw_hash,
            raw_output_retained=True,
            completed_at=NOW,
            integrity_sha256="0" * 64,
        )
        return seal_provider_response(provisional)


def test_provider_analysis_uses_exact_bounded_context_and_normalizes():
    corpus = _with_texts(
        "What time is the hearing?",
        "Yes, but only after 2022.",
    )
    bundle = _context_bundle(corpus)
    provider = ControlledProvider()
    before = corpus.model_dump_json()
    run, report = run_provider_analysis(
        corpus,
        bundle,
        provider,
        created_at=NOW,
        deterministic_seed=7,
    )
    assert corpus.model_dump_json() == before
    assert report.request_count == 2
    assert report.response_count == 2
    assert report.observation_count == 3
    assert report.failed_request_count == 0
    assert {len(item.context_items) for item in run.requests} == {2}
    assert all(
        item.context_window_id.startswith("contextwindow_")
        and item.provider == provider.capabilities.identity
        and item.raw_evidence_sha256 is not None
        for item in run.observations
    )
    assert {
        item.act_type for item in run.observations
    } >= {
        DiscourseActType.INFORMATION_QUESTION,
        DiscourseActType.AFFIRMATIVE_ANSWER,
        DiscourseActType.SCOPE_QUALIFICATION,
    }
    validate_provider_analysis(run, report, corpus, bundle)


def test_provider_timeout_retries_once_without_duplicate_observations():
    corpus = _with_texts("What time is the hearing?")
    provider = ControlledProvider(timeout_once=True)
    run, report = run_provider_analysis(
        corpus, _context_bundle(corpus), provider, created_at=NOW
    )
    assert provider.calls == 2
    assert report.retry_count == 1
    assert report.failed_request_count == 0
    assert len(run.observations) == 1
    assert run.failures[0].kind.value == "timeout"
    assert run.failures[0].retryable


def test_malformed_provider_span_becomes_typed_failure_not_evidence():
    corpus = _with_texts("What time is the hearing?")
    run, report = run_provider_analysis(
        corpus,
        _context_bundle(corpus),
        ControlledProvider(malformed_span=True),
        created_at=NOW,
    )
    assert report.status == "warning"
    assert report.failed_request_count == 1
    assert report.observation_count == 0
    assert run.failures[-1].kind.value == "validation_failure"
    assert not run.failures[-1].retryable


def test_unavailable_provider_is_conservative_and_typed():
    corpus = _with_texts("What time is the hearing?")
    run, report = run_provider_analysis(
        corpus,
        _context_bundle(corpus),
        UnconfiguredDiscourseProvider(),
        created_at=NOW,
    )
    assert report.status == "warning"
    assert report.failed_request_count == 1
    assert run.observations == ()
    assert run.failures[0].kind.value == "provider_unavailable"


def test_provider_persistence_reloads_and_rejects_tampering(tmp_path: Path):
    corpus = _with_texts("What time is the hearing?")
    bundle = _context_bundle(corpus)
    run, report = run_provider_analysis(
        corpus, bundle, ControlledProvider(), created_at=NOW
    )
    paths = persist_provider_analysis(
        run, report, corpus, bundle, tmp_path / "provider"
    )
    assert not paths[2]
    assert load_provider_analysis(tmp_path / "provider") == (run, report)
    assert persist_provider_analysis(
        run, report, corpus, bundle, tmp_path / "provider"
    )[2]
    tampered = run.model_copy(update={"configuration_hash": "f" * 64})
    with pytest.raises(ProviderDiscourseIntegrityError, match="integrity"):
        validate_provider_analysis(tampered, report, corpus, bundle)


def test_provider_cli_inspects_observations_and_failures(tmp_path: Path, capsys):
    import json

    corpus = _with_texts("What time is the hearing?")
    bundle = _context_bundle(corpus)
    run, report = run_provider_analysis(
        corpus, bundle, ControlledProvider(), created_at=NOW
    )
    root = tmp_path / "provider"
    persist_provider_analysis(run, report, corpus, bundle, root)
    assert main(["--json", "discourse", "provider-inspect", str(root)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["report"]["observation_count"] == 1
    assert main([
        "--json", "discourse", "list-provider-observations", str(root)
    ]) == 0
    observations = json.loads(capsys.readouterr().out)
    assert observations[0]["analysis_method"] == "provider_proposal"