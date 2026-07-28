import json

import pytest

from ratiocinatus.discourse_consolidation import build_discourse_consolidation
from ratiocinatus.discourse_review import (
    DiscourseReviewIntegrityError,
    append_discourse_review_action,
    build_discourse_propagation,
    build_discourse_review_queue,
    create_discourse_review_ledger,
    load_discourse_propagation,
    load_discourse_review_ledger,
    load_discourse_review_queue,
    persist_discourse_propagation,
    persist_discourse_review_ledger,
    persist_discourse_review_queue,
    validate_discourse_review_ledger,
)
from ratiocinatus.kernel import canonical_hash, typed_id
from ratiocinatus.phase4_contracts import (
    UtteranceInterruptionStatus,
    UtteranceQuotationStatus,
    UtteranceTextKind,
)
from ratiocinatus.phase5_contracts import DiscourseReviewStatus
from ratiocinatus.phase5_review_contracts import (
    DiscourseReviewActionKind,
    DiscourseReviewQueueKind,
    Phase5ChangeKind,
)

from test_phase5_candidate_consolidation import _evidence
from test_phase5_foundation import NOW


def _artifacts(*texts):
    inputs = _evidence(*texts)
    _, corpus, _ = build_discourse_consolidation(
        *inputs[2:], inputs[0], inputs[1], created_at=NOW
    )
    return inputs[0], corpus


def _change_display_label(corpus, utterance_id, label):
    utterances = []
    for utterance in corpus.utterances:
        if utterance.utterance_id == utterance_id:
            attribution = utterance.attribution.model_copy(
                update={"display_label": label}
            )
            utterance = utterance.model_copy(update={"attribution": attribution})
        utterances.append(utterance)
    return corpus.model_copy(
        update={
            "corpus_id": typed_id("utterancecorpus", corpus.corpus_id, label),
            "utterances": tuple(utterances),
        }
    )


def _change_display_text(corpus, utterance_id, text):
    utterances = []
    for utterance in corpus.utterances:
        if utterance.utterance_id == utterance_id:
            views = []
            for view in utterance.text_views:
                if view.kind == UtteranceTextKind.DISPLAY:
                    view = view.model_copy(update={"text": text})
                views.append(view)
            utterance = utterance.model_copy(update={"text_views": tuple(views)})
        utterances.append(utterance)
    return corpus.model_copy(
        update={
            "corpus_id": typed_id("utterancecorpus", corpus.corpus_id, text),
            "utterances": tuple(utterances),
        }
    )


def test_append_only_review_supports_attributable_successor_ledgers():
    _, corpus = _artifacts("What time is the hearing?", "Yes, but only after 2022.")
    act = corpus.selected_acts[0]
    ledger = create_discourse_review_ledger(corpus, created_at=NOW)
    successor = append_discourse_review_action(
        ledger,
        corpus,
        DiscourseReviewActionKind.APPROVE_ACT,
        (act.act_id,),
        prior_state={"review_status": act.review_status.value},
        proposed_state={"review_status": "approved"},
        author="reviewer@example.test",
        reviewed_at=NOW,
        rationale="The displayed question form and evidence span agree.",
        evidence_references=(act.act_id, act.evidence_spans[0].span_id),
        certainty=0.95,
        resulting_review_status=DiscourseReviewStatus.APPROVED,
    )
    assert ledger.ledger_version == 0 and not ledger.actions
    assert successor.predecessor_ledger_id == ledger.ledger_id
    assert successor.ledger_version == 1
    assert successor.actions[0].phase4_utterance_corpus_modified is False
    validate_discourse_review_ledger(successor, corpus)


def test_defer_action_requires_deferred_result():
    _, corpus = _artifacts("What time is the hearing?")
    ledger = create_discourse_review_ledger(corpus, created_at=NOW)
    with pytest.raises(ValueError, match="defer action"):
        append_discourse_review_action(
            ledger,
            corpus,
            DiscourseReviewActionKind.DEFER_DECISION,
            (corpus.selected_acts[0].act_id,),
            prior_state={"status": "unreviewed"},
            proposed_state={"status": "approved"},
            author="reviewer",
            reviewed_at=NOW,
            rationale="Not actually deferred.",
            evidence_references=(corpus.selected_acts[0].act_id,),
            certainty=0.5,
            resulting_review_status=DiscourseReviewStatus.APPROVED,
        )


def test_display_label_only_change_preserves_classification_identifiers():
    phase4, corpus = _artifacts("What time is the hearing?", "Yes, but only after 2022.")
    utterance_id = phase4.utterances[0].utterance_id
    successor = _change_display_label(phase4, utterance_id, "Reviewed speaker")
    run, report = build_discourse_propagation(
        phase4, successor, corpus, created_at=NOW
    )
    impact = run.impacts[0]
    assert impact.change_kinds == (Phase5ChangeKind.DISPLAY_LABEL_ONLY,)
    assert not impact.invalidated_observation_ids
    assert not impact.invalidated_act_ids
    assert set(run.preserved_act_ids) == {
        item.act_id for item in corpus.selected_acts
    }
    assert report.display_label_only_change_count == 1


def test_text_change_invalidates_spans_observations_candidates_and_acts():
    phase4, corpus = _artifacts("What time is the hearing?", "Yes, but only after 2022.")
    utterance_id = phase4.utterances[0].utterance_id
    successor = _change_display_text(phase4, utterance_id, "When is the hearing?")
    run, report = build_discourse_propagation(
        phase4, successor, corpus, created_at=NOW
    )
    impact = run.impacts[0]
    expected_acts = {
        item.act_id
        for item in corpus.selected_acts
        if item.utterance_id == utterance_id
    }
    assert impact.change_kinds == (Phase5ChangeKind.TEXT,)
    assert impact.invalidated_observation_ids
    assert impact.invalidated_candidate_set_ids
    assert set(impact.invalidated_act_ids) == expected_acts
    assert report.invalidated_act_count == len(expected_acts)
    assert run.rebuild_procedural_state and run.rebuild_review_queues


def test_identity_change_only_invalidates_when_dependency_is_declared():
    phase4, corpus = _artifacts("What time is the hearing?")
    utterance = phase4.utterances[0]
    successor = _change_display_label(
        phase4, utterance.utterance_id, "Identity-dependent label"
    )
    # Turn a label-only edit into a substantive attribution edit.
    changed = successor.utterances[0]
    attribution = changed.attribution.model_copy(
        update={"target_id": "participant_changed"}
    )
    successor = successor.model_copy(
        update={
            "utterances": (
                changed.model_copy(update={"attribution": attribution}),
            )
        }
    )
    without, _ = build_discourse_propagation(
        phase4, successor, corpus, created_at=NOW
    )
    with_dependency, _ = build_discourse_propagation(
        phase4,
        successor,
        corpus,
        created_at=NOW,
        identity_specific_context_utterance_ids=(utterance.utterance_id,),
    )
    assert not without.invalidated_act_ids
    assert with_dependency.invalidated_act_ids


def test_queue_exposes_machine_evidence_and_correction_affected_acts():
    phase4, corpus = _artifacts("What time is the hearing?", "Yes, but only after 2022.")
    utterance_id = phase4.utterances[0].utterance_id
    successor = _change_display_text(phase4, utterance_id, "When is the hearing?")
    propagation, _ = build_discourse_propagation(
        phase4, successor, corpus, created_at=NOW
    )
    ledger = create_discourse_review_ledger(corpus, created_at=NOW)
    queue = build_discourse_review_queue(
        corpus, phase4, ledger, propagation=propagation, generated_at=NOW
    )
    correction_items = [
        item
        for item in queue.items
        if item.kind == DiscourseReviewQueueKind.CORRECTION_AFFECTED_ACT
    ]
    assert correction_items
    assert correction_items[0].utterance_text == "What time is the hearing?"
    assert correction_items[0].speaker_attribution
    assert correction_items[0].source_interval_references
    assert correction_items[0].evidence_span_ids


def test_review_and_propagation_artifacts_round_trip_and_reuse(tmp_path):
    phase4, corpus = _artifacts("What time is the hearing?")
    successor = _change_display_text(
        phase4, phase4.utterances[0].utterance_id, "When is the hearing?"
    )
    ledger = create_discourse_review_ledger(corpus, created_at=NOW)
    queue = build_discourse_review_queue(
        corpus, phase4, ledger, generated_at=NOW
    )
    run, report = build_discourse_propagation(
        phase4, successor, corpus, created_at=NOW
    )
    _, ledger_root, reused = persist_discourse_review_ledger(
        ledger, corpus, tmp_path
    )
    assert not reused and load_discourse_review_ledger(ledger_root) == ledger
    _, queue_root, reused = persist_discourse_review_queue(queue, tmp_path)
    assert not reused and load_discourse_review_queue(queue_root) == queue
    _, _, propagation_root, reused = persist_discourse_propagation(
        run, report, phase4, successor, corpus, tmp_path
    )
    assert not reused
    assert load_discourse_propagation(propagation_root) == (run, report)
    _, _, _, reused = persist_discourse_propagation(
        run, report, phase4, successor, corpus, tmp_path
    )
    assert reused


def test_tampered_ledger_is_rejected():
    _, corpus = _artifacts("What time is the hearing?")
    ledger = create_discourse_review_ledger(corpus, created_at=NOW)
    tampered = ledger.model_copy(
        update={"integrity_sha256": canonical_hash("tampered")}
    )
    with pytest.raises(DiscourseReviewIntegrityError, match="integrity"):
        validate_discourse_review_ledger(tampered, corpus)


def test_boundary_change_invalidates_span_dependent_artifacts():
    phase4, corpus = _artifacts("What time is the hearing?")
    utterance = phase4.utterances[0]
    interval = utterance.source_intervals[0]
    changed_interval = interval.model_copy(
        update={"duration_microseconds": interval.duration_microseconds + 1}
    )
    changed = utterance.model_copy(
        update={"source_intervals": (changed_interval,)}
    )
    successor = phase4.model_copy(
        update={
            "corpus_id": typed_id("utterancecorpus", phase4.corpus_id, "boundary"),
            "utterances": (changed,),
        }
    )
    run, _ = build_discourse_propagation(
        phase4, successor, corpus, created_at=NOW
    )
    assert run.impacts[0].change_kinds == (Phase5ChangeKind.BOUNDARY,)
    assert run.invalidated_observation_ids
    assert run.invalidated_act_ids


def test_quotation_and_interruption_changes_are_detected_selectively():
    phase4, corpus = _artifacts("What time is the hearing?")
    utterance = phase4.utterances[0]
    changed = utterance.model_copy(
        update={
            "quotation_status": UtteranceQuotationStatus.CANDIDATE,
            "interruption_status": UtteranceInterruptionStatus.INTERRUPTED,
        }
    )
    successor = phase4.model_copy(
        update={
            "corpus_id": typed_id("utterancecorpus", phase4.corpus_id, "structure"),
            "utterances": (changed,),
        }
    )
    run, _ = build_discourse_propagation(
        phase4, successor, corpus, created_at=NOW
    )
    impact = run.impacts[0]
    assert impact.change_kinds == (
        Phase5ChangeKind.QUOTATION_STRUCTURE,
        Phase5ChangeKind.INTERRUPTION_OR_CONTINUATION,
    )
    assert not impact.invalidated_act_ids
    assert impact.rebuild_relation_target_act_ids
