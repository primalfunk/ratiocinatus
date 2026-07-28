from pathlib import Path

import pytest

from ratiocinatus.discourse_consolidation import build_discourse_consolidation
from ratiocinatus.kernel import canonical_hash, typed_id
from ratiocinatus.phase5_contracts import (
    DiscourseActFamily,
    DiscourseActType,
)
from ratiocinatus.phase5_evaluation import (
    Phase5EvaluationIntegrityError,
    evaluate_phase5,
    load_phase5_evaluation,
    persist_phase5_evaluation,
    validate_phase5_evaluation,
)
from ratiocinatus.phase5_evaluation_contracts import (
    Phase5ControlledReference,
    Phase5EvaluationMetricKind,
    Phase5EvaluationMetricStatus,
    Phase5EvaluationStratum,
    Phase5ReferenceAct,
    Phase5ReferenceSpan,
)

from test_phase5_candidate_consolidation import _evidence
from test_phase5_foundation import NOW


def _seal(model, payload):
    provisional = model(**payload, integrity_sha256="0" * 64)
    return provisional.model_copy(
        update={
            "integrity_sha256": canonical_hash(
                provisional.model_dump(
                    mode="json", exclude={"integrity_sha256"}
                )
            )
        }
    )


def _artifacts():
    inputs = _evidence(
        "What time is the hearing?",
        "Yes, but only after 2022.",
    )
    _, corpus, _ = build_discourse_consolidation(
        *inputs[2:], inputs[0], inputs[1], created_at=NOW
    )
    return inputs[0], corpus


def _reference(corpus):
    candidate_sets = {
        item.candidate_set_id: item for item in corpus.candidate_sets
    }
    acts_by_utterance = {}
    for act in corpus.selected_acts:
        acts_by_utterance.setdefault(act.utterance_id, []).append(act)
    acts = []
    for act in corpus.selected_acts:
        reference_id = typed_id(
            "refdiscourseact", act.act_id, "synthetic-controlled"
        )
        spans = tuple(
            Phase5ReferenceSpan(
                reference_span_id=typed_id(
                    "refdiscoursespan", reference_id, span.span_id
                ),
                utterance_id=span.utterance_id,
                start_text_offset=span.start_text_offset,
                end_text_offset=span.end_text_offset,
                exact_displayed_text=span.exact_displayed_text,
            )
            for span in act.evidence_spans
        )
        alternatives = tuple(
            sorted(
                {
                    candidate.act_type
                    for candidate in candidate_sets[
                        act.candidate_set_id
                    ].candidates
                    if candidate.act_type != act.act_type
                },
                key=lambda item: item.value,
            )
        )
        strata = {Phase5EvaluationStratum.CLEAN}
        if len(acts_by_utterance[act.utterance_id]) > 1:
            strata.add(Phase5EvaluationStratum.MULTI_LABEL)
        if act.act_family in {
            DiscourseActFamily.QUESTION,
            DiscourseActFamily.ANSWER,
        }:
            strata.add(Phase5EvaluationStratum.QUESTION_ANSWER)
        if act.act_family in {
            DiscourseActFamily.CONCESSION,
            DiscourseActFamily.QUALIFICATION,
            DiscourseActFamily.DEFINITION,
            DiscourseActFamily.EXAMPLE,
        }:
            strata.add(Phase5EvaluationStratum.LEXICAL)
        targets = tuple(
            sorted(
                {
                    value
                    for proposal in act.relation_targets
                    for value in (
                        *((proposal.target_id,) if proposal.target_id else ()),
                        *proposal.alternative_target_ids,
                    )
                }
            )
        )
        acts.append(
            _seal(
                Phase5ReferenceAct,
                {
                    "reference_act_id": reference_id,
                    "utterance_id": act.utterance_id,
                    "act_family": act.act_family,
                    "act_type": act.act_type,
                    "evidence_spans": spans,
                    "target_ids": targets,
                    "alternative_act_types": alternatives,
                    "unresolved_expected": False,
                    "strata": tuple(
                        sorted(strata, key=lambda item: item.value)
                    ),
                    "evidence_references": (
                        act.act_id,
                        *act.source_observation_ids,
                    ),
                },
            )
        )
    return _seal(
        Phase5ControlledReference,
        {
            "reference_id": typed_id(
                "phase5reference", corpus.corpus_id, "synthetic-controlled"
            ),
            "phase4_utterance_corpus_id": (
                corpus.phase4_utterance_corpus_id
            ),
            "acts": tuple(acts),
            "prepared_by": "controlled-fixture-author",
            "prepared_at": NOW,
            "preparation_method": (
                "Source-grounded synthetic mechanics reference prepared "
                "outside the evaluation function."
            ),
            "independent_of_system_output": False,
            "evidence_class": "synthetic_mechanics",
        },
    )


def _metric(evaluation, kind):
    return next(item for item in evaluation.metrics if item.kind == kind)


def test_evaluation_is_complete_deterministic_and_stratified():
    phase4, corpus = _artifacts()
    reference = _reference(corpus)
    evaluation, report = evaluate_phase5(
        corpus, phase4, reference, generated_at=NOW
    )
    repeated = evaluate_phase5(
        corpus, phase4, reference, generated_at=NOW
    )
    assert repeated == (evaluation, report)
    assert {item.kind for item in evaluation.metrics} == set(
        Phase5EvaluationMetricKind
    )
    assert len(evaluation.metrics) == 28
    assert evaluation.strata
    assert evaluation.evidence_class == "synthetic_mechanics"
    assert _metric(
        evaluation, Phase5EvaluationMetricKind.ACT_TYPE_F1
    ).value == 1.0
    assert _metric(
        evaluation, Phase5EvaluationMetricKind.MULTI_LABEL_EXACT_MATCH
    ).value == 1.0
    assert _metric(
        evaluation, Phase5EvaluationMetricKind.EVIDENCE_SPAN_OVERLAP
    ).value == 1.0
    assert report.measured_metric_count + report.not_applicable_metric_count == 28
    validate_phase5_evaluation(
        evaluation, report, corpus, phase4, reference
    )


def test_ineligible_relation_metrics_are_explicitly_not_applicable():
    phase4, corpus = _artifacts()
    evaluation, _ = evaluate_phase5(
        corpus, phase4, _reference(corpus), generated_at=NOW
    )
    objection = _metric(
        evaluation, Phase5EvaluationMetricKind.OBJECTION_TARGET_ACCURACY
    )
    assert objection.status == Phase5EvaluationMetricStatus.NOT_APPLICABLE
    assert objection.value is None and objection.denominator == 0


def test_wrong_reference_lineage_is_rejected():
    phase4, corpus = _artifacts()
    payload = _reference(corpus).model_dump(
        mode="python", exclude={"integrity_sha256"}
    )
    payload["phase4_utterance_corpus_id"] = typed_id(
        "utterancecorpus", "wrong"
    )
    reference = _seal(Phase5ControlledReference, payload)
    with pytest.raises(
        Phase5EvaluationIntegrityError, match="another Phase 4 corpus"
    ):
        evaluate_phase5(corpus, phase4, reference, generated_at=NOW)


def test_evaluation_persistence_replays_and_rejects_tampering(
    tmp_path: Path,
):
    phase4, corpus = _artifacts()
    reference = _reference(corpus)
    evaluation, report = evaluate_phase5(
        corpus, phase4, reference, generated_at=NOW
    )
    first = persist_phase5_evaluation(
        evaluation, report, corpus, phase4, reference, tmp_path
    )
    replay = persist_phase5_evaluation(
        evaluation, report, corpus, phase4, reference, tmp_path
    )
    assert not first[3] and replay[3]
    assert load_phase5_evaluation(first[2]) == (evaluation, report)
    tampered = evaluation.model_copy(update={"strata": ()})
    with pytest.raises(
        Phase5EvaluationIntegrityError, match="integrity is invalid"
    ):
        validate_phase5_evaluation(
            tampered, report, corpus, phase4, reference
        )


def test_propagation_stability_and_review_impact_are_measured():
    from ratiocinatus.discourse_review import (
        append_discourse_review_action,
        build_discourse_propagation,
        create_discourse_review_ledger,
    )
    from ratiocinatus.phase5_contracts import DiscourseReviewStatus
    from ratiocinatus.phase5_review_contracts import (
        DiscourseReviewActionKind,
    )
    from test_phase5_review_propagation import _change_display_text

    phase4, corpus = _artifacts()
    successor = _change_display_text(
        phase4, phase4.utterances[0].utterance_id, "When is the hearing?"
    )
    propagation = build_discourse_propagation(
        phase4, successor, corpus, created_at=NOW
    )
    ledger = create_discourse_review_ledger(corpus, created_at=NOW)
    act = corpus.selected_acts[0]
    ledger = append_discourse_review_action(
        ledger,
        corpus,
        DiscourseReviewActionKind.APPROVE_ACT,
        (act.act_id,),
        prior_state={"review_status": act.review_status.value},
        proposed_state={"review_status": "approved"},
        author="controlled-reviewer",
        reviewed_at=NOW,
        rationale="Controlled reference agrees with the machine act.",
        evidence_references=(act.act_id,),
        certainty=0.95,
        resulting_review_status=DiscourseReviewStatus.APPROVED,
    )
    reference = _reference(corpus)
    first = reference.acts[0]
    payload = first.model_dump(mode="python", exclude={"integrity_sha256"})
    payload["strata"] = tuple(
        sorted(
            {*first.strata, Phase5EvaluationStratum.CORRECTION_AFFECTED},
            key=lambda item: item.value,
        )
    )
    changed_first = _seal(Phase5ReferenceAct, payload)
    reference_payload = reference.model_dump(
        mode="python", exclude={"integrity_sha256"}
    )
    reference_payload["acts"] = (changed_first, *reference.acts[1:])
    reference = _seal(Phase5ControlledReference, reference_payload)
    evaluation, _ = evaluate_phase5(
        corpus,
        phase4,
        reference,
        propagation=propagation,
        review_ledger=ledger,
        generated_at=NOW,
    )
    assert _metric(
        evaluation,
        Phase5EvaluationMetricKind.CORRECTION_PROPAGATION_COMPLETENESS,
    ).value == 1.0
    assert _metric(
        evaluation, Phase5EvaluationMetricKind.UNAFFECTED_ARTIFACT_STABILITY
    ).value == 1.0
    assert _metric(
        evaluation, Phase5EvaluationMetricKind.HUMAN_REVIEW_IMPACT
    ).value == 1.0


def test_cli_exposes_evaluation_operations():
    from ratiocinatus.cli import build_parser

    args = build_parser().parse_args(
        [
            "discourse",
            "evaluate",
            "consolidation",
            "phase4",
            "reference.json",
            "output",
        ]
    )
    assert args.action == "evaluate"
