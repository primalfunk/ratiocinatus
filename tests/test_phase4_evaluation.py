from __future__ import annotations

from pathlib import Path

import pytest

from ratiocinatus.kernel import canonical_hash, typed_id
from ratiocinatus.phase4_evaluation import (
    Phase4EvaluationIntegrityError,
    evaluate_phase4,
    load_phase4_evaluation,
    persist_phase4_evaluation,
    validate_phase4_evaluation,
)
from ratiocinatus.phase4_evaluation_contracts import (
    EvaluationMetricStatus,
    Phase4ControlledReference,
    Phase4EvaluationMetricKind,
    Phase4EvaluationStratum,
    Phase4ReferenceRelation,
    Phase4ReferenceUtterance,
)
from ratiocinatus.phase4_review import create_review_ledger
from ratiocinatus.utterance_relation_contracts import InterruptionKind

from test_phase3_clustering import HAS_FFMPEG
from test_phase3_speaker_transcript import NOW
from test_phase4_propagation_review import _artifact_set


def _seal(model, payload):
    provisional = model(**payload, integrity_sha256="0" * 64)
    return model(
        **payload,
        integrity_sha256=canonical_hash(
            provisional.model_dump(mode="json", exclude={"integrity_sha256"})
        ),
    )


def _reference(artifacts) -> Phase4ControlledReference:
    quotations = {
        item.quoting_utterance_id: item
        for item in artifacts.quotation.quotations
    }
    self_repairs = {
        item.utterance_id for item in artifacts.analysis.self_repairs
    }
    values = []
    ids = {}
    for utterance in artifacts.corpus.utterances:
        reference_id = typed_id(
            "refutterance", utterance.utterance_id, "controlled"
        )
        ids[utterance.utterance_id] = reference_id
        quotation = quotations.get(utterance.utterance_id)
        strata = {Phase4EvaluationStratum.CLEAN_SPEECH}
        if utterance.overlap_status.value != "none":
            strata.add(Phase4EvaluationStratum.OVERLAP)
        if utterance.completeness.value != "complete":
            strata.add(Phase4EvaluationStratum.INCOMPLETE_SPEECH)
        if quotation is not None:
            strata.add(Phase4EvaluationStratum.QUOTATION)
        values.append(
            _seal(
                Phase4ReferenceUtterance,
                {
                    "reference_utterance_id": reference_id,
                    "source_intervals": utterance.source_intervals,
                    "transcript_word_ids": tuple(
                        word_id
                        for component in utterance.components
                        for word_id in component.transcript_word_ids
                    ),
                    "reference_text": next(
                        item.text
                        for item in utterance.text_views
                        if item.kind.value == "display"
                    ),
                    "attribution_status": utterance.attribution.status,
                    "speaker_target_id": utterance.attribution.target_id,
                    "completeness": utterance.completeness,
                    "overlap_expected": (
                        utterance.overlap_status.value != "none"
                    ),
                    "self_repair_expected": (
                        utterance.utterance_id in self_repairs
                    ),
                    "quotation_type": (
                        quotation.quotation_type if quotation else None
                    ),
                    "quoted_text": (
                        quotation.quoted_span.quoted_text
                        if quotation
                        else None
                    ),
                    "quoted_speaker_target_id": (
                        quotation.quoted_speaker_target_id
                        if quotation
                        else None
                    ),
                    "strata": tuple(
                        sorted(strata, key=lambda item: item.value)
                    ),
                    "evidence_references": (
                        utterance.utterance_id,
                        *utterance.completeness_evidence_references,
                    ),
                },
            )
        )
    relations = []
    for item in artifacts.relations.interruptions:
        if item.interrupting_utterance_id is None:
            continue
        payload = {
            "reference_relation_id": typed_id(
                "refutterancerelation", item.interruption_id
            ),
            "kind": "interruption",
            "predecessor_reference_utterance_id": ids[
                item.interrupted_utterance_id
            ],
            "successor_reference_utterance_id": ids[
                item.interrupting_utterance_id
            ],
            "evidence_references": (item.interruption_id,),
        }
        relations.append(_seal(Phase4ReferenceRelation, payload))
    for item in artifacts.relations.continuations:
        payload = {
            "reference_relation_id": typed_id(
                "refutterancerelation", item.continuation_id
            ),
            "kind": "continuation",
            "predecessor_reference_utterance_id": ids[
                item.predecessor_utterance_id
            ],
            "successor_reference_utterance_id": ids[
                item.successor_utterance_id
            ],
            "evidence_references": (item.continuation_id,),
        }
        relations.append(_seal(Phase4ReferenceRelation, payload))
    payload = {
        "reference_id": typed_id(
            "phase4reference",
            artifacts.corpus.corpus_id,
            "synthetic-controlled",
        ),
        "source_id": artifacts.corpus.utterances[0].source_id,
        "utterances": tuple(values),
        "relations": tuple(relations),
        "prepared_by": "controlled-fixture-author",
        "prepared_at": NOW,
        "preparation_method": (
            "Source-addressed synthetic mechanics reference prepared "
            "separately from the evaluation function."
        ),
        "independent_of_system_output": False,
        "evidence_class": "synthetic_mechanics",
    }
    return _seal(Phase4ControlledReference, payload)


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_controlled_evaluation_is_complete_deterministic_and_stratified(
    tmp_path: Path,
) -> None:
    artifacts = _artifact_set(tmp_path)
    reference = _reference(artifacts)
    ledger = create_review_ledger(
        artifacts.corpus, artifacts.transcript_views, created_at=NOW
    )
    evaluation = evaluate_phase4(
        artifacts, reference, review_ledger=ledger, generated_at=NOW
    )
    repeated = evaluate_phase4(
        artifacts, reference, review_ledger=ledger, generated_at=NOW
    )
    assert repeated == evaluation
    assert {item.kind for item in evaluation.metrics} == set(
        Phase4EvaluationMetricKind
    )
    assert evaluation.matched_reference_count == len(reference.utterances)
    assert evaluation.strata
    assert evaluation.evidence_class == "synthetic_mechanics"
    validate_phase4_evaluation(
        evaluation, artifacts, reference, review_ledger=ledger
    )


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_evaluation_marks_ineligible_metrics_not_applicable(
    tmp_path: Path,
) -> None:
    artifacts = _artifact_set(tmp_path)
    evaluation = evaluate_phase4(
        artifacts, _reference(artifacts), generated_at=NOW
    )
    quoted_identity = next(
        item
        for item in evaluation.metrics
        if item.kind
        == Phase4EvaluationMetricKind.QUOTED_SPEAKER_ATTRIBUTION_ACCURACY
    )
    assert quoted_identity.status == EvaluationMetricStatus.NOT_APPLICABLE
    assert quoted_identity.value is None
    assert quoted_identity.denominator == 0


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_evaluation_persistence_replays_and_rejects_tampering(
    tmp_path: Path,
) -> None:
    artifacts = _artifact_set(tmp_path)
    reference = _reference(artifacts)
    evaluation = evaluate_phase4(
        artifacts, reference, generated_at=NOW
    )
    first = persist_phase4_evaluation(
        evaluation, artifacts, reference, tmp_path / "evaluation"
    )
    replay = persist_phase4_evaluation(
        evaluation, artifacts, reference, tmp_path / "evaluation"
    )
    assert not first[3]
    assert replay[3]
    assert load_phase4_evaluation(first[2]) == first[:2]
    tampered = evaluation.model_copy(
        update={"matched_reference_count": 0}
    )
    with pytest.raises(
        Phase4EvaluationIntegrityError, match="integrity is invalid"
    ):
        validate_phase4_evaluation(tampered, artifacts, reference)
