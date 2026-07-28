from __future__ import annotations

import pytest
from pydantic import ValidationError

from ratiocinatus.phase2_contracts import ConfidenceMeasure, ConfidenceOrigin
from ratiocinatus.phase4_contracts import (
    SpeechSourceType,
    UtteranceReviewStatus,
)
from ratiocinatus.quotation_contracts import (
    EmbeddedSpeechKind,
    EmbeddedSpeechSource,
    QUOTATION_CONTRACT_MODELS,
    QuotationDetectionPolicy,
)
from ratiocinatus.addressing_contracts import MediaInterval, TimeDomain


def test_quotation_contract_inventory_and_policy_are_strict() -> None:
    assert len(QUOTATION_CONTRACT_MODELS) == 6
    assert len({item.__name__ for item in QUOTATION_CONTRACT_MODELS}) == 6
    for model in QUOTATION_CONTRACT_MODELS:
        assert model.model_json_schema().get("additionalProperties") is False
    policy = QuotationDetectionPolicy()
    assert not policy.quotation_marks_alone_sufficient
    assert policy.automatic_quoted_identity_binding == "prohibited"
    assert policy.acoustic_attribution_mutation == "prohibited"


def test_embedded_speech_cannot_be_primary_participant_speech() -> None:
    confidence = ConfidenceMeasure(
        origin=ConfidenceOrigin.UNAVAILABLE,
        basis="contract test",
    )
    with pytest.raises(ValidationError, match="cannot be primary"):
        EmbeddedSpeechSource(
            embedded_source_id="embeddedspeech_" + "1" * 32,
            utterance_corpus_id="utterancecorpus_" + "2" * 32,
            utterance_id="utterance_" + "3" * 32,
            acoustic_attribution_id="utteranceattr_" + "4" * 32,
            source_type=SpeechSourceType.PRIMARY_SOURCE_PARTICIPANT,
            kind=EmbeddedSpeechKind.UNCERTAIN,
            marker_text="[unknown]",
            source_intervals=(MediaInterval(domain=TimeDomain.SOURCE_MEDIA, start_microseconds=0, duration_microseconds=10),),
            normalized_audio_intervals=(MediaInterval(domain=TimeDomain.NORMALIZED_CORPUS, start_microseconds=0, duration_microseconds=10),),
            evidence_references=("utterance_" + "3" * 32,),
            confidence=confidence,
            review_status=UtteranceReviewStatus.REVIEW_REQUIRED,
            integrity_sha256="0" * 64,
        )
