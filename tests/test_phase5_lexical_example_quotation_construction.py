import json
from pathlib import Path

import pytest

from ratiocinatus.cli import main
from ratiocinatus.discourse_baseline import build_deterministic_discourse
from ratiocinatus.discourse_consolidation import (
    build_discourse_consolidation,
)
from ratiocinatus.discourse_provider_analysis import (
    run_provider_analysis,
    seal_provider_response,
)
from ratiocinatus.kernel import canonical_hash, typed_id
from ratiocinatus.lexical_example_quotation_construction import (
    LexicalConstructionIntegrityError,
    build_lexical_example_quotation,
    load_lexical_example_quotation,
    persist_lexical_example_quotation,
    validate_lexical_example_quotation,
)
from ratiocinatus.phase5_contracts import (
    DiscourseActFamily,
    DiscourseActType,
    DiscourseEvidenceSpanRole,
    DiscourseTargetStatus,
)
from ratiocinatus.phase5_provider_analysis_contracts import (
    ProviderActProposal,
    ProviderAnalysisResponse,
    ProviderSpanProposal,
)

from test_phase5_deterministic_baseline import _quotation, _with_texts
from test_phase5_foundation import NOW
from test_phase5_provider_analysis import ControlledProvider, _context_bundle
from test_phase5_question_answer_construction import _canonical


class DefinitionChallengeProvider(ControlledProvider):
    def analyze(self, request):
        target = next(item for item in request.context_items if item.is_target)
        if target.displayed_text != "That definition is wrong.":
            return super().analyze(request)
        self.calls += 1
        text = target.displayed_text
        proposal = ProviderActProposal(
            provider_proposal_id=typed_id(
                "providerproposal", request.request_id, 1
            ),
            act_family=DiscourseActFamily.OBJECTION,
            act_type=DiscourseActType.DEFINITION_CHALLENGE,
            spans=(
                ProviderSpanProposal(
                    proposal_span_id=typed_id(
                        "providerspan", request.request_id, 1
                    ),
                    start_text_offset=0,
                    end_text_offset=len(text),
                    exact_displayed_text=text,
                    role=DiscourseEvidenceSpanRole.ACT_CONTENT,
                    confidence=0.84,
                ),
            ),
            classification_confidence=0.87,
            rank=1,
            evidence_for=("controlled definition challenge",),
        )
        raw_hash = canonical_hash((proposal.model_dump(mode="json"),))
        return seal_provider_response(
            ProviderAnalysisResponse(
                response_id=typed_id(
                    "discourseresponse", request.request_id, raw_hash
                ),
                request_id=request.request_id,
                provider=self.capabilities.identity,
                proposals=(proposal,),
                raw_output_sha256=raw_hash,
                raw_output_retained=True,
                completed_at=NOW,
                integrity_sha256="0" * 64,
            )
        )


class QuotationUseProvider(ControlledProvider):
    def analyze(self, request):
        target = next(
            item for item in request.context_items if item.is_target
        )
        text = target.displayed_text
        if '"' not in text:
            return super().analyze(request)
        self.calls += 1
        start = text.index('"') + 1
        end = text.rindex('"')
        proposal = ProviderActProposal(
            provider_proposal_id=typed_id(
                "providerproposal", request.request_id, 1
            ),
            act_family=DiscourseActFamily.QUOTATION,
            act_type=DiscourseActType.DIRECT_QUOTATION,
            spans=(
                ProviderSpanProposal(
                    proposal_span_id=typed_id(
                        "providerspan", request.request_id, 1
                    ),
                    start_text_offset=start,
                    end_text_offset=end,
                    exact_displayed_text=text[start:end],
                    role=DiscourseEvidenceSpanRole.QUOTATION,
                    confidence=0.9,
                ),
            ),
            classification_confidence=0.9,
            rank=1,
            evidence_for=(
                "controlled Phase 4 quotation-use match",
            ),
        )
        raw_hash = canonical_hash(
            (proposal.model_dump(mode="json"),)
        )
        return seal_provider_response(
            ProviderAnalysisResponse(
                response_id=typed_id(
                    "discourseresponse", request.request_id, raw_hash
                ),
                request_id=request.request_id,
                provider=self.capabilities.identity,
                proposals=(proposal,),
                raw_output_sha256=raw_hash,
                raw_output_retained=True,
                completed_at=NOW,
                integrity_sha256="0" * 64,
            )
        )

def _canonical_with_quotation(text):
    phase4 = _with_texts(text)
    quotation = _quotation(phase4)
    context = _context_bundle(phase4)
    baseline, baseline_report = build_deterministic_discourse(
        phase4, created_at=NOW
    )
    provider, provider_report = run_provider_analysis(
        phase4,
        context,
        QuotationUseProvider(),
        created_at=NOW,
    )
    _, corpus, _ = build_discourse_consolidation(
        baseline,
        baseline_report,
        provider,
        provider_report,
        phase4,
        context,
        created_at=NOW,
    )
    return corpus, context, quotation


def test_definition_extracts_expression_body_scope_and_exclusion():
    corpus, context = _canonical(
        "For purposes of this rule, resident means a person living here, "
        "excluding visitors."
    )
    run, report = build_lexical_example_quotation(
        corpus, context, created_at=NOW
    )
    definition = run.definitions[0]
    assert report.definition_count == 1
    assert definition.defined_expression == "resident"
    assert definition.defining_text == (
        "a person living here, excluding visitors.",
    )
    assert definition.scope.value == "declared_context"
    assert definition.applicable_context_text == ("this rule",)
    assert definition.explicit_exclusions == ("visitors",)


def test_competing_definitions_and_nearest_challenge_remain_linked():
    corpus, context = _canonical(
        "Resident means a local person.",
        "Resident means a registered voter.",
        "That definition is wrong.",
        provider=DefinitionChallengeProvider(),
    )
    run, report = build_lexical_example_quotation(
        corpus, context, created_at=NOW
    )
    assert len(run.definitions) == 2
    assert report.competing_definition_count == 2
    assert all(
        len(item.competing_definition_ids) == 1
        for item in run.definitions
    )
    assert run.definitions[0].definition_challenge_act_ids == ()
    assert len(run.definitions[1].definition_challenge_act_ids) == 1
    assert report.definition_challenge_link_count == 1


def test_example_links_probably_without_proof_or_representativeness():
    corpus, context = _canonical(
        "Resident means a local person.",
        "For example, consider the north district in 2022.",
    )
    run, report = build_lexical_example_quotation(
        corpus, context, created_at=NOW
    )
    example = run.examples[0]
    assert report.probable_example_target_count == 1
    assert example.target_status == DiscourseTargetStatus.PROBABLE
    assert len(example.generalization_act_ids) == 1
    assert example.temporal_references == ("2022",)
    assert not example.representativeness_assessed
    assert not example.proves_generalization


def test_example_without_prior_generalization_remains_unresolved():
    corpus, context = _canonical(
        "For example, consider the north district."
    )
    run, report = build_lexical_example_quotation(
        corpus, context, created_at=NOW
    )
    assert report.unresolved_example_target_count == 1
    assert run.examples[0].target_status == DiscourseTargetStatus.UNRESOLVED
    assert run.examples[0].source_act_id in run.unresolved_source_act_ids


def test_quotation_use_preserves_phase4_acoustic_attribution():
    corpus, context, quotation = _canonical_with_quotation(
        'Alice said "The sky is blue."'
    )
    run, report = build_lexical_example_quotation(
        corpus,
        context,
        created_at=NOW,
        quotation_evidence=quotation,
    )
    use = run.quotation_uses[0]
    phase4 = quotation.quotations[0]
    assert report.phase4_matched_quotation_use_count == 1
    assert use.phase4_quotation_id == phase4.quotation_id
    assert use.quoted_span == phase4.quoted_span
    assert use.acoustic_attribution_id == phase4.acoustic_attribution_id
    assert use.quoting_speaker_target_id == (
        phase4.acoustic_speaker_target_id
    )
    assert use.attributed_speaker_target_id == (
        phase4.quoted_speaker_target_id
    )
    assert use.acoustic_attribution_preserved
    assert not use.acoustic_attribution_mutated


def test_lexical_construction_persistence_cli_and_tamper_detection(
    tmp_path: Path, capsys
):
    corpus, context = _canonical(
        "Resident means a local person.",
        "For example, consider the north district.",
    )
    artifacts = build_lexical_example_quotation(
        corpus, context, created_at=NOW
    )
    root = tmp_path / "lexical"
    paths = persist_lexical_example_quotation(
        *artifacts, corpus, context, root
    )
    assert not paths[2]
    assert load_lexical_example_quotation(root) == artifacts
    assert persist_lexical_example_quotation(
        *artifacts, corpus, context, root
    )[2]
    assert main(
        ["--json", "discourse", "lexical-structures-inspect", str(root)]
    ) == 0
    assert json.loads(capsys.readouterr().out)["report"][
        "definition_count"
    ] == 1
    assert main(
        ["--json", "discourse", "list-examples", str(root)]
    ) == 0
    assert len(json.loads(capsys.readouterr().out)) == 1
    tampered = artifacts[0].model_copy(
        update={"configuration_hash": "f" * 64}
    )
    with pytest.raises(
        LexicalConstructionIntegrityError, match="integrity"
    ):
        validate_lexical_example_quotation(
            tampered, artifacts[1], corpus, context
        )
