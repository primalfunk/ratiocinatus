from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from ratiocinatus.addressing_contracts import MediaInterval, TimeDomain
from ratiocinatus.cli import EXIT_SUCCESS, main
from ratiocinatus.phase2_contracts import (
    ConfidenceMeasure,
    ConfidenceOrigin,
    LanguageMode,
    PHASE2_CONTRACT_MODELS,
    ProviderTranscriptCandidate,
    ProviderTranscriptObservation,
    SpeechActivityClassification,
    SpeechActivityInterval,
    SpeechActivityPolicy,
    SpeechEvidenceCapability,
    SpeechEvidenceProviderCapabilities,
    SpeechEvidenceProviderIdentity,
    TimestampOrigin,
    TranscriptionPolicy,
)
from ratiocinatus.speech_providers import (
    SpeechProviderRegistry,
    SpeechProviderUnavailable,
)

NOW = datetime(2000, 1, 1, tzinfo=timezone.utc)


def unavailable(basis: str = "provider supplied no score") -> ConfidenceMeasure:
    return ConfidenceMeasure(
        value=None,
        origin=ConfidenceOrigin.UNAVAILABLE,
        basis=basis,
    )


def test_phase2_contract_schemas_are_closed() -> None:
    for model in PHASE2_CONTRACT_MODELS:
        schema = model.model_json_schema()
        assert schema["title"] == model.__name__
        assert schema.get("additionalProperties") is False


def test_confidence_never_fabricates_availability_or_calibration() -> None:
    assert unavailable().value is None
    with pytest.raises(ValidationError):
        ConfidenceMeasure(
            value=0.5,
            origin=ConfidenceOrigin.UNAVAILABLE,
            basis="not supplied",
        )
    with pytest.raises(ValidationError):
        ConfidenceMeasure(
            value=None,
            origin=ConfidenceOrigin.PROVIDER_NATIVE,
            basis="provider score",
        )
    with pytest.raises(ValidationError):
        ConfidenceMeasure(
            value=0.8,
            origin=ConfidenceOrigin.DERIVED,
            basis="threshold distance",
            calibrated=True,
        )


def test_policy_versions_and_language_configuration_are_strict() -> None:
    with pytest.raises(ValidationError):
        SpeechActivityPolicy(policy_version="9.0.0")
    with pytest.raises(ValidationError):
        SpeechActivityPolicy(
            speech_threshold=0.4,
            non_speech_threshold=0.5,
        )
    with pytest.raises(ValidationError):
        TranscriptionPolicy(language_mode=LanguageMode.EXPLICIT)
    with pytest.raises(ValidationError):
        TranscriptionPolicy(
            language_mode=LanguageMode.UNKNOWN,
            language="en",
        )


def test_capability_claims_are_internally_consistent() -> None:
    identity = SpeechEvidenceProviderIdentity(
        provider_id="test.activity",
        display_name="Test activity",
        provider_version="1",
        local=True,
    )
    with pytest.raises(ValidationError):
        SpeechEvidenceProviderCapabilities(
            identity=identity,
            capabilities=(SpeechEvidenceCapability.SPEECH_ACTIVITY,),
            available=True,
            word_timestamps=True,
            segment_timestamps=True,
        )


def test_speech_interval_requires_explicit_mapped_domains() -> None:
    kwargs = {
        "interval_id": "speech_" + "1" * 32,
        "corpus_id": "corpus_" + "2" * 32,
        "processing_chunk_id": "chunk_" + "3" * 32,
        "classification": SpeechActivityClassification.PROBABLE_SPEECH,
        "speech_presence_confidence": unavailable(),
        "start_boundary_id": "boundary_" + "4" * 32,
        "end_boundary_id": "boundary_" + "5" * 32,
    }
    interval = SpeechActivityInterval(
        source_interval=MediaInterval(
            domain=TimeDomain.SOURCE_MEDIA,
            start_microseconds=-10,
            duration_microseconds=100,
        ),
        normalized_audio_interval=MediaInterval(
            domain=TimeDomain.NORMALIZED_CORPUS,
            start_microseconds=0,
            duration_microseconds=100,
        ),
        **kwargs,
    )
    assert interval.source_interval.start_microseconds == -10
    with pytest.raises(ValidationError):
        SpeechActivityInterval(
            source_interval=interval.source_interval,
            normalized_audio_interval=MediaInterval(
                domain=TimeDomain.NORMALIZED_CORPUS,
                start_microseconds=0,
                duration_microseconds=99,
            ),
            **kwargs,
        )


def test_candidate_selection_cannot_be_implicit_or_contradictory() -> None:
    candidate = ProviderTranscriptCandidate(
        provider_candidate_id="candidate-1",
        proposed_text="possibly spoken",
        rank=1,
        text_confidence=unavailable(),
        selected=True,
        selection_reason="unit selection",
    )
    with pytest.raises(ValidationError):
        ProviderTranscriptObservation(
            observation_id="txobs_" + "1" * 32,
            speech_interval_ids=("speech_" + "2" * 32,),
            source_interval=MediaInterval(
                domain=TimeDomain.SOURCE_MEDIA,
                start_microseconds=0,
                duration_microseconds=100,
            ),
            normalized_audio_interval=MediaInterval(
                domain=TimeDomain.NORMALIZED_CORPUS,
                start_microseconds=0,
                duration_microseconds=100,
            ),
            processing_chunk_ids=("chunk_" + "3" * 32,),
            candidates=(candidate,),
            selected_candidate_id=None,
            timing_confidence=unavailable(),
            boundary_confidence=unavailable(),
        )


def test_provider_registry_and_capability_cli_are_conservative(capsys) -> None:
    registry = SpeechProviderRegistry.with_boundaries()
    transcription = registry.list(SpeechEvidenceCapability.TRANSCRIPTION)
    unavailable_transcription = next(
        item
        for item in transcription
        if item.identity.provider_id == "unconfigured.transcription"
    )
    assert not unavailable_transcription.available
    with pytest.raises(SpeechProviderUnavailable):
        registry.get("missing.provider")

    assert main(
        [
            "--json",
            "speech-provider",
            "inspect",
            "unconfigured.transcription",
        ]
    ) == EXIT_SUCCESS
    payload = json.loads(capsys.readouterr().out)
    assert payload["capabilities"] == ["transcription"]
    assert payload["available"] is False
    assert payload["identity"]["model_id"] is None

    assert main([
        "--json", "speech-provider", "inspect", "missing.provider"
    ]) == 4
    assert "speech provider unavailable" in capsys.readouterr().err
