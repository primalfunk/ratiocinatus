"""Conservative Phase 4 completeness and disfluency analysis."""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime
from pathlib import Path

from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase2_contracts import ConfidenceMeasure, ConfidenceOrigin
from .phase4_contracts import (
    DisfluencyKind,
    DisfluencySpan,
    SelfRepair,
    SelfRepairKind,
    Utterance,
    UtteranceAnalysisPolicy,
    UtteranceAnalysisReport,
    UtteranceAnalysisRun,
    UtteranceCompletenessAssessment,
    UtteranceCompletenessClassification,
    UtteranceCorpus,
    UtteranceReviewStatus,
    UtteranceRun,
    UtteranceTextKind,
)
from .transcript_assembly import validate_transcript_assembly
from .transcript_contracts import TranscriptAssembly, TranscriptWord


class UtteranceAnalysisIntegrityError(RuntimeError):
    """Completeness/disfluency evidence is corrupt or incompatible."""


def _atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.partial-{uuid.uuid4().hex}")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _seal(model, payload: dict):
    provisional = model(**payload, integrity_sha256="0" * 64)
    integrity = canonical_hash(
        provisional.model_dump(mode="json", exclude={"integrity_sha256"})
    )
    return model(**payload, integrity_sha256=integrity)


def _verify_seal(item, label: str) -> None:
    payload = item.model_dump(mode="json", exclude={"integrity_sha256"})
    if canonical_hash(payload) != item.integrity_sha256:
        raise UtteranceAnalysisIntegrityError(f"{label} integrity is invalid")


def _confidence(value: float | None, basis: str) -> ConfidenceMeasure:
    return ConfidenceMeasure(
        value=value,
        origin=(
            ConfidenceOrigin.DERIVED
            if value is not None
            else ConfidenceOrigin.UNAVAILABLE
        ),
        basis=basis,
    )


def _normalized(text: str) -> str:
    return re.sub(r"(^[^\w]+|[^\w]+$)", "", text.casefold()).strip()


def _display_text(utterance: Utterance) -> str:
    return next(
        item.text
        for item in utterance.text_views
        if item.kind == UtteranceTextKind.DISPLAY
    )


def _utterance_words(
    utterance: Utterance, words: dict[str, TranscriptWord]
) -> tuple[TranscriptWord, ...]:
    word_ids = tuple(
        word_id
        for component in utterance.components
        for word_id in component.transcript_word_ids
    )
    try:
        selected = tuple(words[word_id] for word_id in word_ids)
    except KeyError as error:
        raise UtteranceAnalysisIntegrityError(
            "utterance references an unknown transcript word"
        ) from error
    return tuple(
        sorted(
            selected,
            key=lambda item: (
                item.normalized_audio_interval.start_microseconds,
                item.sequence_position,
                item.word_id,
            ),
        )
    )


def _completeness(
    utterance: Utterance,
    words: tuple[TranscriptWord, ...],
    assembly: TranscriptAssembly,
    policy: UtteranceAnalysisPolicy,
    created_at: datetime,
) -> UtteranceCompletenessAssessment:
    text = _display_text(utterance).rstrip()
    normalized_words = tuple(
        value for word in words if (value := _normalized(word.surface_text))
    )
    duration = sum(
        item.duration_microseconds for item in utterance.normalized_audio_intervals
    )
    last_end = max(
        item.start_microseconds + item.duration_microseconds
        for item in utterance.normalized_audio_intervals
    )
    evidence = tuple(
        component.component_id for component in utterance.components
    )
    terminal = text.endswith((".", "?", "!"))
    if not normalized_words:
        classification = UtteranceCompletenessClassification.NON_LEXICAL
        signals = ("no lexical transcript tokens observed",)
        confidence = _confidence(0.95, "deterministic lexical-token check")
        review = UtteranceReviewStatus.UNREVIEWED
    elif text.endswith(("...", "\u2026")):
        classification = UtteranceCompletenessClassification.UNKNOWN
        signals = (
            "terminal ellipsis observed",
            "punctuation alone cannot establish trailing off",
        )
        confidence = _confidence(None, "additional temporal evidence required")
        review = UtteranceReviewStatus.REVIEW_REQUIRED
    elif text.endswith(("-", "\u2014", "\u2013")):
        classification = UtteranceCompletenessClassification.UNKNOWN
        signals = (
            "terminal dash observed",
            "punctuation alone cannot establish abandonment",
        )
        confidence = _confidence(None, "additional temporal evidence required")
        review = UtteranceReviewStatus.REVIEW_REQUIRED
    elif (
        not terminal
        and last_end
        >= assembly.normalized_audio_duration_microseconds
        - policy.source_boundary_tolerance_microseconds
    ):
        classification = (
            UtteranceCompletenessClassification.CLIPPED_BY_SOURCE_BOUNDARY
        )
        signals = ("non-terminal wording reaches source boundary",)
        confidence = _confidence(0.90, "source-duration boundary comparison")
        review = UtteranceReviewStatus.REVIEW_REQUIRED
    elif (
        duration <= policy.short_fragment_max_microseconds
        and len(normalized_words) == 1
        and not terminal
    ):
        classification = UtteranceCompletenessClassification.FRAGMENT
        signals = ("single short non-terminal lexical token observed",)
        confidence = _confidence(0.70, "bounded duration and token-count rule")
        review = UtteranceReviewStatus.REVIEW_REQUIRED
    elif policy.terminal_punctuation_enabled and terminal:
        classification = UtteranceCompletenessClassification.COMPLETE
        signals = (
            "lexical transcript content observed",
            "terminal punctuation observed within source bounds",
        )
        confidence = _confidence(
            0.80, "combined lexical and bounded punctuation signals"
        )
        review = UtteranceReviewStatus.UNREVIEWED
    else:
        classification = UtteranceCompletenessClassification.UNKNOWN
        signals = ("no bounded completeness signal observed",)
        confidence = _confidence(None, "semantic inference is prohibited")
        review = UtteranceReviewStatus.REVIEW_REQUIRED
    payload = {
        "assessment_id": typed_id(
            "utterancecomplete",
            utterance.utterance_id,
            policy.policy_version,
            classification.value,
            signals,
        ),
        "utterance_id": utterance.utterance_id,
        "utterance_corpus_id": utterance.utterance_corpus_id,
        "classification": classification,
        "observed_signals": signals,
        "evidence_references": evidence,
        "confidence": confidence,
        "review_status": review,
        "policy_version": policy.policy_version,
        "created_at": created_at,
    }
    return _seal(UtteranceCompletenessAssessment, payload)


def _span(
    utterance: Utterance,
    kind: DisfluencyKind,
    selected: tuple[TranscriptWord, ...],
    policy: UtteranceAnalysisPolicy,
) -> DisfluencySpan:
    word_ids = tuple(item.word_id for item in selected)
    payload = {
        "disfluency_id": typed_id(
            "disfluency", utterance.utterance_id, kind.value, word_ids
        ),
        "utterance_id": utterance.utterance_id,
        "utterance_corpus_id": utterance.utterance_corpus_id,
        "kind": kind,
        "transcript_word_ids": word_ids,
        "source_intervals": tuple(item.source_interval for item in selected),
        "normalized_audio_intervals": tuple(
            item.normalized_audio_interval for item in selected
        ),
        "surface_text": " ".join(item.surface_text for item in selected),
        "evidence_references": word_ids,
        "confidence": _confidence(0.90, "bounded surface-token pattern"),
        "review_status": UtteranceReviewStatus.REVIEW_REQUIRED,
        "policy_version": policy.policy_version,
    }
    return _seal(DisfluencySpan, payload)


def _repair(
    utterance: Utterance,
    kind: SelfRepairKind,
    reparandum: tuple[TranscriptWord, ...],
    markers: tuple[TranscriptWord, ...],
    repair: tuple[TranscriptWord, ...],
    policy: UtteranceAnalysisPolicy,
) -> SelfRepair:
    all_words = reparandum + markers + repair
    evidence = tuple(item.word_id for item in all_words)
    interruption = (
        reparandum[-1].normalized_audio_interval.start_microseconds
        + reparandum[-1].normalized_audio_interval.duration_microseconds
    )
    payload = {
        "self_repair_id": typed_id(
            "selfrepair", utterance.utterance_id, kind.value, evidence
        ),
        "utterance_id": utterance.utterance_id,
        "utterance_corpus_id": utterance.utterance_corpus_id,
        "kind": kind,
        "reparandum_word_ids": tuple(item.word_id for item in reparandum),
        "repair_marker_word_ids": tuple(item.word_id for item in markers),
        "repair_word_ids": tuple(item.word_id for item in repair),
        "interruption_point_normalized_microseconds": interruption,
        "evidence_references": evidence,
        "confidence": _confidence(0.75, "bounded local token relation candidate"),
        "review_status": UtteranceReviewStatus.REVIEW_REQUIRED,
        "policy_version": policy.policy_version,
    }
    return _seal(SelfRepair, payload)


def _disfluencies_and_repairs(
    utterance: Utterance,
    words: tuple[TranscriptWord, ...],
    policy: UtteranceAnalysisPolicy,
) -> tuple[tuple[DisfluencySpan, ...], tuple[SelfRepair, ...]]:
    spans: list[DisfluencySpan] = []
    repairs: list[SelfRepair] = []
    normalized = tuple(_normalized(item.surface_text) for item in words)
    for index, word in enumerate(words):
        token = normalized[index]
        if token in policy.filler_tokens:
            spans.append(_span(utterance, DisfluencyKind.FILLER, (word,), policy))
        if (
            word.surface_text.casefold() in policy.hesitation_tokens
            or "…" in word.surface_text
            or "..." in word.surface_text
        ):
            spans.append(
                _span(utterance, DisfluencyKind.HESITATION, (word,), policy)
            )
        if (
            index
            and token
            and token == normalized[index - 1]
            and policy.maximum_repetition_window_words >= 1
        ):
            selected = (words[index - 1], word)
            spans.append(
                _span(utterance, DisfluencyKind.REPETITION, selected, policy)
            )
        if token in policy.repair_marker_tokens and 0 < index < len(words) - 1:
            spans.append(
                _span(
                    utterance,
                    DisfluencyKind.EXPLICIT_CORRECTION,
                    (word,),
                    policy,
                )
            )
            repairs.append(
                _repair(
                    utterance,
                    SelfRepairKind.EXPLICIT_CORRECTION,
                    (words[index - 1],),
                    (word,),
                    (words[index + 1],),
                    policy,
                )
            )
        if (
            word.surface_text.rstrip().endswith(("-", "—", "–"))
            and index < len(words) - 1
        ):
            spans.append(
                _span(utterance, DisfluencyKind.FALSE_START, (word,), policy)
            )
            repairs.append(
                _repair(
                    utterance,
                    SelfRepairKind.RESTART,
                    (word,),
                    (),
                    (words[index + 1],),
                    policy,
                )
            )
    return tuple(spans), tuple(repairs)


def _lineage(
    run: UtteranceRun,
    corpus: UtteranceCorpus,
    assembly: TranscriptAssembly,
) -> None:
    validate_transcript_assembly(assembly)
    _verify_seal(run, "utterance run")
    _verify_seal(corpus, "utterance corpus")
    if (
        corpus.run_id != run.run_id
        or corpus.corpus_id != run.utterance_corpus_id
        or corpus.phase2_transcript_assembly_id != assembly.assembly_id
        or corpus.phase2_transcript_version_id != assembly.version.version_id
        or run.utterance_ids
        != tuple(item.utterance_id for item in corpus.utterances)
    ):
        raise UtteranceAnalysisIntegrityError(
            "analysis input lineage is incompatible"
        )
    for utterance in corpus.utterances:
        _verify_seal(utterance, utterance.utterance_id)
        _verify_seal(
            utterance.attribution, utterance.attribution.attribution_id
        )
        for component in utterance.components:
            _verify_seal(component, component.component_id)
        for text_view in utterance.text_views:
            _verify_seal(text_view, text_view.view_id)
    owned_words = {
        word_id
        for utterance in corpus.utterances
        for component in utterance.components
        for word_id in component.transcript_word_ids
    }
    if owned_words != {item.word_id for item in assembly.words}:
        raise UtteranceAnalysisIntegrityError(
            "canonical transcript word ownership is incomplete"
        )


def analyze_utterance_corpus(
    run: UtteranceRun,
    corpus: UtteranceCorpus,
    assembly: TranscriptAssembly,
    *,
    policy: UtteranceAnalysisPolicy | None = None,
    created_at: datetime | None = None,
) -> UtteranceAnalysisRun:
    """Build a deterministic, non-destructive structural analysis."""
    _lineage(run, corpus, assembly)
    policy = policy or UtteranceAnalysisPolicy()
    created_at = created_at or corpus.created_at
    words = {item.word_id: item for item in assembly.words}
    assessments: list[UtteranceCompletenessAssessment] = []
    spans: list[DisfluencySpan] = []
    repairs: list[SelfRepair] = []
    for utterance in corpus.utterances:
        utterance_words = _utterance_words(utterance, words)
        assessments.append(
            _completeness(
                utterance, utterance_words, assembly, policy, created_at
            )
        )
        utterance_spans, utterance_repairs = _disfluencies_and_repairs(
            utterance, utterance_words, policy
        )
        spans.extend(utterance_spans)
        repairs.extend(utterance_repairs)
    configuration_hash = canonical_hash(
        {
            "utterance_run": run.integrity_sha256,
            "utterance_corpus": corpus.integrity_sha256,
            "transcript_assembly": assembly.integrity_sha256,
            "policy": policy.model_dump(mode="json"),
        }
    )
    analysis_id = typed_id(
        "utteranceanalysis", corpus.corpus_id, configuration_hash
    )
    return _seal(
        UtteranceAnalysisRun,
        {
            "analysis_id": analysis_id,
            "utterance_corpus_id": corpus.corpus_id,
            "utterance_run_id": run.run_id,
            "phase2_transcript_assembly_id": assembly.assembly_id,
            "policy": policy,
            "configuration_hash": configuration_hash,
            "completeness_assessments": tuple(assessments),
            "disfluency_spans": tuple(spans),
            "self_repairs": tuple(repairs),
            "created_at": created_at,
            "complete": True,
        },
    )


def _report(analysis: UtteranceAnalysisRun) -> UtteranceAnalysisReport:
    complete = sum(
        item.classification == UtteranceCompletenessClassification.COMPLETE
        for item in analysis.completeness_assessments
    )
    review_ids = {
        item.assessment_id
        for item in analysis.completeness_assessments
        if item.review_status == UtteranceReviewStatus.REVIEW_REQUIRED
    }
    review_ids.update(
        item.disfluency_id
        for item in analysis.disfluency_spans
        if item.review_status == UtteranceReviewStatus.REVIEW_REQUIRED
    )
    review_ids.update(
        item.self_repair_id
        for item in analysis.self_repairs
        if item.review_status == UtteranceReviewStatus.REVIEW_REQUIRED
    )
    payload = {
        "report_id": typed_id(
            "utteranceanalysisreport",
            analysis.analysis_id,
            analysis.integrity_sha256,
        ),
        "analysis_id": analysis.analysis_id,
        "utterance_corpus_id": analysis.utterance_corpus_id,
        "generated_at": analysis.created_at,
        "assessment_count": len(analysis.completeness_assessments),
        "complete_count": complete,
        "unresolved_count": len(analysis.completeness_assessments) - complete,
        "disfluency_count": len(analysis.disfluency_spans),
        "filler_count": sum(
            item.kind == DisfluencyKind.FILLER
            for item in analysis.disfluency_spans
        ),
        "repetition_count": sum(
            item.kind == DisfluencyKind.REPETITION
            for item in analysis.disfluency_spans
        ),
        "hesitation_count": sum(
            item.kind == DisfluencyKind.HESITATION
            for item in analysis.disfluency_spans
        ),
        "self_repair_count": len(analysis.self_repairs),
        "review_required_count": len(review_ids),
        "findings": (
            "Raw utterance wording is preserved; analysis is separately derived.",
        ),
        "limitations": (
            "Completeness uses observable boundary and punctuation signals only.",
            "Disfluency and self-repair records are candidates, not diagnoses.",
        ),
        "status": "complete",
    }
    return _seal(UtteranceAnalysisReport, payload)


def validate_utterance_analysis(
    analysis: UtteranceAnalysisRun,
    run: UtteranceRun,
    corpus: UtteranceCorpus,
    assembly: TranscriptAssembly,
    *,
    report: UtteranceAnalysisReport | None = None,
) -> None:
    _lineage(run, corpus, assembly)
    _verify_seal(analysis, "utterance analysis")
    for item in analysis.completeness_assessments:
        _verify_seal(item, item.assessment_id)
    for item in analysis.disfluency_spans:
        _verify_seal(item, item.disfluency_id)
    for item in analysis.self_repairs:
        _verify_seal(item, item.self_repair_id)
    if (
        analysis.utterance_corpus_id != corpus.corpus_id
        or analysis.utterance_run_id != run.run_id
        or analysis.phase2_transcript_assembly_id != assembly.assembly_id
        or tuple(item.utterance_id for item in analysis.completeness_assessments)
        != tuple(item.utterance_id for item in corpus.utterances)
    ):
        raise UtteranceAnalysisIntegrityError(
            "analysis and source corpus lineage disagree"
        )
    owners = {
        word_id: utterance.utterance_id
        for utterance in corpus.utterances
        for component in utterance.components
        for word_id in component.transcript_word_ids
    }
    for item in analysis.disfluency_spans:
        if any(owners.get(word_id) != item.utterance_id
               for word_id in item.transcript_word_ids):
            raise UtteranceAnalysisIntegrityError(
                "disfluency crosses an utterance ownership boundary"
            )
    for item in analysis.self_repairs:
        referenced = (
            item.reparandum_word_ids
            + item.repair_marker_word_ids
            + item.repair_word_ids
        )
        if any(owners.get(word_id) != item.utterance_id
               for word_id in referenced):
            raise UtteranceAnalysisIntegrityError(
                "self-repair crosses an utterance ownership boundary"
            )
    expected = analyze_utterance_corpus(
        run,
        corpus,
        assembly,
        policy=analysis.policy,
        created_at=analysis.created_at,
    )
    if expected != analysis:
        raise UtteranceAnalysisIntegrityError(
            "analysis is not the deterministic source projection"
        )
    if report is not None:
        _verify_seal(report, "utterance analysis report")
        if report != _report(analysis):
            raise UtteranceAnalysisIntegrityError(
                "utterance analysis report projection is invalid"
            )


def utterance_analysis_report_markdown(
    report: UtteranceAnalysisReport,
) -> str:
    return "\n".join(
        (
            "# Phase 4 completeness and disfluency report",
            "",
            f"- Analysis: `{report.analysis_id}`",
            f"- Assessments: {report.assessment_count}",
            f"- Complete: {report.complete_count}",
            f"- Unresolved or incomplete: {report.unresolved_count}",
            f"- Disfluency candidates: {report.disfluency_count}",
            f"- Self-repair candidates: {report.self_repair_count}",
            f"- Review required: {report.review_required_count}",
            f"- Status: {report.status}",
            "",
        )
    )


def persist_utterance_analysis(
    analysis: UtteranceAnalysisRun,
    run: UtteranceRun,
    corpus: UtteranceCorpus,
    assembly: TranscriptAssembly,
    destination: Path,
) -> tuple[UtteranceAnalysisRun, UtteranceAnalysisReport, Path, bool]:
    destination = destination.expanduser().resolve()
    validate_utterance_analysis(analysis, run, corpus, assembly)
    report = _report(analysis)
    root = destination / "utterance-analyses" / analysis.analysis_id
    paths = (
        root / "analysis.json",
        root / "report.json",
        root / "report.md",
    )
    existing = tuple(path.exists() for path in paths)
    if any(existing) and not all(existing):
        raise UtteranceAnalysisIntegrityError(
            "cached utterance analysis is incomplete"
        )
    if all(existing):
        stored_analysis = load_contract(
            paths[0].read_bytes(), UtteranceAnalysisRun
        )
        stored_report = load_contract(
            paths[1].read_bytes(), UtteranceAnalysisReport
        )
        validate_utterance_analysis(
            stored_analysis,
            run,
            corpus,
            assembly,
            report=stored_report,
        )
        if (
            stored_analysis != analysis
            or stored_report != report
            or paths[2].read_text(encoding="utf-8")
            != utterance_analysis_report_markdown(report)
        ):
            raise UtteranceAnalysisIntegrityError(
                "cached utterance analysis is incompatible"
            )
        return stored_analysis, stored_report, root, True
    _atomic(paths[0], canonical_bytes(analysis))
    _atomic(paths[1], canonical_bytes(report))
    _atomic(
        paths[2],
        utterance_analysis_report_markdown(report).encode("utf-8"),
    )
    return analysis, report, root, False


def load_utterance_analysis(
    root: Path,
) -> tuple[UtteranceAnalysisRun, UtteranceAnalysisReport]:
    root = root.expanduser().resolve(strict=True)
    return (
        load_contract(
            (root / "analysis.json").read_bytes(), UtteranceAnalysisRun
        ),
        load_contract(
            (root / "report.json").read_bytes(), UtteranceAnalysisReport
        ),
    )
