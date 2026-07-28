"""Controlled temporal diarization evaluation and qualification."""

from __future__ import annotations

import os
import uuid
from functools import lru_cache
from pathlib import Path

from datetime import datetime, timezone

from .diarization import (
    validate_diarization_response,
    validate_diarization_run,
)
from .diarization_evaluation_contracts import (
    ControlledDiarizationEvaluation,
    ControlledDiarizationEvaluationReport,
    DiarizationScoringPolicy,
    DiarizationSpeakerMapping,
    DiarizationStratumResult,
    DiarizationTemporalMetrics,
    ReferenceSpeechKind,
    TemporalDiarizationReference,
    TemporalReferenceBoundary,
    TemporalReferenceOverlap,
    TemporalReferenceTurn,
)
from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase3_contracts import (
    DiarizationProviderResponse,
    DiarizationRequest,
    DiarizationRun,
)


class DiarizationEvaluationIntegrityError(RuntimeError):
    """Controlled temporal reference, metrics, or persisted output is invalid."""


IntervalKey = tuple[int, int, str | None]
Interval = tuple[int, int]


def _atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.partial-{uuid.uuid4().hex}")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _seal(model, payload: dict):
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


def _integrity_valid(item) -> bool:
    payload = item.model_dump(mode="json", exclude={"integrity_sha256"})
    return canonical_hash(payload) == item.integrity_sha256


def _end(start: int, duration: int) -> int:
    return start + duration


def _merge_intervals(intervals: tuple[Interval, ...]) -> tuple[Interval, ...]:
    if not intervals:
        return ()
    merged: list[list[int]] = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return tuple((start, end) for start, end in merged)


def _duration(intervals: tuple[Interval, ...]) -> int:
    return sum(end - start for start, end in _merge_intervals(intervals))


def _intersection_duration(
    left: tuple[Interval, ...], right: tuple[Interval, ...]
) -> int:
    left = _merge_intervals(left)
    right = _merge_intervals(right)
    total = 0
    i = j = 0
    while i < len(left) and j < len(right):
        total += max(
            0,
            min(left[i][1], right[j][1])
            - max(left[i][0], right[j][0]),
        )
        if left[i][1] <= right[j][1]:
            i += 1
        else:
            j += 1
    return total


def _included_reference_kind(kind: ReferenceSpeechKind) -> bool:
    return kind not in {
        ReferenceSpeechKind.NON_LEXICAL_VOCALIZATION,
        ReferenceSpeechKind.BACKGROUND_SPEECH,
        ReferenceSpeechKind.AUDIENCE_REACTION,
    }


def create_temporal_reference(
    diarization: DiarizationRun,
    *,
    normalized_audio_duration_microseconds: int,
    turns: tuple[TemporalReferenceTurn, ...],
    boundaries: tuple[TemporalReferenceBoundary, ...] = (),
    overlaps: tuple[TemporalReferenceOverlap, ...] = (),
    provenance: tuple[str, ...],
    created_at: datetime | None = None,
) -> TemporalDiarizationReference:
    if not provenance:
        raise ValueError("temporal diarization reference requires provenance")
    payload = {
        "reference_id": typed_id(
            "diatempref",
            diarization.run_id,
            normalized_audio_duration_microseconds,
            tuple(item.model_dump(mode="json") for item in turns),
            tuple(item.model_dump(mode="json") for item in boundaries),
            tuple(item.model_dump(mode="json") for item in overlaps),
            provenance,
        ),
        "corpus_id": diarization.corpus_id,
        "diarization_run_id": diarization.run_id,
        "source_artifact_sha256": diarization.integrity_sha256,
        "normalized_audio_duration_microseconds": (
            normalized_audio_duration_microseconds
        ),
        "turns": turns,
        "boundaries": boundaries,
        "overlaps": overlaps,
        "provenance": provenance,
        "created_at": created_at or datetime.now(timezone.utc),
    }
    reference = _seal(TemporalDiarizationReference, payload)
    validate_temporal_reference(reference, diarization)
    return reference


def validate_temporal_reference(
    reference: TemporalDiarizationReference,
    diarization: DiarizationRun,
) -> None:
    if not _integrity_valid(reference):
        raise DiarizationEvaluationIntegrityError(
            "temporal diarization reference integrity is invalid"
        )
    if (
        reference.diarization_run_id != diarization.run_id
        or reference.corpus_id != diarization.corpus_id
        or reference.source_artifact_sha256 != diarization.integrity_sha256
    ):
        raise DiarizationEvaluationIntegrityError(
            "temporal diarization reference lineage is incompatible"
        )
    turns_by_speaker: dict[str, list[Interval]] = {}
    for turn in reference.turns:
        interval = turn.normalized_audio_interval
        turns_by_speaker.setdefault(turn.reference_speaker_key, []).append(
            (
                interval.start_microseconds,
                _end(
                    interval.start_microseconds,
                    interval.duration_microseconds,
                ),
            )
        )
    for overlap in reference.overlaps:
        interval = overlap.normalized_audio_interval
        expected = (
            interval.start_microseconds,
            _end(
                interval.start_microseconds,
                interval.duration_microseconds,
            ),
        )
        for speaker in overlap.reference_speaker_keys:
            covered = _intersection_duration(
                tuple(turns_by_speaker.get(speaker, ())), (expected,)
            )
            if covered != expected[1] - expected[0]:
                raise DiarizationEvaluationIntegrityError(
                    "reference overlap is not covered by each declared speaker"
                )


def _validate_response_lineage(
    response: DiarizationProviderResponse,
    diarization: DiarizationRun,
) -> None:
    if (
        response.response_id != diarization.response_id
        or response.request_id != diarization.request_id
        or response.provider != diarization.provider
        or not response.complete
    ):
        raise DiarizationEvaluationIntegrityError(
            "provider response lineage is incompatible"
        )
    normalized_hash = canonical_hash(
        {
            "request_id": response.request_id,
            "provider": response.provider.model_dump(mode="json"),
            "observations": [
                item.model_dump(mode="json") for item in response.observations
            ],
            "turns": [
                item.model_dump(mode="json") for item in response.turns
            ],
            "overlaps": [
                item.model_dump(mode="json") for item in response.overlaps
            ],
            "embeddings": [
                item.model_dump(mode="json") for item in response.embeddings
            ],
        }
    )
    if normalized_hash != response.normalized_evidence_sha256:
        raise DiarizationEvaluationIntegrityError(
            "provider response normalized evidence hash is invalid"
        )


def _reference_intervals(
    reference: TemporalDiarizationReference,
) -> tuple[IntervalKey, ...]:
    return tuple(
        (
            turn.normalized_audio_interval.start_microseconds,
            _end(
                turn.normalized_audio_interval.start_microseconds,
                turn.normalized_audio_interval.duration_microseconds,
            ),
            turn.reference_speaker_key,
        )
        for turn in reference.turns
        if _included_reference_kind(turn.speech_kind)
    )


def _system_intervals(
    response: DiarizationProviderResponse,
) -> tuple[IntervalKey, ...]:
    return tuple(
        (
            turn.normalized_audio_interval.start_microseconds,
            _end(
                turn.normalized_audio_interval.start_microseconds,
                turn.normalized_audio_interval.duration_microseconds,
            ),
            (
                turn.provider_speaker_label
                or f"__UNLABELED__:{turn.provider_turn_id}"
            ),
        )
        for turn in response.turns
    )


def _active(
    intervals: tuple[IntervalKey, ...], midpoint: float
) -> set[str | None]:
    return {
        key
        for start, end, key in intervals
        if start <= midpoint < end
    }


def _speaker_mapping(
    reference_intervals: tuple[IntervalKey, ...],
    system_intervals: tuple[IntervalKey, ...],
    *,
    maximum_speakers: int,
) -> tuple[DiarizationSpeakerMapping, ...]:
    reference_keys = sorted({key for _, _, key in reference_intervals if key})
    system_keys = sorted(
        {
            key
            for _, _, key in system_intervals
            if key and not key.startswith("__UNLABELED__:")
        }
    )
    unlabeled_keys = sorted(
        {key for _, _, key in system_intervals if key and key.startswith("__UNLABELED__:")}
    )
    if (
        len(reference_keys) > maximum_speakers
        or len(system_keys) > maximum_speakers
    ):
        raise DiarizationEvaluationIntegrityError(
            "controlled speaker mapping exceeds the declared bounded size"
        )
    breakpoints = sorted(
        {
            point
            for start, end, _ in (*reference_intervals, *system_intervals)
            for point in (start, end)
        }
    )
    weights: dict[tuple[str, str], int] = {}
    for start, end in zip(breakpoints, breakpoints[1:]):
        if end <= start:
            continue
        midpoint = (start + end) / 2
        refs = _active(reference_intervals, midpoint)
        systems = _active(system_intervals, midpoint)
        for system in systems:
            if system is None:
                continue
            for reference in refs:
                if reference is None:
                    continue
                pair = (system, reference)
                weights[pair] = weights.get(pair, 0) + end - start

    @lru_cache(maxsize=None)
    def choose(index: int, used_mask: int) -> tuple[int, tuple[int, ...]]:
        if index == len(system_keys):
            return 0, ()
        candidates = [-1, *range(len(reference_keys))]
        best_score = -1
        best_choices: tuple[int, ...] = ()
        for selected in candidates:
            if selected >= 0 and used_mask & (1 << selected):
                continue
            tail_score, tail_choices = choose(
                index + 1,
                used_mask | (1 << selected) if selected >= 0 else used_mask,
            )
            own = (
                weights.get(
                    (system_keys[index], reference_keys[selected]), 0
                )
                if selected >= 0
                else 0
            )
            score = own + tail_score
            choices = (selected, *tail_choices)
            if score > best_score or (
                score == best_score and choices < best_choices
            ):
                best_score = score
                best_choices = choices
        return best_score, best_choices

    _, choices = choose(0, 0)
    mappings = [
        DiarizationSpeakerMapping(
            system_speaker_key=system,
            reference_speaker_key=(
                reference_keys[selected] if selected >= 0 else None
            ),
            shared_duration_microseconds=(
                weights.get((system, reference_keys[selected]), 0)
                if selected >= 0
                else 0
            ),
        )
        for system, selected in zip(system_keys, choices)
    ]
    for key in unlabeled_keys:
        mappings.append(
            DiarizationSpeakerMapping(
                system_speaker_key=key,
                reference_speaker_key=None,
                shared_duration_microseconds=0,
            )
        )
    return tuple(mappings)


def _collars(
    reference: TemporalDiarizationReference,
    policy: DiarizationScoringPolicy,
) -> tuple[Interval, ...]:
    duration = reference.normalized_audio_duration_microseconds
    return _merge_intervals(
        tuple(
            (
                max(
                    0,
                    boundary.normalized_audio_microseconds
                    - policy.collar_microseconds
                    - boundary.uncertainty_microseconds,
                ),
                min(
                    duration,
                    boundary.normalized_audio_microseconds
                    + policy.collar_microseconds
                    + boundary.uncertainty_microseconds,
                ),
            )
            for boundary in reference.boundaries
        )
    )


def _inside(intervals: tuple[Interval, ...], midpoint: float) -> bool:
    return any(start <= midpoint < end for start, end in intervals)


def _score_speaker_time(
    reference_intervals: tuple[IntervalKey, ...],
    system_intervals: tuple[IntervalKey, ...],
    mapping: tuple[DiarizationSpeakerMapping, ...],
    *,
    duration: int,
    exclusions: tuple[Interval, ...],
    windows: tuple[Interval, ...] | None = None,
) -> dict[str, int]:
    lookup = {
        item.system_speaker_key: item.reference_speaker_key
        for item in mapping
    }
    breakpoints = {
        0,
        duration,
        *(
            point
            for start, end, _ in (*reference_intervals, *system_intervals)
            for point in (start, end)
        ),
        *(point for interval in exclusions for point in interval),
    }
    if windows is not None:
        breakpoints.update(point for interval in windows for point in interval)
    ordered = sorted(point for point in breakpoints if 0 <= point <= duration)
    totals = {
        "scored": 0,
        "reference": 0,
        "system": 0,
        "correct": 0,
        "missed": 0,
        "false_alarm": 0,
        "confusion": 0,
    }
    for start, end in zip(ordered, ordered[1:]):
        if end <= start:
            continue
        midpoint = (start + end) / 2
        if _inside(exclusions, midpoint):
            continue
        if windows is not None and not _inside(windows, midpoint):
            continue
        segment_duration = end - start
        references = {
            key
            for key in _active(reference_intervals, midpoint)
            if key is not None
        }
        system_raw = _active(system_intervals, midpoint)
        systems = {
            (
                lookup.get(key)
                if key is not None and lookup.get(key) is not None
                else f"UNMAPPED::{key or 'UNLABELED'}"
            )
            for key in system_raw
        }
        reference_count = len(references)
        system_count = len(systems)
        correct = len(references & systems)
        totals["scored"] += segment_duration
        totals["reference"] += reference_count * segment_duration
        totals["system"] += system_count * segment_duration
        totals["correct"] += correct * segment_duration
        totals["missed"] += max(0, reference_count - system_count) * (
            segment_duration
        )
        totals["false_alarm"] += max(0, system_count - reference_count) * (
            segment_duration
        )
        totals["confusion"] += (
            min(reference_count, system_count) - correct
        ) * segment_duration
    return totals


def _system_change_boundaries(
    diarization: DiarizationRun,
    response: DiarizationProviderResponse,
) -> tuple[int, ...]:
    labels = {
        item.observation_id: item.provider_speaker_label
        for item in response.observations
    }
    points = set()
    for boundary in diarization.boundaries:
        preceding = boundary.preceding_observation_id
        following = boundary.following_observation_id
        if (
            preceding is not None
            and following is not None
            and labels.get(preceding) != labels.get(following)
        ):
            points.add(boundary.normalized_audio_microseconds)
    return tuple(sorted(points))


def _match_boundaries(
    reference: tuple[TemporalReferenceBoundary, ...],
    system: tuple[int, ...],
    tolerance: int,
) -> tuple[int, tuple[int, ...]]:
    @lru_cache(maxsize=None)
    def match(i: int, j: int) -> tuple[int, int, tuple[int, ...]]:
        if i == len(reference) or j == len(system):
            return 0, 0, ()
        options = [match(i + 1, j), match(i, j + 1)]
        error = abs(
            reference[i].normalized_audio_microseconds - system[j]
        )
        allowed = tolerance + reference[i].uncertainty_microseconds
        if error <= allowed:
            count, total, errors = match(i + 1, j + 1)
            options.append((count + 1, total + error, (error, *errors)))
        return max(options, key=lambda item: (item[0], -item[1]))

    count, _, errors = match(0, 0)
    return count, errors


def _overlap_intervals_from_reference(
    reference: TemporalDiarizationReference,
) -> tuple[Interval, ...]:
    return tuple(
        (
            item.normalized_audio_interval.start_microseconds,
            _end(
                item.normalized_audio_interval.start_microseconds,
                item.normalized_audio_interval.duration_microseconds,
            ),
        )
        for item in reference.overlaps
    )


def _overlap_intervals_from_run(
    diarization: DiarizationRun,
) -> tuple[Interval, ...]:
    return tuple(
        (
            item.normalized_audio_interval.start_microseconds,
            _end(
                item.normalized_audio_interval.start_microseconds,
                item.normalized_audio_interval.duration_microseconds,
            ),
        )
        for item in diarization.overlaps
    )


def _build_metrics(
    diarization: DiarizationRun,
    response: DiarizationProviderResponse,
    reference: TemporalDiarizationReference,
    policy: DiarizationScoringPolicy,
    reference_intervals: tuple[IntervalKey, ...],
    system_intervals: tuple[IntervalKey, ...],
    mapping: tuple[DiarizationSpeakerMapping, ...],
) -> DiarizationTemporalMetrics:
    duration = reference.normalized_audio_duration_microseconds
    totals = _score_speaker_time(
        reference_intervals,
        system_intervals,
        mapping,
        duration=duration,
        exclusions=_collars(reference, policy),
    )
    if totals["reference"] <= 0:
        raise DiarizationEvaluationIntegrityError(
            "temporal reference has no scored speaker time"
        )
    denominator = totals["reference"]
    system_boundaries = _system_change_boundaries(diarization, response)
    matched, errors = _match_boundaries(
        reference.boundaries,
        system_boundaries,
        policy.boundary_tolerance_microseconds,
    )
    reference_overlap = _overlap_intervals_from_reference(reference)
    system_overlap = _overlap_intervals_from_run(diarization)
    reference_overlap_duration = _duration(reference_overlap)
    system_overlap_duration = _duration(system_overlap)
    overlap_intersection = _intersection_duration(
        reference_overlap, system_overlap
    )
    return DiarizationTemporalMetrics(
        scored_duration_microseconds=totals["scored"],
        reference_speaker_time_microseconds=denominator,
        system_speaker_time_microseconds=totals["system"],
        correct_speaker_time_microseconds=totals["correct"],
        missed_speech_microseconds=totals["missed"],
        false_alarm_microseconds=totals["false_alarm"],
        speaker_confusion_microseconds=totals["confusion"],
        diarization_error_rate=(
            totals["missed"]
            + totals["false_alarm"]
            + totals["confusion"]
        )
        / denominator,
        missed_speech_rate=totals["missed"] / denominator,
        false_alarm_rate=totals["false_alarm"] / denominator,
        speaker_confusion_rate=totals["confusion"] / denominator,
        reference_boundary_count=len(reference.boundaries),
        system_boundary_count=len(system_boundaries),
        matched_boundary_count=matched,
        speaker_change_precision=(
            matched / len(system_boundaries) if system_boundaries else None
        ),
        speaker_change_recall=(
            matched / len(reference.boundaries)
            if reference.boundaries
            else None
        ),
        boundary_mean_absolute_error_microseconds=(
            sum(errors) / len(errors) if errors else None
        ),
        boundary_maximum_error_microseconds=max(errors) if errors else None,
        reference_overlap_duration_microseconds=reference_overlap_duration,
        system_overlap_duration_microseconds=system_overlap_duration,
        overlap_intersection_duration_microseconds=overlap_intersection,
        overlap_precision=(
            overlap_intersection / system_overlap_duration
            if system_overlap_duration
            else None
        ),
        overlap_recall=(
            overlap_intersection / reference_overlap_duration
            if reference_overlap_duration
            else None
        ),
        overlap_duration_error_microseconds=abs(
            reference_overlap_duration - system_overlap_duration
        ),
    )


def _strata(
    reference: TemporalDiarizationReference,
    reference_intervals: tuple[IntervalKey, ...],
    system_intervals: tuple[IntervalKey, ...],
    mapping: tuple[DiarizationSpeakerMapping, ...],
    policy: DiarizationScoringPolicy,
) -> tuple[DiarizationStratumResult, ...]:
    names = sorted(
        {
            stratum
            for turn in reference.turns
            if _included_reference_kind(turn.speech_kind)
            for stratum in turn.strata
        }
    )
    results = []
    for name in names:
        windows = _merge_intervals(
            tuple(
                (
                    turn.normalized_audio_interval.start_microseconds,
                    _end(
                        turn.normalized_audio_interval.start_microseconds,
                        turn.normalized_audio_interval.duration_microseconds,
                    ),
                )
                for turn in reference.turns
                if name in turn.strata
                and _included_reference_kind(turn.speech_kind)
            )
        )
        totals = _score_speaker_time(
            reference_intervals,
            system_intervals,
            mapping,
            duration=reference.normalized_audio_duration_microseconds,
            exclusions=_collars(reference, policy),
            windows=windows,
        )
        if totals["reference"] <= 0 or totals["scored"] <= 0:
            continue
        results.append(
            DiarizationStratumResult(
                stratum=name,
                scored_window_microseconds=totals["scored"],
                reference_speaker_time_microseconds=totals["reference"],
                missed_speech_microseconds=totals["missed"],
                false_alarm_microseconds=totals["false_alarm"],
                speaker_confusion_microseconds=totals["confusion"],
                diarization_error_rate=(
                    totals["missed"]
                    + totals["false_alarm"]
                    + totals["confusion"]
                )
                / totals["reference"],
            )
        )
    return tuple(results)


def evaluate_diarization(
    diarization: DiarizationRun,
    response: DiarizationProviderResponse,
    reference: TemporalDiarizationReference,
    *,
    policy: DiarizationScoringPolicy | None = None,
    generated_at: datetime | None = None,
) -> ControlledDiarizationEvaluation:
    policy = policy or DiarizationScoringPolicy()
    validate_diarization_run(diarization)
    _validate_response_lineage(response, diarization)
    validate_temporal_reference(reference, diarization)
    duration = reference.normalized_audio_duration_microseconds
    if any(
        _end(
            turn.normalized_audio_interval.start_microseconds,
            turn.normalized_audio_interval.duration_microseconds,
        )
        > duration
        for turn in response.turns
    ) or any(
        _end(
            overlap.normalized_audio_interval.start_microseconds,
            overlap.normalized_audio_interval.duration_microseconds,
        )
        > duration
        for overlap in diarization.overlaps
    ):
        raise DiarizationEvaluationIntegrityError(
            "system diarization evidence exceeds reference duration"
        )
    reference_intervals = _reference_intervals(reference)
    system_intervals = _system_intervals(response)
    mapping = _speaker_mapping(
        reference_intervals,
        system_intervals,
        maximum_speakers=policy.maximum_mapping_speakers,
    )
    metrics = _build_metrics(
        diarization,
        response,
        reference,
        policy,
        reference_intervals,
        system_intervals,
        mapping,
    )
    strata = _strata(
        reference,
        reference_intervals,
        system_intervals,
        mapping,
        policy,
    )
    findings = []
    if metrics.missed_speech_microseconds:
        findings.append(
            f"Missed speaker time: {metrics.missed_speech_microseconds} us."
        )
    if metrics.false_alarm_microseconds:
        findings.append(
            f"False-alarm speaker time: {metrics.false_alarm_microseconds} us."
        )
    if metrics.speaker_confusion_microseconds:
        findings.append(
            "Speaker-confusion time: "
            f"{metrics.speaker_confusion_microseconds} us."
        )
    if (
        metrics.speaker_change_precision != 1.0
        or metrics.speaker_change_recall != 1.0
    ) and (
        metrics.reference_boundary_count or metrics.system_boundary_count
    ):
        findings.append(
            "System and reference speaker changes do not match completely "
            "within the declared tolerance."
        )
    if (
        metrics.reference_overlap_duration_microseconds
        or metrics.system_overlap_duration_microseconds
    ) and (
        metrics.overlap_precision != 1.0
        or metrics.overlap_recall != 1.0
    ):
        findings.append(
            "System and reference overlap durations do not match completely."
        )
    status = "warning" if findings else "complete"
    return _seal(
        ControlledDiarizationEvaluation,
        {
            "evaluation_id": typed_id(
                "diatempeval",
                diarization.run_id,
                response.response_id,
                reference.reference_id,
                policy.model_dump(mode="json"),
            ),
            "diarization_run_id": diarization.run_id,
            "provider_response_id": response.response_id,
            "corpus_id": diarization.corpus_id,
            "reference": reference,
            "policy": policy,
            "speaker_mapping": mapping,
            "metrics": metrics,
            "strata": strata,
            "generated_at": generated_at or datetime.now(timezone.utc),
            "findings": tuple(findings),
            "limitations": (
                "Reference labels are local fixture speakers, not identities.",
                "Results describe only the declared controlled recording.",
                "Excluded audience, background, and non-lexical regions are "
                "not general diarization claims.",
                "Provider speaker labels are evaluated without promotion to "
                "participant identities.",
            ),
            "status": status,
        },
    )


def _report(
    evaluation: ControlledDiarizationEvaluation,
) -> ControlledDiarizationEvaluationReport:
    metrics = evaluation.metrics
    return _seal(
        ControlledDiarizationEvaluationReport,
        {
            "report_id": typed_id(
                "diatempreport", evaluation.evaluation_id
            ),
            "evaluation_id": evaluation.evaluation_id,
            "diarization_run_id": evaluation.diarization_run_id,
            "reference_id": evaluation.reference.reference_id,
            "generated_at": evaluation.generated_at,
            "diarization_error_rate": metrics.diarization_error_rate,
            "speaker_change_precision": metrics.speaker_change_precision,
            "speaker_change_recall": metrics.speaker_change_recall,
            "overlap_precision": metrics.overlap_precision,
            "overlap_recall": metrics.overlap_recall,
            "stratum_count": len(evaluation.strata),
            "findings": evaluation.findings,
            "limitations": evaluation.limitations,
            "status": evaluation.status,
        },
    )


def evaluation_report_markdown(
    report: ControlledDiarizationEvaluationReport,
) -> str:
    def value(item: float | None) -> str:
        return "unavailable" if item is None else f"{item:.6f}"

    return "\n".join(
        [
            "# Phase 3 controlled temporal-diarization evaluation",
            "",
            f"Status: **{report.status.upper()}**",
            "",
            f"Evaluation: `{report.evaluation_id}`",
            "",
            f"- Diarization error rate: {report.diarization_error_rate:.6f}",
            (
                "- Speaker-change precision: "
                f"{value(report.speaker_change_precision)}"
            ),
            (
                "- Speaker-change recall: "
                f"{value(report.speaker_change_recall)}"
            ),
            f"- Overlap precision: {value(report.overlap_precision)}",
            f"- Overlap recall: {value(report.overlap_recall)}",
            f"- Reported strata: {report.stratum_count}",
            "",
            "Controlled local-speaker labels are not participant identities.",
            "",
        ]
    )


def validate_diarization_evaluation(
    evaluation: ControlledDiarizationEvaluation,
    diarization: DiarizationRun,
    response: DiarizationProviderResponse,
    report: ControlledDiarizationEvaluationReport | None = None,
) -> None:
    if not _integrity_valid(evaluation):
        raise DiarizationEvaluationIntegrityError(
            "temporal diarization evaluation integrity is invalid"
        )
    expected = evaluate_diarization(
        diarization,
        response,
        evaluation.reference,
        policy=evaluation.policy,
        generated_at=evaluation.generated_at,
    )
    if expected != evaluation:
        raise DiarizationEvaluationIntegrityError(
            "temporal diarization evaluation metrics are not reproducible"
        )
    if report is not None:
        if not _integrity_valid(report) or report != _report(evaluation):
            raise DiarizationEvaluationIntegrityError(
                "temporal diarization report integrity or metrics are invalid"
            )


def evaluate_diarization_artifacts(
    diarization_root: Path,
    reference_path: Path,
    destination: Path,
    *,
    policy: DiarizationScoringPolicy | None = None,
) -> tuple[
    ControlledDiarizationEvaluation,
    ControlledDiarizationEvaluationReport,
    Path,
    bool,
]:
    diarization_root = diarization_root.expanduser().resolve(strict=True)
    reference_path = reference_path.expanduser().resolve(strict=True)
    destination = destination.expanduser().resolve()
    if destination == diarization_root or diarization_root in destination.parents:
        raise ValueError("evaluation output must not modify diarization evidence")
    request = load_contract(
        (diarization_root / "request.json").read_bytes(), DiarizationRequest
    )
    response = load_contract(
        (diarization_root / "response.json").read_bytes(),
        DiarizationProviderResponse,
    )
    diarization = load_contract(
        (diarization_root / "run.json").read_bytes(), DiarizationRun
    )
    validate_diarization_response(response, request, diarization_root)
    validate_diarization_run(diarization)
    reference = load_contract(
        reference_path.read_bytes(), TemporalDiarizationReference
    )
    expected = evaluate_diarization(
        diarization, response, reference, policy=policy
    )
    root = (
        destination
        / "diarization-evaluations"
        / expected.evaluation_id
    )
    evaluation_path = root / "evaluation.json"
    report_path = root / "report.json"
    markdown_path = root / "report.md"
    existing = tuple(
        path.exists() for path in (evaluation_path, report_path, markdown_path)
    )
    if any(existing) and not all(existing):
        raise DiarizationEvaluationIntegrityError(
            "cached temporal diarization evaluation is incomplete"
        )
    if all(existing):
        stored = load_contract(
            evaluation_path.read_bytes(), ControlledDiarizationEvaluation
        )
        report = load_contract(
            report_path.read_bytes(),
            ControlledDiarizationEvaluationReport,
        )
        validate_diarization_evaluation(
            stored, diarization, response, report
        )
        if markdown_path.read_bytes() != evaluation_report_markdown(
            report
        ).encode("utf-8"):
            raise DiarizationEvaluationIntegrityError(
                "cached temporal diarization human report is invalid"
            )
        if stored.evaluation_id != expected.evaluation_id:
            raise DiarizationEvaluationIntegrityError(
                "cached temporal diarization evaluation is incompatible"
            )
        return stored, report, root, True
    report = _report(expected)
    _atomic(evaluation_path, canonical_bytes(expected))
    _atomic(report_path, canonical_bytes(report))
    _atomic(
        markdown_path, evaluation_report_markdown(report).encode("utf-8")
    )
    return expected, report, root, False


def load_diarization_evaluation(
    root: Path,
) -> tuple[
    ControlledDiarizationEvaluation,
    ControlledDiarizationEvaluationReport,
]:
    root = root.expanduser().resolve(strict=True)
    return (
        load_contract(
            (root / "evaluation.json").read_bytes(),
            ControlledDiarizationEvaluation,
        ),
        load_contract(
            (root / "report.json").read_bytes(),
            ControlledDiarizationEvaluationReport,
        ),
    )
