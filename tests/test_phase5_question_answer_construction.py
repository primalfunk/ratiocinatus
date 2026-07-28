import json
from pathlib import Path

import pytest

from ratiocinatus.cli import main
from ratiocinatus.discourse_consolidation import (
    build_discourse_consolidation,
)
from ratiocinatus.discourse_provider_analysis import (
    run_provider_analysis,
    seal_provider_response,
)
from ratiocinatus.kernel import canonical_hash, typed_id
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
from ratiocinatus.phase5_question_answer_contracts import (
    AnswerRelation,
    QuestionAnswerPolicy,
)
from ratiocinatus.question_answer_construction import (
    QuestionAnswerIntegrityError,
    build_question_answers,
    load_question_answers,
    persist_question_answers,
    validate_question_answers,
)

from test_phase5_candidate_consolidation import _evidence
from test_phase5_foundation import NOW
from test_phase5_provider_analysis import ControlledProvider


class TypedAnswerProvider(ControlledProvider):
    ANSWERS = {
        "I will answer later.": DiscourseActType.ANSWER_DEFERRED,
        "I refuse to answer.": DiscourseActType.REFUSAL_TO_ANSWER,
        "I cannot answer.": DiscourseActType.INABILITY_TO_ANSWER,
        "That premise is false.":
            DiscourseActType.ANSWER_BY_REJECTION_OF_PREMISE,
    }

    def analyze(self, request):
        target = next(item for item in request.context_items if item.is_target)
        act_type = self.ANSWERS.get(target.displayed_text)
        if act_type is None:
            return super().analyze(request)
        self.calls += 1
        text = target.displayed_text
        proposal = ProviderActProposal(
            provider_proposal_id=typed_id(
                "providerproposal", request.request_id, 1
            ),
            act_family=DiscourseActFamily.ANSWER,
            act_type=act_type,
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
            classification_confidence=0.86,
            rank=1,
            evidence_for=("controlled explicit answer-state wording",),
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


def _canonical(*texts, provider=None):
    inputs = _evidence(*texts, provider=provider)
    _, corpus, _ = build_discourse_consolidation(
        *inputs[2:], inputs[0], inputs[1], created_at=NOW
    )
    return corpus, inputs[1]


def test_question_and_probable_answer_preserve_structure_without_adequacy():
    corpus, context = _canonical(
        "What time is the hearing?",
        "Yes, but only after 2022.",
    )
    run, report = build_question_answers(corpus, context, created_at=NOW)
    assert report.question_count == 1
    assert report.probable_answer_count == 1
    question = run.questions[0]
    assert question.requested_information_or_decision == (
        "What time is the hearing?"
    )
    assert question.addressee_status.value == "unresolved"
    relation = run.answer_relations[0]
    assert relation.target_status == DiscourseTargetStatus.PROBABLE
    assert relation.polarity.value == "affirmative"
    assert relation.qualification_act_ids
    assert relation.review_status.value == "review_required"
    forbidden = {"adequacy", "completeness", "evasion", "responsive"}
    assert forbidden.isdisjoint(AnswerRelation.model_fields)
    assert not QuestionAnswerPolicy().adequacy_scoring
    validate_question_answers(run, report, corpus, context)


def test_multiple_preceding_questions_remain_alternative_targets():
    corpus, context = _canonical(
        "What time is the hearing?",
        "Where will it be held?",
        "Yes, but only after 2022.",
    )
    run, report = build_question_answers(corpus, context, created_at=NOW)
    relation = run.answer_relations[0]
    assert report.question_count == 2
    assert report.ambiguous_answer_count == 1
    assert relation.target_status == DiscourseTargetStatus.MULTIPLE_CANDIDATES
    assert relation.target_question_ids == ()
    assert len(relation.alternative_question_ids) == 2


def test_several_utterances_can_jointly_answer_one_question():
    corpus, context = _canonical(
        "What time is the hearing?",
        "Yes, but only after 2022.",
        "Yes, but only after 2023.",
    )
    run, report = build_question_answers(corpus, context, created_at=NOW)
    assert len(run.answer_relations) == 2
    assert report.jointly_answered_question_count == 1
    assert all(
        len(item.co_answer_act_ids) == 1 for item in run.answer_relations
    )
    assert {
        item.target_question_ids for item in run.answer_relations
    } == {(run.questions[0].question_id,)}


def test_deferred_refused_inability_and_premise_rejection_are_explicit():
    corpus, context = _canonical(
        "What time is the hearing?",
        "I will answer later.",
        "I refuse to answer.",
        "I cannot answer.",
        "That premise is false.",
        provider=TypedAnswerProvider(),
    )
    run, report = build_question_answers(corpus, context, created_at=NOW)
    assert report.deferred_answer_count == 1
    assert report.refused_answer_count == 1
    assert report.inability_answer_count == 1
    assert report.premise_rejection_count == 1
    by_form = {item.answer_form: item for item in run.answer_relations}
    assert by_form[DiscourseActType.ANSWER_DEFERRED].deferred
    assert by_form[DiscourseActType.REFUSAL_TO_ANSWER].refused
    assert by_form[DiscourseActType.INABILITY_TO_ANSWER].inability
    assert by_form[
        DiscourseActType.ANSWER_BY_REJECTION_OF_PREMISE
    ].rejects_presupposition


def test_answer_before_question_without_explicit_target_stays_unresolved():
    corpus, context = _canonical(
        "I will answer later.",
        "What time is the hearing?",
        provider=TypedAnswerProvider(),
    )
    run, report = build_question_answers(corpus, context, created_at=NOW)
    relation = run.answer_relations[0]
    assert relation.target_status == DiscourseTargetStatus.UNRESOLVED
    assert relation.target_question_ids == ()
    assert relation.alternative_question_ids == ()
    assert run.unlinked_answer_act_ids == (relation.answer_act_id,)
    assert report.unresolved_answer_count == 1


def test_question_answer_persistence_cli_and_tamper_detection(
    tmp_path: Path, capsys
):
    corpus, context = _canonical(
        "Why are you still doing that?",
        "Yes, but only after 2022.",
    )
    artifacts = build_question_answers(corpus, context, created_at=NOW)
    root = tmp_path / "question-answers"
    paths = persist_question_answers(
        *artifacts, corpus, context, root
    )
    assert not paths[2]
    assert load_question_answers(root) == artifacts
    assert artifacts[0].questions[0].presupposition_markers == (
        "Why",
        "still",
    )
    assert main(
        ["--json", "discourse", "question-answer-inspect", str(root)]
    ) == 0
    assert json.loads(capsys.readouterr().out)["report"][
        "answer_relation_count"
    ] == 1
    assert main(
        ["--json", "discourse", "list-questions", str(root)]
    ) == 0
    assert len(json.loads(capsys.readouterr().out)) == 1
    assert main(
        ["--json", "discourse", "list-answer-relations", str(root)]
    ) == 0
    assert len(json.loads(capsys.readouterr().out)) == 1
    tampered = artifacts[0].model_copy(
        update={"configuration_hash": "f" * 64}
    )
    with pytest.raises(QuestionAnswerIntegrityError, match="integrity"):
        validate_question_answers(
            tampered, artifacts[1], corpus, context
        )
