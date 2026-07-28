from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from ratiocinatus.phase2_contracts import ConfidenceMeasure, ConfidenceOrigin
from ratiocinatus.phase4_contracts import UtteranceReviewStatus
from ratiocinatus.utterance_relation_contracts import (
    ContinuationDisposition,
    ContinuationKind,
    ContinuationRelation,
    InterruptionKind,
    InterruptionRelation,
    PHASE4_RELATION_CONTRACT_MODELS,
    SpeakerConsistency,
    UtteranceRelationPolicy,
    UtteranceRelationRun,
)

NOW = datetime(2026, 7, 27, tzinfo=timezone.utc)
SHA = "0" * 64


def _confidence() -> ConfidenceMeasure:
    return ConfidenceMeasure(
        origin=ConfidenceOrigin.UNAVAILABLE,
        basis="contract test",
    )


def _continuation(
    suffix: str,
    predecessor: str,
    successor: str,
    intervening: str,
) -> ContinuationRelation:
    return ContinuationRelation(
        continuation_id="continuation_" + suffix * 32,
        utterance_corpus_id="utterancecorpus_" + "c" * 32,
        predecessor_utterance_id="utterance_" + predecessor * 32,
        successor_utterance_id="utterance_" + successor * 32,
        intervening_utterance_ids=("utterance_" + intervening * 32,),
        elapsed_gap_microseconds=10,
        speaker_consistency=SpeakerConsistency.SAME_ATTRIBUTION,
        kind=ContinuationKind.UNRESOLVED,
        confidence=_confidence(),
        disposition=ContinuationDisposition.UNRESOLVED,
        review_status=UtteranceReviewStatus.REVIEW_REQUIRED,
        integrity_sha256=SHA,
    )


def test_relation_contract_inventory_and_policy_are_strict() -> None:
    assert len(PHASE4_RELATION_CONTRACT_MODELS) == 7
    assert len(
        {model.__name__ for model in PHASE4_RELATION_CONTRACT_MODELS}
    ) == 7
    for model in PHASE4_RELATION_CONTRACT_MODELS:
        assert model.model_json_schema().get("additionalProperties") is False
    policy = UtteranceRelationPolicy()
    assert policy.semantic_continuation_inference == "prohibited"
    assert policy.intent_or_blame_inference == "prohibited"


def test_simultaneous_interruption_requires_overlap_evidence() -> None:
    with pytest.raises(ValidationError, match="requires overlap"):
        InterruptionRelation(
            interruption_id="interruption_" + "1" * 32,
            utterance_corpus_id="utterancecorpus_" + "c" * 32,
            interrupted_utterance_id="utterance_" + "a" * 32,
            interrupting_utterance_id="utterance_" + "b" * 32,
            interruption_onset_normalized_microseconds=100,
            kind=InterruptionKind.ACTUAL_SIMULTANEOUS,
            original_speaker_continues_underneath=True,
            original_utterance_resumes=False,
            temporal_evidence_references=("spkoverlap_" + "d" * 32,),
            confidence=_confidence(),
            review_status=UtteranceReviewStatus.REVIEW_REQUIRED,
            integrity_sha256=SHA,
        )


def test_continuation_cycles_are_rejected() -> None:
    with pytest.raises(ValidationError, match="cycle"):
        UtteranceRelationRun(
            relation_run_id="utterancerelations_" + "1" * 32,
            utterance_corpus_id="utterancecorpus_" + "c" * 32,
            utterance_run_id="utterancerun_" + "2" * 32,
            utterance_analysis_id="utteranceanalysis_" + "3" * 32,
            phase3_diarization_run_id="diarun_" + "4" * 32,
            policy=UtteranceRelationPolicy(),
            configuration_hash=SHA,
            adjacencies=(),
            overlaps=(),
            interruptions=(),
            continuations=(
                _continuation("5", "a", "b", "c"),
                _continuation("6", "b", "a", "d"),
            ),
            created_at=NOW,
            complete=True,
            integrity_sha256=SHA,
        )
