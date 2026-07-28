from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from ratiocinatus.cli import EXIT_INTEGRITY, EXIT_SUCCESS, main
from ratiocinatus.diarization_evaluation import (
    DiarizationEvaluationIntegrityError,
    create_temporal_reference,
    evaluate_diarization,
    evaluate_diarization_artifacts,
    validate_diarization_evaluation,
)
from ratiocinatus.diarization_evaluation_contracts import (
    DIARIZATION_EVALUATION_CONTRACT_MODELS,
    DiarizationScoringPolicy,
    ReferenceSpeechKind,
    TemporalReferenceBoundary,
    TemporalReferenceOverlap,
    TemporalReferenceTurn,
)
from ratiocinatus.kernel import canonical_bytes, canonical_hash, typed_id
from ratiocinatus.phase3_contracts import DiarizationProviderResponse

from test_phase3_clustering import (
    HAS_FFMPEG,
    ConflictedClusteringProvider,
    _prepare,
)

NOW = datetime(2000, 1, 1, tzinfo=timezone.utc)


def test_temporal_diarization_evaluation_schemas_are_closed() -> None:
    assert len(DIARIZATION_EVALUATION_CONTRACT_MODELS) == 10
    for model in DIARIZATION_EVALUATION_CONTRACT_MODELS:
        schema = model.model_json_schema()
        assert schema["title"] == model.__name__
        assert schema.get("additionalProperties") is False


def _reference(request, response, diarization):
    keys = ("controlled_local_a", "controlled_local_b")
    turns = tuple(
        TemporalReferenceTurn(
            reference_turn_id=typed_id(
                "diarefturn", diarization.run_id, ordinal
            ),
            reference_speaker_key=keys[ordinal],
            normalized_audio_interval=turn.normalized_audio_interval,
            speech_kind=ReferenceSpeechKind.PRIMARY_SPEECH,
            strata=(
                "controlled",
                "overlap" if ordinal else "clean_alternating",
            ),
            annotation_basis="Project-authored timing fixed before evaluation.",
        )
        for ordinal, turn in enumerate(response.turns)
    )
    first_end = (
        response.turns[0].normalized_audio_interval.start_microseconds
        + response.turns[0].normalized_audio_interval.duration_microseconds
    )
    second_start = (
        response.turns[1].normalized_audio_interval.start_microseconds
    )
    boundaries = (
        TemporalReferenceBoundary(
            reference_boundary_id=typed_id(
                "diarefboundary", diarization.run_id, "overlap-start"
            ),
            normalized_audio_microseconds=second_start,
            preceding_speaker_keys=(keys[0],),
            following_speaker_keys=keys,
            strata=("overlap",),
            annotation_basis="Controlled overlap entrance.",
        ),
        TemporalReferenceBoundary(
            reference_boundary_id=typed_id(
                "diarefboundary", diarization.run_id, "overlap-end"
            ),
            normalized_audio_microseconds=first_end,
            preceding_speaker_keys=keys,
            following_speaker_keys=(keys[1],),
            strata=("overlap",),
            annotation_basis="Controlled overlap exit.",
        ),
    )
    overlap = diarization.overlaps[0].normalized_audio_interval
    overlaps = (
        TemporalReferenceOverlap(
            reference_overlap_id=typed_id(
                "diarefoverlap", diarization.run_id, "controlled"
            ),
            normalized_audio_interval=overlap,
            reference_speaker_keys=keys,
            strata=("overlap",),
            annotation_basis="Controlled simultaneous speech interval.",
        ),
    )
    return create_temporal_reference(
        diarization,
        normalized_audio_duration_microseconds=(
            request.normalized_audio_duration_microseconds
        ),
        turns=turns,
        boundaries=boundaries,
        overlaps=overlaps,
        provenance=(
            "Project-authored controlled local-speaker timing reference.",
        ),
        created_at=NOW,
    )


def _relabeled(
    response: DiarizationProviderResponse,
) -> DiarizationProviderResponse:
    labels = ("SYSTEM_X", "SYSTEM_Y")
    observations = tuple(
        item.model_copy(update={"provider_speaker_label": labels[ordinal]})
        for ordinal, item in enumerate(response.observations)
    )
    turns = tuple(
        item.model_copy(update={"provider_speaker_label": labels[ordinal]})
        for ordinal, item in enumerate(response.turns)
    )
    normalized_hash = canonical_hash(
        {
            "request_id": response.request_id,
            "provider": response.provider.model_dump(mode="json"),
            "observations": [
                item.model_dump(mode="json") for item in observations
            ],
            "turns": [item.model_dump(mode="json") for item in turns],
            "overlaps": [
                item.model_dump(mode="json") for item in response.overlaps
            ],
            "embeddings": [
                item.model_dump(mode="json") for item in response.embeddings
            ],
        }
    )
    return response.model_copy(
        update={
            "observations": observations,
            "turns": turns,
            "normalized_evidence_sha256": normalized_hash,
        }
    )


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_exact_temporal_metrics_mapping_boundaries_overlap_and_strata(
    tmp_path: Path,
) -> None:
    request, response, diarization, _, _, _ = _prepare(
        tmp_path, ConflictedClusteringProvider()
    )
    reference = _reference(request, response, diarization)
    relabeled = _relabeled(response)
    evaluation = evaluate_diarization(
        diarization,
        relabeled,
        reference,
        policy=DiarizationScoringPolicy(collar_microseconds=0),
        generated_at=NOW,
    )

    assert evaluation.status == "complete"
    assert evaluation.metrics.diarization_error_rate == 0.0
    assert evaluation.metrics.missed_speech_microseconds == 0
    assert evaluation.metrics.false_alarm_microseconds == 0
    assert evaluation.metrics.speaker_confusion_microseconds == 0
    assert evaluation.metrics.speaker_change_precision == 1.0
    assert evaluation.metrics.speaker_change_recall == 1.0
    assert evaluation.metrics.boundary_mean_absolute_error_microseconds == 0.0
    assert evaluation.metrics.overlap_precision == 1.0
    assert evaluation.metrics.overlap_recall == 1.0
    assert {item.stratum for item in evaluation.strata} == {
        "clean_alternating",
        "controlled",
        "overlap",
    }
    assert {
        item.reference_speaker_key for item in evaluation.speaker_mapping
    } == {"controlled_local_a", "controlled_local_b"}
    validate_diarization_evaluation(
        evaluation, diarization, relabeled
    )


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_confusion_and_missed_overlap_are_separate_der_contributions(
    tmp_path: Path,
) -> None:
    request, response, diarization, _, _, _ = _prepare(
        tmp_path, ConflictedClusteringProvider()
    )
    reference = _reference(request, response, diarization)
    evaluation = evaluate_diarization(
        diarization,
        response,
        reference,
        policy=DiarizationScoringPolicy(collar_microseconds=0),
        generated_at=NOW,
    )

    assert evaluation.status == "warning"
    assert evaluation.metrics.diarization_error_rate > 0
    assert (
        evaluation.metrics.missed_speech_microseconds
        + evaluation.metrics.speaker_confusion_microseconds
        > 0
    )
    assert evaluation.metrics.false_alarm_microseconds == 0
    assert evaluation.metrics.speaker_change_recall == 0.0
    assert evaluation.metrics.overlap_precision == 1.0
    assert evaluation.metrics.overlap_recall == 1.0
    assert any("Speaker-confusion" in item for item in evaluation.findings)


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_persistence_cache_cli_and_corruption_refusal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    request, response, diarization, _, diarization_root, _ = _prepare(
        tmp_path, ConflictedClusteringProvider()
    )
    reference = _reference(request, response, diarization)
    reference_path = tmp_path / "temporal-reference.json"
    reference_path.write_bytes(canonical_bytes(reference))
    destination = tmp_path / "evaluations"

    evaluation, report, root, reused = evaluate_diarization_artifacts(
        diarization_root,
        reference_path,
        destination,
        policy=DiarizationScoringPolicy(collar_microseconds=0),
    )
    assert not reused
    validate_diarization_evaluation(
        evaluation, diarization, response, report
    )
    assert (root / "evaluation.json").is_file()
    assert (root / "report.json").is_file()
    assert (root / "report.md").is_file()
    cached = evaluate_diarization_artifacts(
        diarization_root,
        reference_path,
        destination,
        policy=DiarizationScoringPolicy(collar_microseconds=0),
    )
    assert cached[-1]
    assert cached[0] == evaluation

    assert main(
        [
            "--json",
            "diarization",
            "inspect-diarization-evaluation",
            str(root),
        ]
    ) == EXIT_SUCCESS
    assert evaluation.evaluation_id in capsys.readouterr().out
    assert main(
        [
            "--json",
            "diarization",
            "list-diarization-strata",
            str(root),
        ]
    ) == EXIT_SUCCESS
    assert "controlled" in capsys.readouterr().out
    assert main(
        [
            "--json",
            "diarization",
            "validate-diarization-evaluation",
            str(root),
            str(diarization_root),
        ]
    ) == EXIT_SUCCESS
    capsys.readouterr()

    (root / "report.md").write_text("corrupt", encoding="utf-8")
    assert main(
        [
            "diarization",
            "validate-diarization-evaluation",
            str(root),
            str(diarization_root),
        ]
    ) == EXIT_INTEGRITY
    assert "integrity failure" in capsys.readouterr().err


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_reference_lineage_bounds_mapping_limit_and_partial_cache_refuse(
    tmp_path: Path,
) -> None:
    request, response, diarization, _, diarization_root, _ = _prepare(
        tmp_path, ConflictedClusteringProvider()
    )
    reference = _reference(request, response, diarization)
    invalid = reference.model_copy(
        update={"source_artifact_sha256": "f" * 64}
    )
    with pytest.raises(
        DiarizationEvaluationIntegrityError, match="integrity|lineage"
    ):
        evaluate_diarization(diarization, response, invalid)

    with pytest.raises(
        DiarizationEvaluationIntegrityError, match="bounded size"
    ):
        evaluate_diarization(
            diarization,
            _relabeled(response),
            reference,
            policy=DiarizationScoringPolicy(maximum_mapping_speakers=1),
        )

    reference_path = tmp_path / "reference.json"
    reference_path.write_bytes(canonical_bytes(reference))
    _, _, root, _ = evaluate_diarization_artifacts(
        diarization_root,
        reference_path,
        tmp_path / "evaluation",
    )
    (root / "report.json").unlink()
    with pytest.raises(
        DiarizationEvaluationIntegrityError, match="cache.*incomplete"
    ):
        evaluate_diarization_artifacts(
            diarization_root,
            reference_path,
            tmp_path / "evaluation",
        )
