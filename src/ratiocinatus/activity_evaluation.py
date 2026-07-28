"""Duration-weighted evaluation of canonical speech-activity evidence."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import mean, median

from .addressing_contracts import MediaInterval, TimeDomain
from .kernel import typed_id
from .media import sha256_file
from .phase2_contracts import (
    SpeechActivityClassification,
    SpeechActivityEvaluationMetrics,
    SpeechActivityEvaluationReport,
    SpeechActivityReference,
    SpeechActivityRun,
)


def _bounds(interval: MediaInterval) -> tuple[int, int]:
    return (
        interval.start_microseconds,
        interval.start_microseconds + interval.duration_microseconds,
    )


def merge_intervals(
    intervals: list[MediaInterval] | tuple[MediaInterval, ...],
) -> tuple[MediaInterval, ...]:
    """Return ordered, non-overlapping normalized-corpus intervals."""

    bounds = sorted(_bounds(item) for item in intervals)
    merged: list[tuple[int, int]] = []
    for start, end in bounds:
        if start < 0 or end <= start:
            raise ValueError("evaluation interval bounds are invalid")
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return tuple(
        MediaInterval(
            domain=TimeDomain.NORMALIZED_CORPUS,
            start_microseconds=start,
            duration_microseconds=end - start,
        )
        for start, end in merged
    )


def reference_from_line_schedule(
    schedule_path: Path,
    *,
    variant: str,
    normalized_audio_sha256: str,
    normalized_audio_duration_microseconds: int,
) -> SpeechActivityReference:
    """Build a reference from a pre-existing public fixture line schedule."""

    resolved = schedule_path.resolve(strict=True)
    payload = json.loads(resolved.read_text(encoding="utf-8-sig"))
    fixture_id = payload.get("fixture_id")
    lines = payload.get("lines")
    if not isinstance(fixture_id, str) or not isinstance(lines, list):
        raise ValueError("line schedule must contain fixture_id and lines")
    intervals = []
    for item in lines:
        try:
            start = int(item["start_microseconds"])
            end = int(item["end_microseconds"])
            duration = int(item["duration_microseconds"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("line schedule contains an invalid line") from exc
        if end - start != duration:
            raise ValueError("line schedule duration and endpoints disagree")
        intervals.append(
            MediaInterval(
                domain=TimeDomain.NORMALIZED_CORPUS,
                start_microseconds=start,
                duration_microseconds=duration,
            )
        )
    merged = merge_intervals(intervals)
    schedule_hash = sha256_file(resolved)
    return SpeechActivityReference(
        reference_id=typed_id(
            "saref",
            fixture_id,
            variant,
            schedule_hash,
            normalized_audio_sha256,
        ),
        fixture_id=fixture_id,
        variant=variant,
        normalized_audio_sha256=normalized_audio_sha256,
        normalized_audio_duration_microseconds=(
            normalized_audio_duration_microseconds
        ),
        schedule_sha256=schedule_hash,
        intervals=merged,
        provenance=(
            "Project-authored line schedule generated before semantic VAD "
            "selection; adjacent and overlapping line intervals are unioned."
        ),
    )

def _duration(intervals: tuple[MediaInterval, ...]) -> int:
    return sum(item.duration_microseconds for item in intervals)


def _intersection_duration(
    left: tuple[MediaInterval, ...],
    right: tuple[MediaInterval, ...],
) -> int:
    total = 0
    left_index = 0
    right_index = 0
    while left_index < len(left) and right_index < len(right):
        left_start, left_end = _bounds(left[left_index])
        right_start, right_end = _bounds(right[right_index])
        total += max(0, min(left_end, right_end) - max(left_start, right_start))
        if left_end <= right_end:
            left_index += 1
        else:
            right_index += 1
    return total


def evaluate_speech_activity(
    run: SpeechActivityRun,
    reference: SpeechActivityReference,
    *,
    generated_at: datetime | None = None,
) -> SpeechActivityEvaluationReport:
    """Compare probable-speech duration with an independent reference."""

    if not run.complete:
        raise ValueError("cannot evaluate an incomplete speech activity run")
    if (
        run.request.normalized_audio_sha256
        != reference.normalized_audio_sha256
    ):
        raise ValueError("run and reference source hashes differ")
    if (
        run.request.normalized_audio_duration_microseconds
        != reference.normalized_audio_duration_microseconds
    ):
        raise ValueError("run and reference durations differ")

    predicted = merge_intervals(
        [
            item.normalized_audio_interval
            for item in run.intervals
            if item.classification
            == SpeechActivityClassification.PROBABLE_SPEECH
        ]
    )
    expected = merge_intervals(reference.intervals)
    true_positive = _intersection_duration(predicted, expected)
    predicted_duration = _duration(predicted)
    expected_duration = _duration(expected)
    false_positive = predicted_duration - true_positive
    false_negative = expected_duration - true_positive
    total = reference.normalized_audio_duration_microseconds
    true_negative = total - true_positive - false_positive - false_negative
    if true_negative < 0:
        raise ValueError("evaluation intervals exceed the reference timeline")

    precision_denominator = true_positive + false_positive
    recall_denominator = true_positive + false_negative
    precision = (
        true_positive / precision_denominator
        if precision_denominator
        else None
    )
    recall = (
        true_positive / recall_denominator if recall_denominator else None
    )
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None
        and recall is not None
        and precision + recall
        else None
    )

    predicted_boundaries = [
        position for interval in predicted for position in _bounds(interval)
    ]
    reference_boundaries = [
        position for interval in expected for position in _bounds(interval)
    ]
    errors = [
        min(abs(position - candidate) for candidate in reference_boundaries)
        for position in predicted_boundaries
    ]
    metrics = SpeechActivityEvaluationMetrics(
        true_positive_microseconds=true_positive,
        false_positive_microseconds=false_positive,
        false_negative_microseconds=false_negative,
        true_negative_microseconds=true_negative,
        precision=precision,
        recall=recall,
        f1=f1,
        mean_boundary_error_microseconds=mean(errors) if errors else None,
        median_boundary_error_microseconds=median(errors) if errors else None,
        maximum_boundary_error_microseconds=max(errors) if errors else None,
        predicted_speech_interval_count=len(predicted),
        reference_speech_interval_count=len(expected),
    )
    return SpeechActivityEvaluationReport(
        evaluation_id=typed_id(
            "saeval",
            run.run_id,
            reference.reference_id,
            metrics.model_dump(mode="json"),
        ),
        generated_at=generated_at or datetime.now(timezone.utc),
        run_id=run.run_id,
        reference=reference,
        provider=run.provider,
        metrics=metrics,
        findings=(
            "Metrics are duration-weighted on this controlled fixture and "
            "do not establish general-corpus performance.",
            "Uncertain and non-speech classifications are evaluated as "
            "non-positive; they are not promoted to speech.",
            "Boundary error pairs each predicted boundary with the nearest "
            "reference boundary and is not an onset/offset assignment score.",
        ),
    )
