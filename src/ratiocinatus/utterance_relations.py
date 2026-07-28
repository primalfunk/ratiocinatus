"""Deterministic Phase 4 interruption, overlap, and continuation evidence."""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path

from .addressing_contracts import MediaInterval, TimeDomain
from .diarization_normalization import validate_diarization_run
from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase2_contracts import ConfidenceMeasure, ConfidenceOrigin
from .phase3_contracts import DiarizationRun, OverlapInterval
from .phase4_contracts import (
    Utterance,
    UtteranceAnalysisRun,
    UtteranceCompletenessClassification,
    UtteranceCorpus,
    UtteranceOverlapStatus,
    UtteranceReviewStatus,
    UtteranceRun,
)
from .utterance_relation_contracts import (
    ContinuationDisposition,
    ContinuationKind,
    ContinuationRelation,
    InterruptionKind,
    InterruptionRelation,
    OverlapAttributionDisposition,
    SpeakerConsistency,
    UtteranceAdjacencyRelation,
    UtteranceOverlapRelation,
    UtteranceRelationPolicy,
    UtteranceRelationReport,
    UtteranceRelationRun,
    UtteranceTemporalRelation,
)


class UtteranceRelationIntegrityError(RuntimeError):
    """Utterance relation evidence is corrupt or incompatible."""


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
        raise UtteranceRelationIntegrityError(f"{label} integrity is invalid")


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


def _end(interval: MediaInterval) -> int:
    return interval.start_microseconds + interval.duration_microseconds


def _bounds(utterance: Utterance) -> tuple[int, int]:
    return (
        min(
            item.start_microseconds
            for item in utterance.normalized_audio_intervals
        ),
        max(_end(item) for item in utterance.normalized_audio_intervals),
    )


def _intersection(
    left: tuple[int, int], right: MediaInterval
) -> tuple[int, int] | None:
    start = max(left[0], right.start_microseconds)
    end = min(left[1], _end(right))
    return (start, end) if end > start else None


def _target(utterance: Utterance) -> str | None:
    return utterance.attribution.target_id


def _lineage(
    utterance_run: UtteranceRun,
    corpus: UtteranceCorpus,
    analysis: UtteranceAnalysisRun,
    diarization: DiarizationRun,
) -> None:
    validate_diarization_run(diarization)
    _verify_seal(utterance_run, "utterance run")
    _verify_seal(corpus, "utterance corpus")
    _verify_seal(analysis, "utterance analysis")
    if (
        corpus.run_id != utterance_run.run_id
        or corpus.corpus_id != utterance_run.utterance_corpus_id
        or analysis.utterance_corpus_id != corpus.corpus_id
        or analysis.utterance_run_id != utterance_run.run_id
        or utterance_run.phase3_diarization_run_id != diarization.run_id
        or corpus.source_corpus_id != diarization.corpus_id
        or corpus.source_id != diarization.source_id
    ):
        raise UtteranceRelationIntegrityError(
            "relation input lineage is incompatible"
        )
    if tuple(item.utterance_id for item in corpus.utterances) != (
        utterance_run.utterance_ids
    ):
        raise UtteranceRelationIntegrityError(
            "utterance run ordering disagrees with corpus"
        )
    if tuple(
        item.utterance_id for item in analysis.completeness_assessments
    ) != tuple(item.utterance_id for item in corpus.utterances):
        raise UtteranceRelationIntegrityError(
            "analysis completeness coverage is incompatible"
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
    for item in analysis.completeness_assessments:
        _verify_seal(item, item.assessment_id)
    for item in analysis.disfluency_spans:
        _verify_seal(item, item.disfluency_id)
    for item in analysis.self_repairs:
        _verify_seal(item, item.self_repair_id)


def _ordered(corpus: UtteranceCorpus) -> tuple[Utterance, ...]:
    return tuple(
        sorted(
            corpus.utterances,
            key=lambda item: (_bounds(item)[0], item.utterance_id),
        )
    )


def _adjacencies(
    corpus: UtteranceCorpus,
    policy: UtteranceRelationPolicy,
) -> tuple[UtteranceAdjacencyRelation, ...]:
    ordered = _ordered(corpus)
    result: list[UtteranceAdjacencyRelation] = []
    for left, right in zip(ordered, ordered[1:]):
        left_start, left_end = _bounds(left)
        right_start, right_end = _bounds(right)
        signed_gap = right_start - left_end
        overlap_interval = None
        if right_start == left_start and signed_gap < 0:
            temporal = UtteranceTemporalRelation.SIMULTANEOUS_START
        elif signed_gap < 0:
            temporal = UtteranceTemporalRelation.OVERLAPPING
        elif signed_gap == 0:
            temporal = UtteranceTemporalRelation.TOUCHING
        else:
            temporal = UtteranceTemporalRelation.BEFORE
        if signed_gap < 0:
            overlap_start = right_start
            overlap_end = min(left_end, right_end)
            overlap_interval = MediaInterval(
                domain=TimeDomain.NORMALIZED_CORPUS,
                start_microseconds=overlap_start,
                duration_microseconds=overlap_end - overlap_start,
            )
        evidence = (left.utterance_id, right.utterance_id)
        result.append(
            _seal(
                UtteranceAdjacencyRelation,
                {
                    "adjacency_id": typed_id(
                        "utteranceadjacency",
                        corpus.corpus_id,
                        evidence,
                        temporal.value,
                        signed_gap,
                    ),
                    "utterance_corpus_id": corpus.corpus_id,
                    "preceding_utterance_id": left.utterance_id,
                    "following_utterance_id": right.utterance_id,
                    "temporal_relation": temporal,
                    "signed_gap_microseconds": signed_gap,
                    "overlap_normalized_audio_interval": overlap_interval,
                    "evidence_references": evidence,
                    "policy_version": policy.policy_version,
                },
            )
        )
    return tuple(result)


def _overlap_disposition(
    affected: tuple[Utterance, ...],
) -> OverlapAttributionDisposition:
    if not affected:
        return OverlapAttributionDisposition.UNTRANSCRIBED_OVERLAP
    if any(
        item.overlap_status
        == UtteranceOverlapStatus.UNCERTAIN_WORD_ATTRIBUTION
        or any(
            component.uncertain_word_attribution
            for component in item.components
        )
        for item in affected
    ):
        return OverlapAttributionDisposition.UNCERTAIN_WORD_ATTRIBUTION
    targets = tuple(_target(item) for item in affected)
    if (
        len(affected) >= 2
        and all(target is not None for target in targets)
        and len(set(targets)) == len(targets)
    ):
        return OverlapAttributionDisposition.SEPARATED_UTTERANCES
    return OverlapAttributionDisposition.MIXED_TRANSCRIPT


def _overlap_projection(
    corpus: UtteranceCorpus,
    overlap: OverlapInterval,
) -> UtteranceOverlapRelation:
    affected = tuple(
        item
        for item in _ordered(corpus)
        if _intersection(_bounds(item), overlap.normalized_audio_interval)
        is not None
    )
    disposition = _overlap_disposition(affected)
    affected_ids = tuple(item.utterance_id for item in affected)
    payload = {
        "overlap_relation_id": typed_id(
            "utteranceoverlap",
            corpus.corpus_id,
            overlap.overlap_id,
            affected_ids,
            disposition.value,
        ),
        "utterance_corpus_id": corpus.corpus_id,
        "phase3_overlap_id": overlap.overlap_id,
        "classification": overlap.classification,
        "source_interval": overlap.source_interval,
        "normalized_audio_interval": overlap.normalized_audio_interval,
        "affected_utterance_ids": affected_ids,
        "candidate_cluster_ids": overlap.candidate_cluster_ids,
        "disposition": disposition,
        "partially_attributed": (
            overlap.partially_attributed
            or disposition
            != OverlapAttributionDisposition.SEPARATED_UTTERANCES
        ),
        "evidence_references": (overlap.overlap_id,) + affected_ids,
        "confidence": overlap.overlap_confidence,
        "review_status": UtteranceReviewStatus.REVIEW_REQUIRED,
    }
    return _seal(UtteranceOverlapRelation, payload)


def _continuations(
    corpus: UtteranceCorpus,
    analysis: UtteranceAnalysisRun,
    policy: UtteranceRelationPolicy,
) -> tuple[ContinuationRelation, ...]:
    ordered = _ordered(corpus)
    assessments = {
        item.utterance_id: item for item in analysis.completeness_assessments
    }
    result: list[ContinuationRelation] = []
    for index, predecessor in enumerate(ordered[:-2]):
        assessment = assessments[predecessor.utterance_id]
        if assessment.classification in {
            UtteranceCompletenessClassification.COMPLETE,
            UtteranceCompletenessClassification.NON_LEXICAL,
        }:
            continue
        predecessor_target = _target(predecessor)
        if predecessor_target is None:
            continue
        predecessor_end = _bounds(predecessor)[1]
        for successor_index in range(index + 2, len(ordered)):
            successor = ordered[successor_index]
            if _target(successor) != predecessor_target:
                continue
            elapsed = _bounds(successor)[0] - predecessor_end
            if elapsed < 0:
                continue
            if elapsed > policy.continuation_max_gap_microseconds:
                break
            intervening = tuple(
                item.utterance_id
                for item in ordered[index + 1:successor_index]
            )

            payload = {
                "continuation_id": typed_id(
                    "continuation",
                    corpus.corpus_id,
                    predecessor.utterance_id,
                    successor.utterance_id,
                    intervening,
                    elapsed,
                ),
                "utterance_corpus_id": corpus.corpus_id,
                "predecessor_utterance_id": predecessor.utterance_id,
                "successor_utterance_id": successor.utterance_id,
                "intervening_utterance_ids": intervening,
                "elapsed_gap_microseconds": elapsed,
                "speaker_consistency": SpeakerConsistency.SAME_ATTRIBUTION,
                "kind": ContinuationKind.UNRESOLVED,
                "lexical_or_syntactic_evidence": (),
                "semantic_continuation_evidence": (),
                "semantic_inference_used": False,
                "confidence": _confidence(
                    0.65, "bounded temporal and attribution evidence only"
                ),
                "disposition": ContinuationDisposition.UNRESOLVED,
                "review_status": UtteranceReviewStatus.REVIEW_REQUIRED,
                "policy_version": policy.policy_version,
            }
            result.append(_seal(ContinuationRelation, payload))
            break
    return tuple(result)


def _interruptions(
    corpus: UtteranceCorpus,
    analysis: UtteranceAnalysisRun,
    adjacencies: tuple[UtteranceAdjacencyRelation, ...],
    overlaps: tuple[UtteranceOverlapRelation, ...],
    continuations: tuple[ContinuationRelation, ...],
    policy: UtteranceRelationPolicy,
) -> tuple[InterruptionRelation, ...]:
    utterances = {item.utterance_id: item for item in corpus.utterances}
    assessments = {
        item.utterance_id: item for item in analysis.completeness_assessments
    }
    continuation_by_predecessor = {
        item.predecessor_utterance_id: item for item in continuations
    }
    result: list[InterruptionRelation] = []
    for overlap in overlaps:
        if len(overlap.affected_utterance_ids) < 2:
            continue
        affected = tuple(
            sorted(
                (
                    utterances[item]
                    for item in overlap.affected_utterance_ids
                ),
                key=lambda item: (_bounds(item)[0], item.utterance_id),
            )
        )
        interrupted, interrupting = affected[:2]
        interrupted_start, interrupted_end = _bounds(interrupted)
        interrupting_start, _ = _bounds(interrupting)
        different_targets = (
            _target(interrupted) is not None
            and _target(interrupting) is not None
            and _target(interrupted) != _target(interrupting)
        )
        kind = (
            InterruptionKind.ACTUAL_SIMULTANEOUS
            if different_targets
            else InterruptionKind.UNCERTAIN
        )
        continuation = continuation_by_predecessor.get(
            interrupted.utterance_id
        )
        evidence = (
            overlap.overlap_relation_id,
            overlap.phase3_overlap_id,
            interrupted.utterance_id,
            interrupting.utterance_id,
        )
        payload = {
            "interruption_id": typed_id(
                "interruption",
                corpus.corpus_id,
                evidence,
                kind.value,
            ),
            "utterance_corpus_id": corpus.corpus_id,
            "interrupted_utterance_id": interrupted.utterance_id,
            "interrupting_utterance_id": interrupting.utterance_id,
            "interruption_onset_normalized_microseconds": max(
                interrupted_start, interrupting_start
            ),
            "interrupting_speaker_target_id": _target(interrupting),
            "kind": kind,
            "overlap_relation_id": overlap.overlap_relation_id,
            "original_speaker_continues_underneath": (
                interrupted_end > interrupting_start
            ),
            "original_utterance_resumes": continuation is not None,
            "continuation_relation_id": (
                continuation.continuation_id
                if continuation is not None
                else None
            ),
            "temporal_evidence_references": evidence,
            "confidence": _confidence(
                0.85 if different_targets else 0.55,
                "Phase 3 overlap projected onto utterance timelines",
            ),
            "review_status": UtteranceReviewStatus.REVIEW_REQUIRED,
            "policy_version": policy.policy_version,
        }
        result.append(_seal(InterruptionRelation, payload))
    overlap_pairs = {
        frozenset(item.affected_utterance_ids)
        for item in overlaps
        if len(item.affected_utterance_ids) >= 2
    }
    takeover_classes = {
        UtteranceCompletenessClassification.ABANDONED,
        UtteranceCompletenessClassification.TRAILING_OFF,
        UtteranceCompletenessClassification.INTERRUPTED,
    }
    for adjacency in adjacencies:
        pair = frozenset(
            (
                adjacency.preceding_utterance_id,
                adjacency.following_utterance_id,
            )
        )
        if pair in overlap_pairs:
            continue
        if (
            adjacency.signed_gap_microseconds < 0
            or adjacency.signed_gap_microseconds
            > policy.immediate_takeover_max_gap_microseconds
        ):
            continue
        interrupted = utterances[adjacency.preceding_utterance_id]
        interrupting = utterances[adjacency.following_utterance_id]
        interrupted_assessment = assessments[interrupted.utterance_id]
        terminal_interruption_signal = any(
            signal in {
                "terminal ellipsis observed",
                "terminal dash observed",
            }
            for signal in interrupted_assessment.observed_signals
        )
        if (
            interrupted_assessment.classification not in takeover_classes
            and not terminal_interruption_signal
        ) or (
            _target(interrupted) is None
            or _target(interrupted) == _target(interrupting)
        ):
            continue
        continuation = continuation_by_predecessor.get(
            interrupted.utterance_id
        )
        evidence = (
            adjacency.adjacency_id,
            interrupted.utterance_id,
            interrupting.utterance_id,
        )
        result.append(
            _seal(
                InterruptionRelation,
                {
                    "interruption_id": typed_id(
                        "interruption",
                        corpus.corpus_id,
                        evidence,
                        InterruptionKind.IMMEDIATE_TURN_TAKEOVER.value,
                    ),
                    "utterance_corpus_id": corpus.corpus_id,
                    "interrupted_utterance_id": interrupted.utterance_id,
                    "interrupting_utterance_id": interrupting.utterance_id,
                    "interruption_onset_normalized_microseconds": _bounds(
                        interrupting
                    )[0],
                    "interrupting_speaker_target_id": _target(interrupting),
                    "kind": InterruptionKind.IMMEDIATE_TURN_TAKEOVER,
                    "overlap_relation_id": None,
                    "original_speaker_continues_underneath": False,
                    "original_utterance_resumes": continuation is not None,
                    "continuation_relation_id": (
                        continuation.continuation_id
                        if continuation is not None
                        else None
                    ),
                    "temporal_evidence_references": evidence,
                    "confidence": _confidence(
                        0.65,
                        "short takeover gap plus incomplete terminal signal",
                    ),
                    "review_status": UtteranceReviewStatus.REVIEW_REQUIRED,
                    "policy_version": policy.policy_version,
                },
            )
        )
    return tuple(result)


def build_utterance_relations(
    utterance_run: UtteranceRun,
    corpus: UtteranceCorpus,
    analysis: UtteranceAnalysisRun,
    diarization: DiarizationRun,
    *,
    policy: UtteranceRelationPolicy | None = None,
    created_at: datetime | None = None,
) -> UtteranceRelationRun:
    """Project temporal relations without assigning intent or blame."""
    _lineage(utterance_run, corpus, analysis, diarization)
    policy = policy or UtteranceRelationPolicy()
    timestamp = created_at or analysis.created_at
    adjacencies = _adjacencies(corpus, policy)
    overlaps = tuple(
        _overlap_projection(corpus, item) for item in diarization.overlaps
    )
    continuations = _continuations(corpus, analysis, policy)
    interruptions = _interruptions(
        corpus,
        analysis,
        adjacencies,
        overlaps,
        continuations,
        policy,
    )
    configuration_hash = canonical_hash(
        {
            "utterance_run": utterance_run.integrity_sha256,
            "utterance_corpus": corpus.integrity_sha256,
            "utterance_analysis": analysis.integrity_sha256,
            "diarization": diarization.integrity_sha256,
            "policy": policy.model_dump(mode="json"),
        }
    )
    relation_run_id = typed_id(
        "utterancerelations", corpus.corpus_id, configuration_hash
    )
    return _seal(
        UtteranceRelationRun,
        {
            "relation_run_id": relation_run_id,
            "utterance_corpus_id": corpus.corpus_id,
            "utterance_run_id": utterance_run.run_id,
            "utterance_analysis_id": analysis.analysis_id,
            "phase3_diarization_run_id": diarization.run_id,
            "policy": policy,
            "configuration_hash": configuration_hash,
            "adjacencies": adjacencies,
            "overlaps": overlaps,
            "interruptions": interruptions,
            "continuations": continuations,
            "created_at": timestamp,
            "complete": True,
        },
    )


def _report(relations: UtteranceRelationRun) -> UtteranceRelationReport:
    unresolved = sum(
        item.kind == InterruptionKind.UNCERTAIN
        for item in relations.interruptions
    ) + sum(
        item.disposition == ContinuationDisposition.UNRESOLVED
        for item in relations.continuations
    )
    review_ids = {
        item.overlap_relation_id
        for item in relations.overlaps
        if item.review_status == UtteranceReviewStatus.REVIEW_REQUIRED
    }
    review_ids.update(
        item.interruption_id
        for item in relations.interruptions
        if item.review_status == UtteranceReviewStatus.REVIEW_REQUIRED
    )
    review_ids.update(
        item.continuation_id
        for item in relations.continuations
        if item.review_status == UtteranceReviewStatus.REVIEW_REQUIRED
    )
    return _seal(
        UtteranceRelationReport,
        {
            "report_id": typed_id(
                "utterancerelationreport",
                relations.relation_run_id,
                relations.integrity_sha256,
            ),
            "relation_run_id": relations.relation_run_id,
            "utterance_corpus_id": relations.utterance_corpus_id,
            "generated_at": relations.created_at,
            "adjacency_count": len(relations.adjacencies),
            "overlap_count": len(relations.overlaps),
            "overlap_duration_microseconds": sum(
                item.normalized_audio_interval.duration_microseconds
                for item in relations.overlaps
            ),
            "interruption_count": len(relations.interruptions),
            "continuation_count": len(relations.continuations),
            "unresolved_count": unresolved,
            "review_required_count": len(review_ids),
            "limitations": (
                "Temporal interruption candidates do not establish intent or blame.",
                "Supportive interjection and backchannel classes are not inferred.",
                "Continuation candidates do not use semantic similarity.",
            ),
            "status": "warning" if unresolved else "complete",
        },
    )


def validate_utterance_relations(
    relations: UtteranceRelationRun,
    utterance_run: UtteranceRun,
    corpus: UtteranceCorpus,
    analysis: UtteranceAnalysisRun,
    diarization: DiarizationRun,
    *,
    report: UtteranceRelationReport | None = None,
) -> None:
    _lineage(utterance_run, corpus, analysis, diarization)
    _verify_seal(relations, "utterance relation run")
    for item in relations.adjacencies:
        _verify_seal(item, item.adjacency_id)
    for item in relations.overlaps:
        _verify_seal(item, item.overlap_relation_id)
    for item in relations.interruptions:
        _verify_seal(item, item.interruption_id)
    for item in relations.continuations:
        _verify_seal(item, item.continuation_id)
    if (
        relations.utterance_corpus_id != corpus.corpus_id
        or relations.utterance_run_id != utterance_run.run_id
        or relations.utterance_analysis_id != analysis.analysis_id
        or relations.phase3_diarization_run_id != diarization.run_id
    ):
        raise UtteranceRelationIntegrityError(
            "relation run and source lineage disagree"
        )
    utterance_ids = {item.utterance_id for item in corpus.utterances}
    phase3_overlap_ids = {item.overlap_id for item in diarization.overlaps}
    for item in relations.adjacencies:
        if {
            item.preceding_utterance_id,
            item.following_utterance_id,
        } - utterance_ids:
            raise UtteranceRelationIntegrityError(
                "adjacency references unknown utterance"
            )
    for item in relations.overlaps:
        if (
            item.phase3_overlap_id not in phase3_overlap_ids
            or set(item.affected_utterance_ids) - utterance_ids
        ):
            raise UtteranceRelationIntegrityError(
                "overlap projection references unknown evidence"
            )
    overlap_ids = {
        item.overlap_relation_id: item for item in relations.overlaps
    }
    adjacency_ids = {item.adjacency_id for item in relations.adjacencies}
    continuation_ids = {
        item.continuation_id: item for item in relations.continuations
    }
    for item in relations.interruptions:
        if item.interrupted_utterance_id not in utterance_ids or (
            item.interrupting_utterance_id is not None
            and item.interrupting_utterance_id not in utterance_ids
        ):
            raise UtteranceRelationIntegrityError(
                "interruption references unknown utterance"
            )
        if item.kind == InterruptionKind.ACTUAL_SIMULTANEOUS:
            overlap = overlap_ids.get(item.overlap_relation_id or "")
            if overlap is None or not {
                item.interrupted_utterance_id,
                item.interrupting_utterance_id,
            }.issubset(overlap.affected_utterance_ids):
                raise UtteranceRelationIntegrityError(
                    "simultaneous interruption lacks temporal support"
                )
        if item.kind == InterruptionKind.IMMEDIATE_TURN_TAKEOVER and not (
            set(item.temporal_evidence_references).intersection(adjacency_ids)
        ):
            raise UtteranceRelationIntegrityError(
                "takeover interruption lacks adjacency support"
            )
        if (
            item.continuation_relation_id is not None
            and item.continuation_relation_id not in continuation_ids
        ):
            raise UtteranceRelationIntegrityError(
                "interruption references unknown continuation"
            )
    order = {
        item.utterance_id: index
        for index, item in enumerate(_ordered(corpus))
    }
    for item in relations.continuations:
        if (
            order.get(item.predecessor_utterance_id, -1)
            >= order.get(item.successor_utterance_id, -1)
            or set(item.intervening_utterance_ids) - utterance_ids
        ):
            raise UtteranceRelationIntegrityError(
                "continuation ordering is impossible"
            )
    expected = build_utterance_relations(
        utterance_run,
        corpus,
        analysis,
        diarization,
        policy=relations.policy,
        created_at=relations.created_at,
    )
    if expected != relations:
        raise UtteranceRelationIntegrityError(
            "relations are not the deterministic source projection"
        )
    if report is not None:
        _verify_seal(report, "utterance relation report")
        if report != _report(relations):
            raise UtteranceRelationIntegrityError(
                "utterance relation report projection is invalid"
            )


def utterance_relation_report_markdown(
    report: UtteranceRelationReport,
) -> str:
    return "\n".join(
        (
            "# Phase 4 interruption and overlap report",
            "",
            f"- Relation run: `{report.relation_run_id}`",
            f"- Adjacencies: {report.adjacency_count}",
            f"- Phase 3 overlaps preserved: {report.overlap_count}",
            f"- Overlap duration: {report.overlap_duration_microseconds} us",
            f"- Interruption candidates: {report.interruption_count}",
            f"- Continuation candidates: {report.continuation_count}",
            f"- Unresolved: {report.unresolved_count}",
            f"- Review required: {report.review_required_count}",
            f"- Status: {report.status}",
            "",
        )
    )


def persist_utterance_relations(
    relations: UtteranceRelationRun,
    utterance_run: UtteranceRun,
    corpus: UtteranceCorpus,
    analysis: UtteranceAnalysisRun,
    diarization: DiarizationRun,
    destination: Path,
) -> tuple[UtteranceRelationRun, UtteranceRelationReport, Path, bool]:
    destination = destination.expanduser().resolve()
    validate_utterance_relations(
        relations, utterance_run, corpus, analysis, diarization
    )
    report = _report(relations)
    root = destination / "utterance-relations" / relations.relation_run_id
    paths = (
        root / "relations.json",
        root / "report.json",
        root / "report.md",
    )
    existing = tuple(path.exists() for path in paths)
    if any(existing) and not all(existing):
        raise UtteranceRelationIntegrityError(
            "cached utterance relations are incomplete"
        )
    if all(existing):
        stored = load_contract(paths[0].read_bytes(), UtteranceRelationRun)
        stored_report = load_contract(
            paths[1].read_bytes(), UtteranceRelationReport
        )
        validate_utterance_relations(
            stored,
            utterance_run,
            corpus,
            analysis,
            diarization,
            report=stored_report,
        )
        if (
            stored != relations
            or stored_report != report
            or paths[2].read_text(encoding="utf-8")
            != utterance_relation_report_markdown(report)
        ):
            raise UtteranceRelationIntegrityError(
                "cached utterance relations are incompatible"
            )
        return stored, stored_report, root, True
    _atomic(paths[0], canonical_bytes(relations))
    _atomic(paths[1], canonical_bytes(report))
    _atomic(
        paths[2],
        utterance_relation_report_markdown(report).encode("utf-8"),
    )
    return relations, report, root, False


def load_utterance_relations(
    root: Path,
) -> tuple[UtteranceRelationRun, UtteranceRelationReport]:
    root = root.expanduser().resolve(strict=True)
    return (
        load_contract(
            (root / "relations.json").read_bytes(), UtteranceRelationRun
        ),
        load_contract(
            (root / "report.json").read_bytes(), UtteranceRelationReport
        ),
    )
