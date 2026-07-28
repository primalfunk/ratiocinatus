from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from ratiocinatus.addressing_contracts import MediaInterval, TimeDomain
from ratiocinatus.kernel import canonical_bytes, canonical_hash, typed_id
from ratiocinatus.phase2_contracts import (
    ConfidenceMeasure,
    ConfidenceOrigin,
    ProviderTranscriptCandidate,
    ProviderTranscriptObservation,
    ProviderWordObservation,
    RawEvidenceDisposition,
    RawProviderEvidence,
    SpeechActivityClassification,
    SpeechActivityInterval,
    SpeechEvidenceProviderIdentity,
    TimestampOrigin,
    TranscriptionPolicy,
    TranscriptionProviderResponse,
    TranscriptionRequest,
)
from ratiocinatus.correction_contracts import (
    CORRECTION_CONTRACT_MODELS,
    CorrectionActor,
    CorrectionActorKind,
    CorrectionType,
    TranscriptCorrectionDraft,
    TranscriptSegmentProposal,
)
from ratiocinatus.corrections import (
    TranscriptCorrectionIntegrityError,
    _state_from_segment,
    apply_correction_batch,
    build_transcript_revision,
    prepare_correction_batch,
    validate_transcript_revision,
)
from ratiocinatus.transcript_assembly import (
    TranscriptAssemblyIntegrityError,
    _build_assembly,
    validate_transcript_assembly,
)
from ratiocinatus.transcription import (
    TranscriptionIntegrityError,
    validate_transcription_response,
)
from ratiocinatus.subtitle_contracts import (
    SUBTITLE_CONTRACT_MODELS,
    SubtitleCue,
    SubtitleExportManifest,
    SubtitleExportPolicy,
    SubtitleFormat,
    SubtitleSegmentationOrigin,
)
from ratiocinatus.subtitles import (
    SubtitleExportIntegrityError,
    export_subtitles,
    validate_subtitle_export,
)
from ratiocinatus.evaluation_contracts import (
    EVALUATION_CONTRACT_MODELS,
    EvaluationAvailability,
    EvaluationStratum,
    ReferenceTranscript,
    ReferenceTranscriptSegment,
)
from ratiocinatus.transcript_evaluation import (
    TranscriptEvaluationIntegrityError,
    evaluate_transcript,
    validate_transcript_evaluation,
)
from ratiocinatus.transcript_contracts import (
    LowConfidenceClassification,
    TRANSCRIPT_CONTRACT_MODELS,
    TranscriptAssemblyPolicy,
    TranscriptAssemblyStatus,
)

NOW = datetime(2000, 1, 1, tzinfo=timezone.utc)


def confidence(
    value: float | None,
    *,
    origin: ConfidenceOrigin = ConfidenceOrigin.PROVIDER_NATIVE,
    basis: str = "test provider output",
) -> ConfidenceMeasure:
    return ConfidenceMeasure(
        value=value,
        origin=origin if value is not None else ConfidenceOrigin.UNAVAILABLE,
        basis=basis,
    )


def evidence():
    corpus_id = typed_id("corpus", "assembly-test")
    source_id = typed_id("src", "assembly-test")
    speech_id = typed_id("speech", "assembly-test")
    observation_id = typed_id("txobs", "assembly-test")
    provider = SpeechEvidenceProviderIdentity(
        provider_id="test.transcriber",
        display_name="Test transcriber",
        provider_version="1.0.0",
        model_id="test-model",
        model_version="1",
        local=True,
    )
    normalized = MediaInterval(
        domain=TimeDomain.NORMALIZED_CORPUS,
        start_microseconds=1_000_000,
        duration_microseconds=2_000_000,
    )
    source = MediaInterval(
        domain=TimeDomain.SOURCE_MEDIA,
        start_microseconds=1_250_000,
        duration_microseconds=2_000_000,
    )
    activity = SpeechActivityInterval(
        interval_id=speech_id,
        corpus_id=corpus_id,
        source_interval=source,
        normalized_audio_interval=normalized,
        processing_chunk_id=typed_id("chunk", "assembly-test"),
        classification=SpeechActivityClassification.PROBABLE_SPEECH,
        speech_presence_confidence=confidence(0.95),
        start_boundary_id=typed_id("boundary", "start"),
        end_boundary_id=typed_id("boundary", "end"),
    )
    request = TranscriptionRequest(
        request_id=typed_id("txreq", "assembly-test"),
        requested_at=NOW,
        corpus_id=corpus_id,
        source_id=source_id,
        normalized_audio_sha256="1" * 64,
        normalized_audio_duration_microseconds=4_000_000,
        source_mapping_offset_microseconds=250_000,
        speech_activity_run_id=typed_id("sarun", "assembly-test"),
        speech_interval_ids=(speech_id,),
        speech_intervals=(activity,),
        policy=TranscriptionPolicy(),
        provider=provider,
        configuration_hash="2" * 64,
    )
    words = (
        ProviderWordObservation(
            provider_word_id="word-0",
            surface_text=" Hello",
            sequence_position=0,
            source_interval=MediaInterval(
                domain=TimeDomain.SOURCE_MEDIA,
                start_microseconds=1_250_000,
                duration_microseconds=1_000_000,
            ),
            normalized_audio_interval=MediaInterval(
                domain=TimeDomain.NORMALIZED_CORPUS,
                start_microseconds=1_000_000,
                duration_microseconds=1_000_000,
            ),
            timestamp_origin=TimestampOrigin.PROVIDER_NATIVE,
            recognition_confidence=confidence(0.9),
            timing_confidence=confidence(
                None, basis="provider supplies no word timing confidence"
            ),
        ),
        ProviderWordObservation(
            provider_word_id="word-1",
            surface_text=" world",
            sequence_position=1,
            source_interval=MediaInterval(
                domain=TimeDomain.SOURCE_MEDIA,
                start_microseconds=2_250_000,
                duration_microseconds=1_000_000,
            ),
            normalized_audio_interval=MediaInterval(
                domain=TimeDomain.NORMALIZED_CORPUS,
                start_microseconds=2_000_000,
                duration_microseconds=1_000_000,
            ),
            timestamp_origin=TimestampOrigin.PROVIDER_NATIVE,
            recognition_confidence=confidence(0.4),
            timing_confidence=confidence(
                None, basis="provider supplies no word timing confidence"
            ),
        ),
    )
    candidate = ProviderTranscriptCandidate(
        provider_candidate_id="candidate-0",
        proposed_text="  Hello   world  ",
        language="en",
        rank=1,
        text_confidence=confidence(0.8, origin=ConfidenceOrigin.DERIVED),
        selected=True,
        selection_reason="single provider candidate",
        words=words,
    )
    observation = ProviderTranscriptObservation(
        observation_id=observation_id,
        speech_interval_ids=(speech_id,),
        source_interval=source,
        normalized_audio_interval=normalized,
        processing_chunk_ids=(activity.processing_chunk_id,),
        provider_segment_reference="segment-0",
        candidates=(candidate,),
        selected_candidate_id=candidate.provider_candidate_id,
        timing_confidence=confidence(
            None, basis="provider supplies no segment timing confidence"
        ),
        boundary_confidence=confidence(
            None, basis="provider supplies no boundary confidence"
        ),
    )
    response = TranscriptionProviderResponse(
        response_id=typed_id("txresponse", "assembly-test"),
        request_id=request.request_id,
        provider=provider,
        started_at=NOW,
        completed_at=NOW,
        observations=(observation,),
        normalized_evidence_sha256="3" * 64,
        raw_evidence=RawProviderEvidence(
            disposition=RawEvidenceDisposition.UNAVAILABLE,
            explanation="unit test",
        ),
        complete=True,
    )
    return request, response


def test_transcription_temporal_confidence_and_lineage_negative_proofs():
    request, response = evidence()
    observation = response.observations[0]

    outside_normalized = observation.normalized_audio_interval.model_copy(
        update={"duration_microseconds": 4_000_000}
    )
    outside_source = observation.source_interval.model_copy(
        update={"duration_microseconds": 4_000_000}
    )
    outside = observation.model_copy(
        update={
            "normalized_audio_interval": outside_normalized,
            "source_interval": outside_source,
        }
    )
    outside_hash = canonical_hash(
        {
            "request_id": request.request_id,
            "provider": response.provider.model_dump(mode="json"),
            "observations": [outside.model_dump(mode="json")],
        }
    )
    with pytest.raises(
        TranscriptionIntegrityError, match="exceeds normalized audio"
    ):
        validate_transcription_response(
            response.model_copy(
                update={
                    "observations": (outside,),
                    "normalized_evidence_sha256": outside_hash,
                }
            ),
            request,
            Path("."),
        )

    duplicate = observation.model_copy(
        update={"observation_id": typed_id("txobs", "duplicate")}
    )
    duplicate_hash = canonical_hash(
        {
            "request_id": request.request_id,
            "provider": response.provider.model_dump(mode="json"),
            "observations": [
                observation.model_dump(mode="json"),
                duplicate.model_dump(mode="json"),
            ],
        }
    )
    with pytest.raises(
        TranscriptionIntegrityError, match="overlap or regress"
    ):
        validate_transcription_response(
            response.model_copy(
                update={
                    "observations": (observation, duplicate),
                    "normalized_evidence_sha256": duplicate_hash,
                }
            ),
            request,
            Path("."),
        )

    with pytest.raises(
        TranscriptionIntegrityError, match="another request"
    ):
        validate_transcription_response(
            response.model_copy(
                update={"request_id": typed_id("txreq", "incompatible")}
            ),
            request,
            Path("."),
        )

    reversed_words = observation.model_dump(mode="json")
    reversed_words["candidates"][0]["words"][1][
        "normalized_audio_interval"
    ]["start_microseconds"] = 1_500_000
    reversed_words["candidates"][0]["words"][1][
        "source_interval"
    ]["start_microseconds"] = 1_750_000
    with pytest.raises(ValueError, match="words must be ordered"):
        ProviderTranscriptObservation.model_validate_json(canonical_bytes(reversed_words))

    with pytest.raises(ValueError, match="less than or equal to 1"):
        ConfidenceMeasure(
            value=1.01,
            origin=ConfidenceOrigin.PROVIDER_NATIVE,
            basis="invalid qualification value",
        )

def test_canonical_promotion_is_stable_and_confidence_is_machine_readable():
    request, response = evidence()
    policy = TranscriptAssemblyPolicy()
    first = _build_assembly(
        request,
        response,
        audio_stream_id=typed_id("stream", "audio"),
        audio_stream_index=1,
        policy=policy,
    )
    second = _build_assembly(
        request,
        response,
        audio_stream_id=typed_id("stream", "audio"),
        audio_stream_index=1,
        policy=policy,
    )

    assert first == second
    assert first.status == TranscriptAssemblyStatus.REVIEW_REQUIRED
    assert first.segments[0].normalized_text == "Hello world"
    assert len(first.words) == 2
    assert first.words[0].recognition_confidence.value == 0.9
    classifications = [
        item.classification for item in first.low_confidence_regions
    ]
    assert classifications.count(
        LowConfidenceClassification.UNAVAILABLE_TEMPORAL_ALIGNMENT_CONFIDENCE
    ) == 3
    assert (
        LowConfidenceClassification.UNCERTAIN_SEGMENT_BOUNDARY
        in classifications
    )
    assert (
        LowConfidenceClassification.LOW_TRANSCRIPTION_CONFIDENCE
        in classifications
    )
    validate_transcript_assembly(
        first, request=request, response=response
    )


def test_unresolved_observation_blocks_without_inventing_text():
    request, response = evidence()
    unresolved = response.observations[0].model_copy(
        update={
            "candidates": (),
            "selected_candidate_id": None,
        }
    )
    response = response.model_copy(update={"observations": (unresolved,)})
    assembly = _build_assembly(
        request,
        response,
        audio_stream_id=typed_id("stream", "audio"),
        audio_stream_index=1,
        policy=TranscriptAssemblyPolicy(),
    )

    assert not assembly.segments
    assert not assembly.words
    assert assembly.status == TranscriptAssemblyStatus.BLOCKED
    assert assembly.low_confidence_regions[0].classification == (
        LowConfidenceClassification.MISSING_OUTPUT
    )
    assert assembly.low_confidence_regions[0].blocks_downstream_use
    validate_transcript_assembly(assembly)


def test_integrity_change_is_rejected():
    request, response = evidence()
    assembly = _build_assembly(
        request,
        response,
        audio_stream_id=typed_id("stream", "audio"),
        audio_stream_index=1,
        policy=TranscriptAssemblyPolicy(),
    )
    altered = assembly.model_copy(
        update={"validation_findings": ("silently altered",)}
    )
    with pytest.raises(
        TranscriptAssemblyIntegrityError, match="integrity hash"
    ):
        validate_transcript_assembly(altered)

def test_transcript_contract_schemas_are_closed():
    for model in TRANSCRIPT_CONTRACT_MODELS:
        schema = model.model_json_schema()
        assert schema["title"] == model.__name__
        assert schema.get("additionalProperties") is False


def test_information_regions_remain_machine_readable_without_forcing_review():
    request, response = evidence()
    assembly = _build_assembly(
        request,
        response,
        audio_stream_id=typed_id("stream", "audio"),
        audio_stream_index=1,
        policy=TranscriptAssemblyPolicy(
            minimum_word_confidence=0.0,
            review_unavailable_text_confidence=False,
            review_unavailable_timing_confidence=False,
            review_uncertain_boundaries=False,
        ),
    )

    assert assembly.low_confidence_regions
    assert not any(
        item.review_recommended
        for item in assembly.low_confidence_regions
    )
    assert assembly.status == TranscriptAssemblyStatus.COMPLETE
    validate_transcript_assembly(assembly)

def replacement_draft(assembly, *, prior=None):
    current = _state_from_segment(assembly)[0]
    prior = prior or current
    return TranscriptCorrectionDraft(
        target_version_id=assembly.version.version_id,
        correction_type=CorrectionType.REPLACEMENT,
        target_artifact_ids=(current.artifact_id,),
        prior_values=(prior,),
        proposed_values=(
            TranscriptSegmentProposal(
                source_interval=current.source_interval,
                normalized_audio_interval=current.normalized_audio_interval,
                text="Corrected words",
                normalized_text="Corrected words",
                language_claim=current.language_claim,
            ),
        ),
        affected_source_interval=current.source_interval,
        actor=CorrectionActor(
            kind=CorrectionActorKind.HUMAN,
            actor_id="reviewer-1",
            display_name="Controlled reviewer",
        ),
        corrected_at=NOW,
        reason="Correct the controlled transcript text.",
        evidence_or_review_references=("review:test-1",),
    )


def test_append_only_replacement_creates_successor_and_views():
    request, response = evidence()
    assembly = _build_assembly(
        request,
        response,
        audio_stream_id=typed_id("stream", "audio"),
        audio_stream_index=1,
        policy=TranscriptAssemblyPolicy(),
    )
    original_bytes = assembly.model_dump_json()
    batch = prepare_correction_batch(
        assembly.version.version_id,
        (replacement_draft(assembly),),
    )
    revision, report = build_transcript_revision(assembly, batch)

    assert assembly.model_dump_json() == original_bytes
    assert revision.version.version_kind == "corrected"
    assert revision.version.predecessor_version_id == assembly.version.version_id
    assert revision.original_machine_view.rendered_text.strip() == "Hello   world"
    assert revision.current_corrected_view.rendered_text == "Corrected words"
    assert not revision.current_corrected_view.retained_word_ids
    assert revision.corrections[0].actor.kind == CorrectionActorKind.HUMAN
    assert revision.corrections[0].resulting_version_id == revision.version.version_id
    assert revision.difference_report.entries[0].prior_values[0].text.strip() == (
        "Hello   world"
    )
    assert report.human_correction_count == 1
    assert report.automated_correction_count == 0
    validate_transcript_revision(revision, assembly=assembly)


def test_stale_prior_value_and_unknown_version_are_rejected():
    request, response = evidence()
    assembly = _build_assembly(
        request,
        response,
        audio_stream_id=typed_id("stream", "audio"),
        audio_stream_index=1,
        policy=TranscriptAssemblyPolicy(),
    )
    prior = _state_from_segment(assembly)[0].model_copy(
        update={"text": "stale text"}
    )
    batch = prepare_correction_batch(
        assembly.version.version_id,
        (replacement_draft(assembly, prior=prior),),
    )
    with pytest.raises(
        TranscriptCorrectionIntegrityError, match="stale or incorrect"
    ):
        build_transcript_revision(assembly, batch)

    conflicting = prepare_correction_batch(
        assembly.version.version_id,
        (replacement_draft(assembly), replacement_draft(assembly)),
    )
    with pytest.raises(
        TranscriptCorrectionIntegrityError, match="conflicting target history"
    ):
        build_transcript_revision(assembly, conflicting)
    wrong = batch.model_copy(
        update={"target_version_id": typed_id("txversion", "unknown")}
    )
    with pytest.raises(
        TranscriptCorrectionIntegrityError, match="batch identity|unknown"
    ):
        build_transcript_revision(assembly, wrong)

def test_correction_contract_schemas_are_closed():
    for model in CORRECTION_CONTRACT_MODELS:
        schema = model.model_json_schema()
        assert schema["title"] == model.__name__
        assert schema.get("additionalProperties") is False


def test_automated_actor_requires_process_version():
    with pytest.raises(ValueError, match="process version"):
        CorrectionActor(
            kind=CorrectionActorKind.AUTOMATED_PROCESS,
            actor_id="auto-1",
            display_name="Automated correction",
        )

def test_supported_correction_shapes_apply_without_mutating_machine_state():
    request, response = evidence()
    assembly = _build_assembly(
        request,
        response,
        audio_stream_id=typed_id("stream", "audio"),
        audio_stream_index=1,
        policy=TranscriptAssemblyPolicy(),
    )
    prior = _state_from_segment(assembly)[0]
    normalized = prior.normalized_audio_interval
    source = prior.source_interval

    split = (
        TranscriptSegmentProposal(
            source_interval=source.model_copy(
                update={"duration_microseconds": 1_000_000}
            ),
            normalized_audio_interval=normalized.model_copy(
                update={"duration_microseconds": 1_000_000}
            ),
            text="Hello",
            normalized_text="Hello",
            language_claim=prior.language_claim,
        ),
        TranscriptSegmentProposal(
            source_interval=source.model_copy(
                update={
                    "start_microseconds": source.start_microseconds + 1_000_000,
                    "duration_microseconds": 1_000_000,
                }
            ),
            normalized_audio_interval=normalized.model_copy(
                update={
                    "start_microseconds": (
                        normalized.start_microseconds + 1_000_000
                    ),
                    "duration_microseconds": 1_000_000,
                }
            ),
            text="world",
            normalized_text="world",
            language_claim=prior.language_claim,
        ),
    )
    boundary = TranscriptSegmentProposal(
        source_interval=source.model_copy(
            update={
                "start_microseconds": source.start_microseconds + 100_000,
                "duration_microseconds": 1_800_000,
            }
        ),
        normalized_audio_interval=normalized.model_copy(
            update={
                "start_microseconds": normalized.start_microseconds + 100_000,
                "duration_microseconds": 1_800_000,
            }
        ),
        text=prior.text,
        normalized_text=prior.normalized_text,
        language_claim=prior.language_claim,
    )
    same = dict(
        source_interval=source,
        normalized_audio_interval=normalized,
        text=prior.text,
        normalized_text=prior.normalized_text,
        language_claim=prior.language_claim,
    )
    insertion = TranscriptSegmentProposal(
        source_interval=source.model_copy(
            update={
                "start_microseconds": 350_000,
                "duration_microseconds": 500_000,
            }
        ),
        normalized_audio_interval=normalized.model_copy(
            update={
                "start_microseconds": 100_000,
                "duration_microseconds": 500_000,
            }
        ),
        text="Inserted text",
        normalized_text="Inserted text",
        language_claim="en",
    )
    cases = (
        (CorrectionType.INSERTION, (), (insertion,), insertion.source_interval, 2),
        (CorrectionType.DELETION, (prior,), (), source, 0),
        (CorrectionType.SPLIT, (prior,), split, source, 2),
        (CorrectionType.BOUNDARY_ADJUSTMENT, (prior,), (boundary,), source, 1),
        (
            CorrectionType.LANGUAGE_CORRECTION,
            (prior,),
            (TranscriptSegmentProposal(**{**same, "language_claim": "fr"}),),
            source,
            1,
        ),
        (
            CorrectionType.NORMALIZATION_ONLY,
            (prior,),
            (TranscriptSegmentProposal(**{**same, "normalized_text": "Hello  world"}),),
            source,
            1,
        ),
        (
            CorrectionType.UNCERTAINTY_ANNOTATION,
            (prior,),
            (TranscriptSegmentProposal(**{**same, "uncertainty_annotation": "review pronunciation"}),),
            source,
            1,
        ),
    )
    for kind, prior_values, proposed, affected, expected_count in cases:
        draft = TranscriptCorrectionDraft(
            target_version_id=assembly.version.version_id,
            correction_type=kind,
            target_artifact_ids=(prior.artifact_id,),
            prior_values=prior_values,
            proposed_values=proposed,
            affected_source_interval=affected,
            actor=CorrectionActor(
                kind=CorrectionActorKind.HUMAN,
                actor_id="shape-reviewer",
                display_name="Shape reviewer",
            ),
            corrected_at=NOW,
            reason=f"Exercise {kind.value} correction shape.",
            evidence_or_review_references=(f"review:{kind.value}",),
        )
        batch = prepare_correction_batch(
            assembly.version.version_id, (draft,)
        )
        revision, _ = build_transcript_revision(assembly, batch)
        assert len(revision.current_corrected_view.segments) == expected_count
        assert revision.original_machine_view.segments == (
            _state_from_segment(assembly)
        )

def test_retained_alternative_candidate_can_be_restored_explicitly():
    request, response = evidence()
    observation = response.observations[0]
    selected = observation.candidates[0]
    alternative = selected.model_copy(
        update={
            "provider_candidate_id": "candidate-alternative",
            "proposed_text": "Hallo world",
            "selected": False,
            "selection_reason": None,
        }
    )
    response = response.model_copy(
        update={
            "observations": (
                observation.model_copy(
                    update={"candidates": (selected, alternative)}
                ),
            )
        }
    )
    assembly = _build_assembly(
        request,
        response,
        audio_stream_id=typed_id("stream", "audio"),
        audio_stream_index=1,
        policy=TranscriptAssemblyPolicy(),
    )
    prior = _state_from_segment(assembly)[0]
    draft = TranscriptCorrectionDraft(
        target_version_id=assembly.version.version_id,
        correction_type=CorrectionType.RESTORE_EARLIER_CANDIDATE,
        target_artifact_ids=(prior.artifact_id,),
        prior_values=(prior,),
        proposed_values=(
            TranscriptSegmentProposal(
                source_interval=prior.source_interval,
                normalized_audio_interval=prior.normalized_audio_interval,
                text="Hallo world",
                normalized_text="Hallo world",
                language_claim=prior.language_claim,
                restored_candidate_id="candidate-alternative",
            ),
        ),
        affected_source_interval=prior.source_interval,
        actor=CorrectionActor(
            kind=CorrectionActorKind.HUMAN,
            actor_id="candidate-reviewer",
            display_name="Candidate reviewer",
        ),
        corrected_at=NOW,
        reason="Restore the retained alternative for review.",
        evidence_or_review_references=("candidate:candidate-alternative",),
    )
    revision, _ = build_transcript_revision(
        assembly,
        prepare_correction_batch(
            assembly.version.version_id, (draft,)
        ),
    )
    assert revision.current_corrected_view.rendered_text == "Hallo world"
    assert revision.corrections[0].proposed_values[0].restored_candidate_id == (
        "candidate-alternative"
    )

def persist_assembly(root, assembly):
    root.mkdir(parents=True)
    (root / "assembly.json").write_bytes(canonical_bytes(assembly))
    (root / "version.json").write_bytes(canonical_bytes(assembly.version))
    for directory, identifier, values in (
        ("segments", "segment_id", assembly.segments),
        ("words", "word_id", assembly.words),
        ("low-confidence", "region_id", assembly.low_confidence_regions),
    ):
        for value in values:
            path = root / directory / f"{getattr(value, identifier)}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(canonical_bytes(value))


def test_subtitle_contract_schemas_are_closed():
    for model in SUBTITLE_CONTRACT_MODELS:
        schema = model.model_json_schema()
        assert schema["title"] == model.__name__
        assert schema.get("additionalProperties") is False


def test_machine_subtitles_split_on_words_persist_and_detect_corruption(tmp_path):
    request, response = evidence()
    assembly = _build_assembly(
        request,
        response,
        audio_stream_id=typed_id("stream", "audio"),
        audio_stream_index=1,
        policy=TranscriptAssemblyPolicy(),
    )
    assembly_root = tmp_path / "assembly"
    persist_assembly(assembly_root, assembly)
    policy = SubtitleExportPolicy(
        maximum_cue_characters=10,
        maximum_line_characters=5,
        maximum_lines_per_cue=2,
    )
    manifest, report, export_root, reused = export_subtitles(
        assembly_root, tmp_path / "exports", policy=policy
    )

    invalid_timing = manifest.cues[0].model_dump(mode="json")
    invalid_timing["rounded_end_milliseconds"] = invalid_timing[
        "rounded_start_milliseconds"
    ]
    with pytest.raises(ValueError, match="rounded interval must be positive"):
        SubtitleCue.model_validate_json(canonical_bytes(invalid_timing))

    unsupported_version = manifest.model_dump(mode="json")
    unsupported_version["format_version"] = "9.0.0"
    with pytest.raises(ValueError, match="Input should be '1.0.0'"):
        SubtitleExportManifest.model_validate_json(
            canonical_bytes(unsupported_version)
        )
    assert not reused and report.valid
    assert len(manifest.cues) == 2
    assert all(
        cue.segmentation_origin
        == SubtitleSegmentationOrigin.PROVIDER_WORD_TIMESTAMPS
        for cue in manifest.cues
    )
    assert manifest.transcript_version_id == assembly.version.version_id
    assert manifest.view_kind.value == "original_machine"
    assert {item.subtitle_format for item in manifest.files} == {
        SubtitleFormat.WEBVTT,
        SubtitleFormat.SRT,
    }
    assert (export_root / "transcript.vtt").read_text(
        encoding="utf-8"
    ).startswith("WEBVTT\n")
    assert "00:00:01,000 --> 00:00:02,000" in (
        export_root / "transcript.srt"
    ).read_text(encoding="utf-8")
    assert export_subtitles(
        assembly_root, tmp_path / "exports", policy=policy
    )[3]
    validate_subtitle_export(manifest, export_root, assembly=assembly)
    with pytest.raises(
        SubtitleExportIntegrityError, match="report differs"
    ):
        validate_subtitle_export(
            manifest,
            export_root,
            report=report.model_copy(
                update={"cue_count": report.cue_count + 1}
            ),
        )

    (export_root / "transcript.srt").write_text(
        "corrupt", encoding="utf-8"
    )
    with pytest.raises(
        SubtitleExportIntegrityError, match="failed validation"
    ):
        export_subtitles(
            assembly_root, tmp_path / "exports", policy=policy
        )


def test_corrected_subtitles_declare_successor_and_withhold_changed_words(tmp_path):
    request, response = evidence()
    assembly = _build_assembly(
        request,
        response,
        audio_stream_id=typed_id("stream", "audio"),
        audio_stream_index=1,
        policy=TranscriptAssemblyPolicy(),
    )
    assembly_root = tmp_path / "assembly"
    persist_assembly(assembly_root, assembly)
    batch = prepare_correction_batch(
        assembly.version.version_id,
        (replacement_draft(assembly),),
    )
    batch_path = tmp_path / "batch.json"
    batch_path.write_bytes(canonical_bytes(batch))
    revision, _, revision_root, _ = apply_correction_batch(
        assembly_root, batch_path, tmp_path / "revisions"
    )
    manifest, report, export_root, _ = export_subtitles(
        assembly_root,
        tmp_path / "exports",
        revision_root=revision_root,
        view_kind=revision.current_corrected_view.view_kind,
    )

    assert report.valid
    assert manifest.revision_id == revision.revision_id
    assert manifest.transcript_version_id == revision.version.version_id
    assert manifest.view_kind.value == "current_corrected"
    assert manifest.cues[0].text == "Corrected words"
    assert not manifest.cues[0].retained_word_ids
    assert "Corrected words" in (
        export_root / "transcript.vtt"
    ).read_text(encoding="utf-8")


def evaluation_reference(assembly, *, text="Hello world"):
    segment = assembly.segments[0]
    return ReferenceTranscript(
        reference_id=typed_id(
            "txreference", assembly.assembly_id, text
        ),
        fixture_id="controlled-test",
        variant="clean",
        corpus_id=assembly.version.corpus_id,
        source_id=assembly.source_id,
        source_sha256="1" * 64,
        normalized_audio_sha256=assembly.normalized_audio_sha256,
        normalized_audio_duration_microseconds=(
            assembly.normalized_audio_duration_microseconds
        ),
        source_mapping_offset_microseconds=(
            assembly.source_mapping_offset_microseconds
        ),
        source_document_sha256="3" * 64,
        schedule_document_sha256="4" * 64,
        provenance="Project-authored test reference.",
        independence_statement=(
            "Written independently and never supplied to provider inference."
        ),
        segments=(
            ReferenceTranscriptSegment(
                reference_segment_id="reference-segment-1",
                source_interval=segment.source_interval,
                normalized_audio_interval=(
                    segment.normalized_audio_interval
                ),
                text=text,
                strata=(EvaluationStratum.CLEAN_SPEECH,),
            ),
        ),
    )


def test_evaluation_contract_schemas_are_closed():
    for model in EVALUATION_CONTRACT_MODELS:
        schema = model.model_json_schema()
        assert schema["title"] == model.__name__
        assert schema.get("additionalProperties") is False


def test_transcript_evaluation_persists_metrics_and_rejects_corruption(tmp_path):
    request, response = evidence()
    assembly = _build_assembly(
        request,
        response,
        audio_stream_id=typed_id("stream", "audio"),
        audio_stream_index=1,
        policy=TranscriptAssemblyPolicy(),
    )
    assembly_root = tmp_path / "assembly"
    persist_assembly(assembly_root, assembly)
    reference_path = tmp_path / "reference.json"
    reference_path.write_bytes(
        canonical_bytes(evaluation_reference(assembly))
    )

    report, root, reused = evaluate_transcript(
        assembly_root, reference_path, tmp_path / "evaluations"
    )

    assert not reused
    assert report.aggregate.word_error_rate == 0.0
    assert report.aggregate.character_error_rate == 0.0
    assert report.segment_timing.mean_start_error_microseconds == 0.0
    assert report.word_timing.availability == (
        EvaluationAvailability.UNAVAILABLE_REFERENCE
    )
    assert report.candidate_selection.availability == (
        EvaluationAvailability.UNAVAILABLE_REFERENCE
    )
    assert report.strata[0].stratum == EvaluationStratum.CLEAN_SPEECH
    assert evaluate_transcript(
        assembly_root, reference_path, tmp_path / "evaluations"
    )[2]
    validate_transcript_evaluation(report, assembly=assembly, root=root)

    (root / "report.md").write_text("corrupt", encoding="utf-8")
    with pytest.raises(
        TranscriptEvaluationIntegrityError, match="failed validation"
    ):
        evaluate_transcript(
            assembly_root, reference_path, tmp_path / "evaluations"
        )


def test_corrected_evaluation_reports_versioned_correction_impact(tmp_path):
    request, response = evidence()
    assembly = _build_assembly(
        request,
        response,
        audio_stream_id=typed_id("stream", "audio"),
        audio_stream_index=1,
        policy=TranscriptAssemblyPolicy(),
    )
    assembly_root = tmp_path / "assembly"
    persist_assembly(assembly_root, assembly)
    batch = prepare_correction_batch(
        assembly.version.version_id,
        (replacement_draft(assembly),),
    )
    batch_path = tmp_path / "batch.json"
    batch_path.write_bytes(canonical_bytes(batch))
    revision, _, revision_root, _ = apply_correction_batch(
        assembly_root, batch_path, tmp_path / "revisions"
    )
    subtitle, _, subtitle_root, _ = export_subtitles(
        assembly_root,
        tmp_path / "exports",
        revision_root=revision_root,
        view_kind=revision.current_corrected_view.view_kind,
    )
    reference_path = tmp_path / "reference.json"
    reference_path.write_bytes(
        canonical_bytes(evaluation_reference(assembly))
    )

    report, _, _ = evaluate_transcript(
        assembly_root,
        reference_path,
        tmp_path / "evaluations",
        revision_root=revision_root,
        view_kind=revision.current_corrected_view.view_kind,
        subtitle_export_root=subtitle_root,
    )

    assert report.transcript_version_id == revision.version.version_id
    assert report.subtitle_cues.export_id == subtitle.export_id
    assert report.subtitle_cues.valid
    assert report.correction_impact.availability == (
        EvaluationAvailability.AVAILABLE
    )
    assert report.correction_impact.original.word_error_rate == 0.0
    assert report.correction_impact.corrected.word_error_rate > 0.0


def test_transcript_evaluation_rejects_reference_from_another_source(tmp_path):
    request, response = evidence()
    assembly = _build_assembly(
        request,
        response,
        audio_stream_id=typed_id("stream", "audio"),
        audio_stream_index=1,
        policy=TranscriptAssemblyPolicy(),
    )
    assembly_root = tmp_path / "assembly"
    persist_assembly(assembly_root, assembly)
    reference = evaluation_reference(assembly).model_copy(
        update={"source_id": typed_id("src", "other")}
    )
    reference_path = tmp_path / "reference.json"
    reference_path.write_bytes(canonical_bytes(reference))

    with pytest.raises(
        TranscriptEvaluationIntegrityError, match="another assembly lineage"
    ):
        evaluate_transcript(
            assembly_root,
            reference_path,
            tmp_path / "evaluations",
        )
    wrong_audio = evaluation_reference(assembly).model_copy(
        update={"normalized_audio_sha256": "f" * 64}
    )
    reference_path.write_bytes(canonical_bytes(wrong_audio))
    with pytest.raises(
        TranscriptEvaluationIntegrityError, match="another assembly lineage"
    ):
        evaluate_transcript(
            assembly_root,
            reference_path,
            tmp_path / "evaluations",
        )