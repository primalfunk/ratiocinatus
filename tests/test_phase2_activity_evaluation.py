from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from ratiocinatus.activity_evaluation import (
    evaluate_speech_activity,
    merge_intervals,
    reference_from_line_schedule,
)
from ratiocinatus.addressing_contracts import MediaInterval, TimeDomain
from ratiocinatus.phase2_contracts import (
    SpeechActivityClassification,
    SpeechActivityReference,
    SpeechEvidenceProviderIdentity,
)


NOW = datetime(2000, 1, 1, tzinfo=timezone.utc)
SHA = "1" * 64


def interval(start: int, duration: int) -> MediaInterval:
    return MediaInterval(
        domain=TimeDomain.NORMALIZED_CORPUS,
        start_microseconds=start,
        duration_microseconds=duration,
    )


def test_merge_intervals_unions_overlap_and_adjacency() -> None:
    assert merge_intervals(
        [interval(20, 10), interval(0, 10), interval(10, 5)]
    ) == (interval(0, 15), interval(20, 10))


def test_duration_metrics_and_nearest_boundary_error_are_explicit() -> None:
    provider = SpeechEvidenceProviderIdentity(
        provider_id="local.test_vad",
        display_name="Test VAD",
        provider_version="1.0.0",
        local=True,
    )
    run = SimpleNamespace(
        complete=True,
        run_id="sarun_" + "2" * 32,
        provider=provider,
        request=SimpleNamespace(
            normalized_audio_sha256=SHA,
            normalized_audio_duration_microseconds=1_000,
        ),
        intervals=(
            SimpleNamespace(
                classification=SpeechActivityClassification.PROBABLE_SPEECH,
                normalized_audio_interval=interval(100, 300),
            ),
            SimpleNamespace(
                classification=SpeechActivityClassification.UNCERTAIN,
                normalized_audio_interval=interval(400, 100),
            ),
            SimpleNamespace(
                classification=SpeechActivityClassification.PROBABLE_SPEECH,
                normalized_audio_interval=interval(700, 200),
            ),
        ),
    )
    reference = SpeechActivityReference(
        reference_id="saref_" + "3" * 32,
        fixture_id="controlled",
        variant="unit",
        normalized_audio_sha256=SHA,
        normalized_audio_duration_microseconds=1_000,
        schedule_sha256="4" * 64,
        intervals=(interval(200, 300), interval(800, 100)),
        provenance="independently prepared unit reference",
    )

    report = evaluate_speech_activity(run, reference, generated_at=NOW)

    assert report.metrics.true_positive_microseconds == 300
    assert report.metrics.false_positive_microseconds == 200
    assert report.metrics.false_negative_microseconds == 100
    assert report.metrics.true_negative_microseconds == 400
    assert report.metrics.precision == pytest.approx(0.6)
    assert report.metrics.recall == pytest.approx(0.75)
    assert report.metrics.f1 == pytest.approx(2 / 3)
    assert report.metrics.mean_boundary_error_microseconds == 75
    assert report.metrics.median_boundary_error_microseconds == 100
    assert report.metrics.maximum_boundary_error_microseconds == 100
    assert report.uncertain_treatment == "evaluated_as_non_positive"

    malformed = report.model_dump(mode="python")
    malformed["metrics"]["true_positive_microseconds"] += 1
    with pytest.raises(ValidationError, match="confusion durations"):
        type(report).model_validate(malformed)


def test_reference_builder_rejects_schedule_endpoint_disagreement(
    tmp_path: Path,
) -> None:
    schedule = tmp_path / "schedule.json"
    schedule.write_text(
        '{"fixture_id":"fixture","lines":[{"start_microseconds":0,'
        '"end_microseconds":10,"duration_microseconds":9}]}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="endpoints disagree"):
        reference_from_line_schedule(
            schedule,
            variant="invalid",
            normalized_audio_sha256=SHA,
            normalized_audio_duration_microseconds=100,
        )


def test_evaluation_rejects_reference_for_different_audio() -> None:
    run = SimpleNamespace(
        complete=True,
        request=SimpleNamespace(
            normalized_audio_sha256=SHA,
            normalized_audio_duration_microseconds=100,
        ),
    )
    reference = SpeechActivityReference(
        reference_id="saref_" + "5" * 32,
        fixture_id="controlled",
        variant="wrong-audio",
        normalized_audio_sha256="6" * 64,
        normalized_audio_duration_microseconds=100,
        schedule_sha256="7" * 64,
        intervals=(interval(0, 10),),
        provenance="independently prepared unit reference",
    )
    with pytest.raises(ValueError, match="hashes differ"):
        evaluate_speech_activity(run, reference, generated_at=NOW)
