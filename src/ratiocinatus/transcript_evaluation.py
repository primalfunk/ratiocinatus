"""Deterministic controlled-reference transcript evaluation."""

from __future__ import annotations

import hashlib
import os
import re
import statistics
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .correction_contracts import (
    TranscriptRevision,
    TranscriptSegmentState,
    TranscriptViewKind,
)
from .corrections import (
    _state_from_segment,
    _verify_persisted_assembly,
    _verify_persisted_revision,
    validate_transcript_revision,
)
from .evaluation_contracts import (
    CandidateSelectionMetrics,
    ConfidenceReliabilityAnalysis,
    ConfidenceReliabilityBin,
    CorrectionImpact,
    EditMetrics,
    EvaluationAvailability,
    EvaluationStratum,
    ReferenceTranscript,
    StratumEvaluation,
    SubtitleCueEvaluation,
    TimingErrorMetrics,
    TranscriptEvaluationPolicy,
    TranscriptEvaluationReport,
)
from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .subtitle_contracts import (
    SubtitleExportManifest,
    SubtitleValidationReport,
)
from .subtitles import validate_subtitle_export
from .transcript_assembly import validate_transcript_assembly
from .transcript_contracts import TranscriptAssembly


class TranscriptEvaluationIntegrityError(ValueError):
    """Raised when evaluation inputs, output, or cache disagree."""


TOKEN_PATTERN = re.compile(r"[^\W_]+(?:'[^\W_]+)?", re.UNICODE)


def _seal(report: TranscriptEvaluationReport) -> TranscriptEvaluationReport:
    return report.model_copy(
        update={
            "integrity_sha256": canonical_hash(
                report.model_copy(update={"integrity_sha256": "0" * 64})
            )
        }
    )


def _verify_seal(report: TranscriptEvaluationReport) -> None:
    if _seal(report).integrity_sha256 != report.integrity_sha256:
        raise TranscriptEvaluationIntegrityError(
            "transcript evaluation integrity seal is invalid"
        )


def _atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def normalize_tokens(text: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return tuple(TOKEN_PATTERN.findall(normalized))


def _edit_alignment(
    reference: tuple[str, ...],
    hypothesis: tuple[str, ...],
) -> tuple[int, int, int]:
    rows: list[list[tuple[int, int, int, int]]] = [
        [(index, 0, index, 0) for index in range(len(hypothesis) + 1)]
    ]
    for left_index, left in enumerate(reference, start=1):
        row = [(left_index, 0, 0, left_index)]
        for right_index, right in enumerate(hypothesis, start=1):
            deletion = rows[-1][right_index]
            insertion = row[-1]
            diagonal = rows[-1][right_index - 1]
            options = (
                (
                    deletion[0] + 1,
                    deletion[1],
                    deletion[2],
                    deletion[3] + 1,
                ),
                (
                    insertion[0] + 1,
                    insertion[1],
                    insertion[2] + 1,
                    insertion[3],
                ),
                (
                    diagonal[0] + (left != right),
                    diagonal[1] + (left != right),
                    diagonal[2],
                    diagonal[3],
                ),
            )
            row.append(min(options))
        rows.append(row)
    _, substitutions, insertions, deletions = rows[-1][-1]
    return substitutions, deletions, insertions


def _distance(left: tuple[str, ...], right: tuple[str, ...]) -> int:
    previous = list(range(len(right) + 1))
    for left_index, left_item in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_item in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_item != right_item),
                )
            )
        previous = current
    return previous[-1]


def edit_metrics(reference_text: str, hypothesis_text: str) -> EditMetrics:
    reference = normalize_tokens(reference_text)
    hypothesis = normalize_tokens(hypothesis_text)
    substitutions, deletions, insertions = _edit_alignment(
        reference, hypothesis
    )
    reference_characters = tuple(" ".join(reference))
    hypothesis_characters = tuple(" ".join(hypothesis))
    character_edits = _distance(
        reference_characters, hypothesis_characters
    )
    return EditMetrics(
        reference_word_count=len(reference),
        hypothesis_word_count=len(hypothesis),
        word_substitution_count=substitutions,
        word_deletion_count=deletions,
        word_insertion_count=insertions,
        word_error_rate=(
            (substitutions + deletions + insertions) / len(reference)
            if reference
            else None
        ),
        reference_character_count=len(reference_characters),
        hypothesis_character_count=len(hypothesis_characters),
        character_edit_count=character_edits,
        character_error_rate=(
            character_edits / len(reference_characters)
            if reference_characters
            else None
        ),
    )


def _bounds(value) -> tuple[int, int]:
    interval = value.normalized_audio_interval
    return (
        interval.start_microseconds,
        interval.start_microseconds + interval.duration_microseconds,
    )


def _overlap(left, right) -> int:
    left_start, left_end = _bounds(left)
    right_start, right_end = _bounds(right)
    return max(0, min(left_end, right_end) - max(left_start, right_start))


def _matching_state(
    reference,
    states: tuple[TranscriptSegmentState, ...],
) -> TranscriptSegmentState | None:
    if not states:
        return None
    overlapping = [(item, _overlap(reference, item)) for item in states]
    best, amount = max(
        overlapping,
        key=lambda pair: (
            pair[1],
            -abs(
                sum(_bounds(pair[0])) - sum(_bounds(reference))
            ),
        ),
    )
    if amount:
        return best
    return min(
        states,
        key=lambda item: abs(sum(_bounds(item)) - sum(_bounds(reference))),
    )


def _states_for_references(
    states: tuple[TranscriptSegmentState, ...],
    references: Iterable,
) -> tuple[TranscriptSegmentState, ...]:
    selected = {
        item.artifact_id
        for reference in references
        for item in states
        if _overlap(reference, item) > 0
    }
    return tuple(item for item in states if item.artifact_id in selected)


def _joined_reference(references: Iterable) -> str:
    return " ".join(item.text for item in references)


def _joined_hypothesis(states: Iterable[TranscriptSegmentState]) -> str:
    return " ".join(item.normalized_text for item in states)


def _timing_metrics(references, states) -> TimingErrorMetrics:
    start_errors: list[int] = []
    end_errors: list[int] = []
    unmatched = 0
    for reference in references:
        match = _matching_state(reference, states)
        if match is None:
            unmatched += 1
            continue
        reference_start, reference_end = _bounds(reference)
        match_start, match_end = _bounds(match)
        start_errors.append(abs(match_start - reference_start))
        end_errors.append(abs(match_end - reference_end))
    if not start_errors:
        return TimingErrorMetrics(
            availability=EvaluationAvailability.UNAVAILABLE_HYPOTHESIS,
            evaluated_item_count=0,
            unmatched_reference_count=unmatched,
            unavailable_reason="No hypothesis segment could be matched.",
        )
    return TimingErrorMetrics(
        availability=EvaluationAvailability.AVAILABLE,
        evaluated_item_count=len(start_errors),
        unmatched_reference_count=unmatched,
        mean_start_error_microseconds=statistics.mean(start_errors),
        median_start_error_microseconds=statistics.median(start_errors),
        maximum_start_error_microseconds=max(start_errors),
        mean_end_error_microseconds=statistics.mean(end_errors),
        median_end_error_microseconds=statistics.median(end_errors),
        maximum_end_error_microseconds=max(end_errors),
    )


def _word_timing(
    reference: ReferenceTranscript,
    assembly: TranscriptAssembly,
) -> TimingErrorMetrics:
    expected = [
        word
        for segment in reference.segments
        for word in segment.words
        if word.normalized_audio_interval is not None
    ]
    if not expected:
        return TimingErrorMetrics(
            availability=EvaluationAvailability.UNAVAILABLE_REFERENCE,
            evaluated_item_count=0,
            unmatched_reference_count=0,
            unavailable_reason=(
                "The controlled reference does not claim word timestamps."
            ),
        )
    actual = [
        word
        for word in assembly.words
        if any(_overlap(word, segment) > 0 for segment in reference.segments)
    ]
    count = min(len(expected), len(actual))
    if not count:
        return TimingErrorMetrics(
            availability=EvaluationAvailability.UNAVAILABLE_HYPOTHESIS,
            evaluated_item_count=0,
            unmatched_reference_count=len(expected),
            unavailable_reason="No canonical word timestamps overlap reference.",
        )
    starts = [
        abs(_bounds(expected[index])[0] - _bounds(actual[index])[0])
        for index in range(count)
    ]
    ends = [
        abs(_bounds(expected[index])[1] - _bounds(actual[index])[1])
        for index in range(count)
    ]
    return TimingErrorMetrics(
        availability=EvaluationAvailability.AVAILABLE,
        evaluated_item_count=count,
        unmatched_reference_count=len(expected) - count,
        mean_start_error_microseconds=statistics.mean(starts),
        median_start_error_microseconds=statistics.median(starts),
        maximum_start_error_microseconds=max(starts),
        mean_end_error_microseconds=statistics.mean(ends),
        median_end_error_microseconds=statistics.median(ends),
        maximum_end_error_microseconds=max(ends),
    )


def _confidence_reliability(
    reference: ReferenceTranscript,
    states: tuple[TranscriptSegmentState, ...],
    assembly: TranscriptAssembly,
    policy: TranscriptEvaluationPolicy,
) -> ConfidenceReliabilityAnalysis:
    segment_by_id = {item.segment_id: item for item in assembly.segments}
    rows: list[tuple[float, float]] = []
    unavailable = 0
    for state in states:
        origins = [
            segment_by_id[item]
            for item in state.origin_segment_ids
            if item in segment_by_id
        ]
        values = [
            item.text_confidence.value
            for item in origins
            if item.text_confidence.value is not None
        ]
        if not values:
            unavailable += 1
            continue
        overlapping = [
            item for item in reference.segments if _overlap(item, state) > 0
        ]
        if not overlapping:
            continue
        metrics = edit_metrics(
            _joined_reference(overlapping), state.normalized_text
        )
        accuracy = 1.0 - min(metrics.word_error_rate or 0.0, 1.0)
        rows.append((statistics.mean(values), accuracy))
    if not rows:
        return ConfidenceReliabilityAnalysis(
            availability=EvaluationAvailability.UNAVAILABLE_HYPOTHESIS,
            confidence_origin="mixed_or_unavailable",
            excluded_unavailable_count=unavailable,
            method=(
                "Segment text confidence versus overlapping-reference word "
                "accuracy; descriptive only, not calibration."
            ),
            unavailable_reason=(
                "No evaluated segment supplied numeric text confidence."
            ),
        )
    bins: list[ConfidenceReliabilityBin] = []
    edges = policy.confidence_bin_edges
    for index, (lower, upper) in enumerate(zip(edges, edges[1:])):
        selected = [
            row
            for row in rows
            if row[0] >= lower
            and (row[0] <= upper if index == len(edges) - 2 else row[0] < upper)
        ]
        if not selected:
            continue
        claimed = statistics.mean(item[0] for item in selected)
        observed = statistics.mean(item[1] for item in selected)
        bins.append(
            ConfidenceReliabilityBin(
                lower_inclusive=lower,
                upper_inclusive=upper,
                item_count=len(selected),
                mean_claimed_confidence=claimed,
                mean_observed_word_accuracy=observed,
                absolute_reliability_gap=abs(claimed - observed),
            )
        )
    origins = {
        segment_by_id[item].text_confidence.origin.value
        for state in states
        for item in state.origin_segment_ids
        if item in segment_by_id
        and segment_by_id[item].text_confidence.value is not None
    }
    return ConfidenceReliabilityAnalysis(
        availability=EvaluationAvailability.AVAILABLE,
        confidence_origin=(
            next(iter(origins)) if len(origins) == 1 else "mixed"
        ),
        bins=tuple(bins),
        excluded_unavailable_count=unavailable,
        method=(
            "Segment text confidence versus overlapping-reference word "
            "accuracy; descriptive only, not evidence of calibration."
        ),
    )


def _candidate_metrics(
    reference: ReferenceTranscript,
    states: tuple[TranscriptSegmentState, ...],
    assembly: TranscriptAssembly,
) -> CandidateSelectionMetrics:
    expected = [
        item for item in reference.segments if item.expected_candidate_id
    ]
    if not expected:
        return CandidateSelectionMetrics(
            availability=EvaluationAvailability.UNAVAILABLE_REFERENCE,
            evaluated_segment_count=0,
            correct_selection_count=0,
            unavailable_reason=(
                "Reference segments do not designate provider candidates."
            ),
        )
    segment_by_id = {item.segment_id: item for item in assembly.segments}
    correct = 0
    evaluated = 0
    for item in expected:
        state = _matching_state(item, states)
        if state is None:
            continue
        candidates = {
            segment_by_id[origin].selected_candidate_id
            for origin in state.origin_segment_ids
            if origin in segment_by_id
        }
        evaluated += 1
        correct += item.expected_candidate_id in candidates
    if not evaluated:
        return CandidateSelectionMetrics(
            availability=EvaluationAvailability.UNAVAILABLE_HYPOTHESIS,
            evaluated_segment_count=0,
            correct_selection_count=0,
            unavailable_reason="No candidate-bearing hypothesis matched.",
        )
    return CandidateSelectionMetrics(
        availability=EvaluationAvailability.AVAILABLE,
        evaluated_segment_count=evaluated,
        correct_selection_count=correct,
        accuracy=correct / evaluated,
    )


def _subtitle_metrics(
    root: Path | None,
    *,
    version_id: str,
) -> SubtitleCueEvaluation:
    if root is None:
        return SubtitleCueEvaluation(
            availability=EvaluationAvailability.NOT_REQUESTED,
            cue_count=0,
            unavailable_reason="No subtitle export was supplied.",
        )
    root = root.resolve(strict=True)
    manifest = load_contract(
        (root / "manifest.json").read_bytes(), SubtitleExportManifest
    )
    validation = load_contract(
        (root / "validation-report.json").read_bytes(),
        SubtitleValidationReport,
    )
    validate_subtitle_export(manifest, root, report=validation)
    if manifest.transcript_version_id != version_id:
        raise TranscriptEvaluationIntegrityError(
            "subtitle export belongs to another transcript version"
        )
    return SubtitleCueEvaluation(
        availability=EvaluationAvailability.AVAILABLE,
        export_id=manifest.export_id,
        cue_count=len(manifest.cues),
        valid=True,
    )


def _correction_impact(
    reference: ReferenceTranscript,
    assembly: TranscriptAssembly,
    revision: TranscriptRevision | None,
) -> CorrectionImpact:
    if revision is None:
        return CorrectionImpact(
            availability=EvaluationAvailability.NOT_REQUESTED,
            base_version_id=assembly.version.version_id,
            correction_count=0,
            unavailable_reason="No transcript revision was supplied.",
        )
    reference_text = _joined_reference(reference.segments)
    original_states = _states_for_references(
        revision.original_machine_view.segments, reference.segments
    )
    corrected_states = _states_for_references(
        revision.current_corrected_view.segments, reference.segments
    )
    original = edit_metrics(
        reference_text, _joined_hypothesis(original_states)
    )
    corrected = edit_metrics(
        reference_text, _joined_hypothesis(corrected_states)
    )
    return CorrectionImpact(
        availability=EvaluationAvailability.AVAILABLE,
        base_version_id=assembly.version.version_id,
        corrected_version_id=revision.version.version_id,
        original=original,
        corrected=corrected,
        word_error_rate_change=(
            (corrected.word_error_rate or 0.0)
            - (original.word_error_rate or 0.0)
        ),
        character_error_rate_change=(
            (corrected.character_error_rate or 0.0)
            - (original.character_error_rate or 0.0)
        ),
        correction_count=len(revision.corrections),
    )


def _markdown(report: TranscriptEvaluationReport) -> bytes:
    wer = report.aggregate.word_error_rate
    cer = report.aggregate.character_error_rate
    lines = [
        "# Transcript evaluation",
        "",
        f"Status: **{report.status.upper()}**",
        "",
        f"- Evaluation: `{report.evaluation_id}`",
        f"- Transcript version: `{report.transcript_version_id}`",
        f"- Reference: `{report.reference.reference_id}`",
        f"- View: `{report.view_kind.value}`",
        f"- WER: `{wer:.6f}`" if wer is not None else "- WER: unavailable",
        f"- CER: `{cer:.6f}`" if cer is not None else "- CER: unavailable",
        (
            f"- Segment timing items: "
            f"`{report.segment_timing.evaluated_item_count}`"
        ),
        "",
        "These controlled-reference measurements do not establish general "
        "transcription quality.",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def validate_transcript_evaluation(
    report: TranscriptEvaluationReport,
    *,
    assembly: TranscriptAssembly | None = None,
    root: Path | None = None,
) -> None:
    _verify_seal(report)
    if assembly is not None and (
        report.base_assembly_id != assembly.assembly_id
        or report.reference.corpus_id != assembly.version.corpus_id
        or report.reference.source_id != assembly.source_id
        or report.reference.normalized_audio_sha256
        != assembly.normalized_audio_sha256
        or report.reference.normalized_audio_duration_microseconds
        != assembly.normalized_audio_duration_microseconds
        or report.reference.source_mapping_offset_microseconds
        != assembly.source_mapping_offset_microseconds
    ):
        raise TranscriptEvaluationIntegrityError(
            "evaluation reference and assembly lineage disagree"
        )
    if root is not None:
        root = root.resolve()
        report_path = root / "report.json"
        markdown_path = root / "report.md"
        try:
            persisted = report_path.read_bytes()
            markdown = markdown_path.read_bytes()
        except OSError as exc:
            raise TranscriptEvaluationIntegrityError(
                "persisted evaluation is incomplete"
            ) from exc
        if (
            persisted != canonical_bytes(report)
            or hashlib.sha256(markdown).hexdigest()
            != hashlib.sha256(_markdown(report)).hexdigest()
            or markdown != _markdown(report)
        ):
            raise TranscriptEvaluationIntegrityError(
                "persisted evaluation failed validation"
            )


def evaluate_transcript(
    assembly_root: Path,
    reference_path: Path,
    destination: Path,
    *,
    revision_root: Path | None = None,
    view_kind: TranscriptViewKind = TranscriptViewKind.ORIGINAL_MACHINE,
    subtitle_export_root: Path | None = None,
    policy: TranscriptEvaluationPolicy | None = None,
) -> tuple[TranscriptEvaluationReport, Path, bool]:
    assembly_root = assembly_root.resolve(strict=True)
    assembly = load_contract(
        (assembly_root / "assembly.json").read_bytes(), TranscriptAssembly
    )
    validate_transcript_assembly(assembly)
    _verify_persisted_assembly(assembly_root, assembly)
    reference = load_contract(
        reference_path.resolve(strict=True).read_bytes(), ReferenceTranscript
    )
    if (
        reference.corpus_id != assembly.version.corpus_id
        or reference.source_id != assembly.source_id
        or reference.normalized_audio_sha256
        != assembly.normalized_audio_sha256
        or reference.normalized_audio_duration_microseconds
        != assembly.normalized_audio_duration_microseconds
        or reference.source_mapping_offset_microseconds
        != assembly.source_mapping_offset_microseconds
    ):
        raise TranscriptEvaluationIntegrityError(
            "reference transcript belongs to another assembly lineage"
        )
    revision = None
    if revision_root is not None:
        revision_root = revision_root.resolve(strict=True)
        revision = load_contract(
            (revision_root / "revision.json").read_bytes(),
            TranscriptRevision,
        )
        validate_transcript_revision(revision, assembly=assembly)
        _verify_persisted_revision(revision_root, revision)
    if view_kind == TranscriptViewKind.CURRENT_CORRECTED:
        if revision is None:
            raise TranscriptEvaluationIntegrityError(
                "corrected evaluation requires a transcript revision"
            )
        view = revision.current_corrected_view
    elif revision is not None:
        view = revision.original_machine_view
    else:
        states = _state_from_segment(assembly)
        view = None
    states = view.segments if view is not None else _state_from_segment(assembly)
    version_id = (
        view.version_id if view is not None else assembly.version.version_id
    )
    policy = policy or TranscriptEvaluationPolicy()
    reference_text = _joined_reference(reference.segments)
    evaluated_states = _states_for_references(states, reference.segments)
    aggregate = edit_metrics(
        reference_text, _joined_hypothesis(evaluated_states)
    )
    strata: list[StratumEvaluation] = []
    represented = sorted(
        {tag for item in reference.segments for tag in item.strata},
        key=lambda item: item.value,
    )
    for stratum in represented:
        references = tuple(
            item for item in reference.segments if stratum in item.strata
        )
        matching = _states_for_references(states, references)
        strata.append(
            StratumEvaluation(
                stratum=stratum,
                reference_segment_count=len(references),
                metrics=edit_metrics(
                    _joined_reference(references),
                    _joined_hypothesis(matching),
                ),
                segment_timing=_timing_metrics(references, matching),
            )
        )
    reviewed = sum(
        any(
            _overlap(reference_segment, region) > 0
            for region in assembly.low_confidence_regions
        )
        for reference_segment in reference.segments
    )
    timing = _timing_metrics(reference.segments, evaluated_states)
    word_timing = _word_timing(reference, assembly)
    reliability = _confidence_reliability(
        reference, evaluated_states, assembly, policy
    )
    candidate = _candidate_metrics(reference, evaluated_states, assembly)
    subtitle = _subtitle_metrics(
        subtitle_export_root, version_id=version_id
    )
    impact = _correction_impact(reference, assembly, revision)
    unavailable = tuple(
        name
        for name, value in (
            ("word timing", word_timing.availability),
            ("candidate selection", candidate.availability),
            ("subtitle cues", subtitle.availability),
            ("correction impact", impact.availability),
        )
        if value != EvaluationAvailability.AVAILABLE
    )
    generated_at: datetime = (
        view.created_at if view is not None else assembly.assembled_at
    )
    evaluation_id = typed_id(
        "txevaluation",
        assembly.assembly_id,
        revision.revision_id if revision is not None else None,
        version_id,
        view_kind.value,
        reference.reference_id,
        policy.model_dump(mode="json"),
        subtitle.export_id,
    )
    findings = (
        "Controlled-reference results do not establish general transcription "
        "quality.",
        "Reference text is evaluation input and was not supplied to provider "
        "inference.",
        "Segment timing uses maximum overlap then nearest midpoint; it is not "
        "speaker or semantic alignment.",
    ) + (
        (
            "Unavailable or unrequested metrics: "
            + ", ".join(unavailable)
            + "."
        ,)
        if unavailable
        else ()
    )
    report = _seal(
        TranscriptEvaluationReport(
            evaluation_id=evaluation_id,
            base_assembly_id=assembly.assembly_id,
            revision_id=(
                revision.revision_id if revision is not None else None
            ),
            transcript_version_id=version_id,
            view_kind=view_kind,
            reference=reference,
            policy=policy,
            generated_at=generated_at,
            aggregate=aggregate,
            strata=tuple(strata),
            segment_timing=timing,
            word_timing=word_timing,
            confidence_reliability=reliability,
            candidate_selection=candidate,
            subtitle_cues=subtitle,
            correction_impact=impact,
            reviewed_reference_segment_count=reviewed,
            findings=findings,
            status="warning" if unavailable else "complete",
            integrity_sha256="0" * 64,
        )
    )
    root = (
        destination.resolve()
        / "transcript-evaluations"
        / report.evaluation_id
    )
    report_path = root / "report.json"
    markdown_path = root / "report.md"
    if report_path.exists() or markdown_path.exists():
        if not report_path.exists() or not markdown_path.exists():
            raise TranscriptEvaluationIntegrityError(
                "cached transcript evaluation is incomplete"
            )
        stored = load_contract(
            report_path.read_bytes(), TranscriptEvaluationReport
        )
        if stored != report:
            raise TranscriptEvaluationIntegrityError(
                "cached transcript evaluation is incompatible"
            )
        validate_transcript_evaluation(
            stored, assembly=assembly, root=root
        )
        return stored, root, True
    _atomic(report_path, canonical_bytes(report))
    _atomic(markdown_path, _markdown(report))
    validate_transcript_evaluation(report, assembly=assembly, root=root)
    return report, root, False
