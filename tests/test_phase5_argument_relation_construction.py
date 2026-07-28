import json
from pathlib import Path

import pytest

from ratiocinatus.argument_relation_construction import (
    ArgumentRelationIntegrityError,
    build_argument_relations,
    load_argument_relations,
    persist_argument_relations,
    validate_argument_relations,
)
from ratiocinatus.cli import main
from ratiocinatus.discourse_provider_analysis import seal_provider_response
from ratiocinatus.kernel import canonical_hash, typed_id
from ratiocinatus.phase5_argument_relation_contracts import (
    ChallengeDimension,
    RebuttalMethod,
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

from test_phase5_foundation import NOW
from test_phase5_provider_analysis import ControlledProvider
from test_phase5_question_answer_construction import _canonical


class ArgumentProvider(ControlledProvider):
    TYPES = {
        "The policy caused the delay.": (
            DiscourseActFamily.ASSERTIVE,
            DiscourseActType.ASSERTION,
        ),
        "I deny that claim, probably.": (
            DiscourseActFamily.ASSERTIVE,
            DiscourseActType.ASSERTION,
        ),
        "I object to that evidence.": (
            DiscourseActFamily.OBJECTION,
            DiscourseActType.EVIDENCE_CHALLENGE,
        ),
        "That claim fails.": (
            DiscourseActFamily.REBUTTAL,
            DiscourseActType.DIRECT_REBUTTAL,
        ),
        "This purported rebuttal has no clear target.": (
            DiscourseActFamily.REBUTTAL,
            DiscourseActType.UNRESOLVED_TARGET_REBUTTAL,
        ),
    }

    def analyze(self, request):
        target = next(item for item in request.context_items if item.is_target)
        spec = self.TYPES.get(target.displayed_text)
        if spec is None:
            return super().analyze(request)
        self.calls += 1
        text = target.displayed_text
        proposal = ProviderActProposal(
            provider_proposal_id=typed_id(
                "providerproposal", request.request_id, 1
            ),
            act_family=spec[0],
            act_type=spec[1],
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
            evidence_for=("controlled argument-relation fixture",),
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


def test_evidence_objection_targets_nearest_prior_act_probably():
    corpus, context = _canonical(
        "The policy caused the delay.",
        "I object to that evidence.",
        provider=ArgumentProvider(),
    )
    run, report = build_argument_relations(corpus, context, created_at=NOW)
    relation = run.challenge_rebuttal_relations[0]
    assert report.objection_relation_count == 1
    assert relation.challenge_dimension == ChallengeDimension.EVIDENCE
    assert relation.target_status == DiscourseTargetStatus.PROBABLE
    assert len(relation.target_act_ids) == 1
    assert relation.challenged_span_ids
    assert relation.review_status.value == "review_required"


def test_multiple_nearest_prior_acts_preserve_target_ambiguity():
    corpus, context = _canonical(
        "I deny that claim, probably.",
        "I object to that evidence.",
        provider=ArgumentProvider(),
    )
    run, report = build_argument_relations(corpus, context, created_at=NOW)
    relation = run.challenge_rebuttal_relations[0]
    assert report.ambiguous_target_count >= 1
    assert relation.target_status == DiscourseTargetStatus.MULTIPLE_CANDIDATES
    assert relation.target_act_ids == ()
    assert len(relation.alternative_target_act_ids) >= 2
    assert relation.source_act_id in run.unresolved_source_act_ids


def test_rebuttal_relation_never_claims_success():
    corpus, context = _canonical(
        "The policy caused the delay.",
        "That claim fails.",
        provider=ArgumentProvider(),
    )
    run, report = build_argument_relations(corpus, context, created_at=NOW)
    relation = run.challenge_rebuttal_relations[0]
    assert report.rebuttal_relation_count == 1
    assert relation.rebuttal_method == RebuttalMethod.DIRECT
    assert not relation.rebuttal_success_assessed
    assert "success" not in type(relation).model_fields
    assert "successful" not in type(relation).model_fields


def test_explicit_unresolved_rebuttal_type_forces_unresolved_target():
    corpus, context = _canonical(
        "The policy caused the delay.",
        "This purported rebuttal has no clear target.",
        provider=ArgumentProvider(),
    )
    run, report = build_argument_relations(corpus, context, created_at=NOW)
    relation = run.challenge_rebuttal_relations[0]
    assert relation.rebuttal_method == RebuttalMethod.UNRESOLVED
    assert relation.target_status == DiscourseTargetStatus.UNRESOLVED
    assert relation.target_act_ids == ()
    assert report.unresolved_target_count == 1


def test_partial_concession_retains_temporal_and_scope_qualification():
    corpus, context = _canonical(
        "What time is the hearing?",
        "Yes, but only after 2022.",
    )
    run, report = build_argument_relations(corpus, context, created_at=NOW)
    concession = run.concessions[0]
    assert report.concession_count == 1
    assert report.qualification_count == 2
    assert concession.conceded_content == ("Yes, but",)
    assert concession.retained_disagreement == ("only", "after 2022")
    assert len(concession.qualification_act_ids) == 2
    assert {item.dimension.value for item in run.qualifications} == {
        "scope",
        "temporal",
    }
    assert all(
        item.target_status
        == DiscourseTargetStatus.MULTIPLE_CANDIDATES
        for item in run.qualifications
    )


def test_argument_relation_persistence_cli_and_tamper_detection(
    tmp_path: Path, capsys
):
    corpus, context = _canonical(
        "The policy caused the delay.",
        "I object to that evidence.",
        provider=ArgumentProvider(),
    )
    artifacts = build_argument_relations(corpus, context, created_at=NOW)
    root = tmp_path / "argument-relations"
    paths = persist_argument_relations(
        *artifacts, corpus, context, root
    )
    assert not paths[2]
    assert load_argument_relations(root) == artifacts
    assert persist_argument_relations(
        *artifacts, corpus, context, root
    )[2]
    assert main(
        ["--json", "discourse", "argument-relations-inspect", str(root)]
    ) == 0
    assert json.loads(capsys.readouterr().out)["report"][
        "objection_relation_count"
    ] == 1
    assert main(
        ["--json", "discourse", "list-objections", str(root)]
    ) == 0
    assert len(json.loads(capsys.readouterr().out)) == 1
    tampered = artifacts[0].model_copy(
        update={"configuration_hash": "f" * 64}
    )
    with pytest.raises(ArgumentRelationIntegrityError, match="integrity"):
        validate_argument_relations(
            tampered, artifacts[1], corpus, context
        )
