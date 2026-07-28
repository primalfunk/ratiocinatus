"""Selective Phase 4 correction-impact analysis and successor validation."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .context_window_contracts import ContextWindowBundle, ContextWindowPolicy
from .context_windows import build_context_windows, validate_context_windows
from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase4_contracts import (
    Utterance,
    UtteranceAnalysisRun,
    UtteranceCorpus,
    UtteranceRun,
    UtteranceTextKind,
    UtteranceSegmentationPolicy,
)
from .phase4_review_contracts import (
    Phase4ChangeKind,
    Phase4InvalidationKind,
    Phase4PropagationPolicy,
    Phase4PropagationReport,
    Phase4PropagationRun,
    UtteranceMappingDisposition,
    UtterancePropagationImpact,
)
from .quotation_contracts import QuotationEvidenceRun
from .quotation_evidence import build_quotation_evidence
from .turn_repair_contracts import TurnRepairRun
from .turn_repair import build_turn_repair_run
from .utterance_relation_contracts import UtteranceRelationRun
from .utterance_relations import build_utterance_relations
from .utterance_view_contracts import (
    SpeakerAttributedTranscriptBundle,
    SpeakerAttributedTranscriptPolicy,
)
from .utterance_analysis import analyze_utterance_corpus
from .utterance_segmentation import build_utterance_corpus
from .speaker_transcript_contracts import SpeakerLabeledTranscriptView
from .transcript_contracts import TranscriptAssembly
from .phase3_contracts import DiarizationRun
from .utterance_views import (
    build_speaker_attributed_views,
    validate_speaker_attributed_views,
)


class Phase4PropagationIntegrityError(RuntimeError):
    """Propagation evidence is corrupt, stale, or incompatible."""


@dataclass(frozen=True)
class Phase4ArtifactSet:
    utterance_run: UtteranceRun
    corpus: UtteranceCorpus
    analysis: UtteranceAnalysisRun
    relations: UtteranceRelationRun
    repair: TurnRepairRun
    quotation: QuotationEvidenceRun
    transcript_views: SpeakerAttributedTranscriptBundle
    context_windows: ContextWindowBundle


def rebuild_phase4_artifact_set(
    assembly: TranscriptAssembly,
    speaker_view: SpeakerLabeledTranscriptView,
    diarization: DiarizationRun,
    *,
    segmentation_policy: UtteranceSegmentationPolicy | None = None,
    transcript_view_policy: SpeakerAttributedTranscriptPolicy | None = None,
    context_policy: ContextWindowPolicy | None = None,
    created_at: datetime | None = None,
) -> Phase4ArtifactSet:
    """Rebuild the complete Phase 4 successor chain from new Phase 2/3 evidence."""
    utterance_run, corpus = build_utterance_corpus(
        assembly,
        speaker_view,
        diarization,
        policy=segmentation_policy,
        created_at=created_at,
    )
    analysis = analyze_utterance_corpus(
        utterance_run, corpus, assembly, created_at=created_at
    )
    relations = build_utterance_relations(
        utterance_run, corpus, analysis, diarization, created_at=created_at
    )
    repair = build_turn_repair_run(
        utterance_run,
        corpus,
        assembly,
        speaker_view,
        diarization,
        created_at=created_at,
    )
    quotation = build_quotation_evidence(
        utterance_run, corpus, assembly, created_at=created_at
    )
    sources = (
        utterance_run,
        corpus,
        analysis,
        relations,
        repair,
        quotation,
    )
    views = build_speaker_attributed_views(
        *sources, policy=transcript_view_policy, generated_at=created_at
    )
    contexts = build_context_windows(
        views, *sources, policy=context_policy, created_at=created_at
    )
    artifacts = Phase4ArtifactSet(*sources, views, contexts)
    validate_phase4_artifact_set(artifacts)
    return artifacts

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
        raise Phase4PropagationIntegrityError(f"{label} integrity is invalid")


def _validate_set(artifacts: Phase4ArtifactSet) -> None:
    sources = (
        artifacts.utterance_run,
        artifacts.corpus,
        artifacts.analysis,
        artifacts.relations,
        artifacts.repair,
        artifacts.quotation,
    )
    validate_speaker_attributed_views(artifacts.transcript_views, *sources)
    validate_context_windows(
        artifacts.context_windows, artifacts.transcript_views, *sources
    )


def validate_phase4_artifact_set(artifacts: Phase4ArtifactSet) -> None:
    """Validate one complete Phase 4 dependency chain."""
    _validate_set(artifacts)

def _text(utterance: Utterance) -> str:
    return next(
        item.text
        for item in utterance.text_views
        if item.kind == UtteranceTextKind.DISPLAY
    )


def _word_ids(utterance: Utterance) -> frozenset[str]:
    return frozenset(
        word_id
        for component in utterance.components
        for word_id in component.transcript_word_ids
    )


def _bounds(utterance: Utterance) -> tuple[int, int]:
    starts = [
        item.start_microseconds for item in utterance.normalized_audio_intervals
    ]
    ends = [
        item.start_microseconds + item.duration_microseconds
        for item in utterance.normalized_audio_intervals
    ]
    return min(starts), max(ends)


def _mapping_score(
    predecessor: Utterance,
    successor: Utterance,
    tolerance: int,
) -> tuple[int, int, int] | None:
    old_words = _word_ids(predecessor)
    new_words = _word_ids(successor)
    intersection = len(old_words.intersection(new_words))
    if old_words and old_words == new_words:
        return 3, intersection, 0
    if intersection:
        return 2, intersection, -abs(len(old_words) - len(new_words))
    old_start, old_end = _bounds(predecessor)
    new_start, new_end = _bounds(successor)
    overlap = min(old_end, new_end) - max(old_start, new_start)
    gap = max(old_start - new_end, new_start - old_end, 0)
    if overlap > 0 or gap <= tolerance:
        return 1, max(overlap, 0), -gap
    return None


def _candidate_map(
    predecessors: tuple[Utterance, ...],
    successors: tuple[Utterance, ...],
    policy: Phase4PropagationPolicy,
) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    forward: dict[str, tuple[str, ...]] = {}
    reverse_values: dict[str, list[str]] = {
        item.utterance_id: [] for item in successors
    }
    successor_ids = {item.utterance_id for item in successors}
    for predecessor in predecessors:
        scored = []
        if predecessor.utterance_id in successor_ids:
            forward[predecessor.utterance_id] = (predecessor.utterance_id,)
            reverse_values[predecessor.utterance_id].append(
                predecessor.utterance_id
            )
            continue
        for successor in successors:
            score = _mapping_score(
                predecessor,
                successor,
                policy.temporal_mapping_tolerance_microseconds,
            )
            if score is not None:
                scored.append((score, successor.utterance_id))
        if not scored:
            forward[predecessor.utterance_id] = ()
            continue
        best_tier = max(item[0][0] for item in scored)
        candidates = tuple(
            sorted(
                item[1] for item in scored if item[0][0] == best_tier
            )
        )
        forward[predecessor.utterance_id] = candidates
        for successor_id in candidates:
            reverse_values[successor_id].append(predecessor.utterance_id)
    reverse = {
        key: tuple(sorted(values)) for key, values in reverse_values.items()
    }
    return forward, reverse


def _change_kinds(
    predecessors: tuple[Utterance, ...],
    successors: tuple[Utterance, ...],
    disposition: UtteranceMappingDisposition,
) -> tuple[Phase4ChangeKind, ...]:
    if len(predecessors) != 1 or len(successors) != 1:
        changes = {Phase4ChangeKind.SEGMENTATION}
        if not predecessors or not successors:
            changes.add(Phase4ChangeKind.SOURCE_LINEAGE)
        return tuple(sorted(changes, key=lambda item: item.value))
    old, new = predecessors[0], successors[0]
    changes: set[Phase4ChangeKind] = set()
    if _text(old) != _text(new):
        changes.add(Phase4ChangeKind.TEXT_ONLY)
    if (
        old.source_intervals != new.source_intervals
        or old.normalized_audio_intervals != new.normalized_audio_intervals
    ):
        changes.add(Phase4ChangeKind.TIMING)
    if (
        old.attribution.status != new.attribution.status
        or old.attribution.target_kind != new.attribution.target_kind
        or old.attribution.target_id != new.attribution.target_id
        or old.attribution.candidate_target_ids
        != new.attribution.candidate_target_ids
    ):
        changes.add(Phase4ChangeKind.SPEAKER_ATTRIBUTION)
    elif old.attribution.display_label != new.attribution.display_label:
        changes.add(Phase4ChangeKind.DISPLAY_LABEL)
    if (
        _word_ids(old) != _word_ids(new)
        or len(old.components) != len(new.components)
        or disposition
        in {
            UtteranceMappingDisposition.SPLIT,
            UtteranceMappingDisposition.MERGED,
        }
    ):
        changes.add(Phase4ChangeKind.SEGMENTATION)
    if (
        old.source_corpus_id != new.source_corpus_id
        or old.source_id != new.source_id
    ):
        changes.add(Phase4ChangeKind.SOURCE_LINEAGE)
    return tuple(sorted(changes, key=lambda item: item.value))


def _invalidations(
    changes: tuple[Phase4ChangeKind, ...],
) -> tuple[Phase4InvalidationKind, ...]:
    if not changes:
        return ()
    values = {
        Phase4InvalidationKind.TRANSCRIPT_VIEWS,
        Phase4InvalidationKind.CONTEXT_WINDOWS,
    }
    if set(changes) != {Phase4ChangeKind.DISPLAY_LABEL}:
        values.add(Phase4InvalidationKind.UTTERANCE)
    if set(changes).intersection(
        {
            Phase4ChangeKind.TEXT_ONLY,
            Phase4ChangeKind.TIMING,
            Phase4ChangeKind.SPEAKER_ATTRIBUTION,
            Phase4ChangeKind.SEGMENTATION,
            Phase4ChangeKind.SOURCE_LINEAGE,
        }
    ):
        values.update(
            {
                Phase4InvalidationKind.STRUCTURAL_ANALYSIS,
                Phase4InvalidationKind.TEMPORAL_RELATIONS,
                Phase4InvalidationKind.TURN_REPAIR,
                Phase4InvalidationKind.QUOTATION,
            }
        )
    return tuple(sorted(values, key=lambda item: item.value))


def build_phase4_propagation(
    predecessor: Phase4ArtifactSet,
    successor: Phase4ArtifactSet,
    *,
    policy: Phase4PropagationPolicy | None = None,
    created_at: datetime | None = None,
) -> Phase4PropagationRun:
    """Compare validated predecessor and rebuilt successor artifact chains."""
    _validate_set(predecessor)
    _validate_set(successor)
    policy = policy or Phase4PropagationPolicy()
    timestamp = created_at or successor.context_windows.created_at
    old_values = predecessor.corpus.utterances
    new_values = successor.corpus.utterances
    old_by_id = {item.utterance_id: item for item in old_values}
    new_by_id = {item.utterance_id: item for item in new_values}
    forward, reverse = _candidate_map(old_values, new_values, policy)
    configuration_hash = canonical_hash(
        {
            "predecessor_context": (
                predecessor.context_windows.integrity_sha256
            ),
            "successor_context": successor.context_windows.integrity_sha256,
            "policy": policy.model_dump(mode="json"),
        }
    )
    run_id = typed_id(
        "phase4propagation",
        predecessor.corpus.corpus_id,
        successor.corpus.corpus_id,
        configuration_hash,
    )
    impacts = []
    referenced_successors: set[str] = set()
    for predecessor_id in sorted(forward):
        successor_ids = forward[predecessor_id]
        referenced_successors.update(successor_ids)
        predecessor_values = (old_by_id[predecessor_id],)
        successor_values = tuple(new_by_id[item] for item in successor_ids)
        if not successor_ids:
            disposition = UtteranceMappingDisposition.REMOVED
        elif len(successor_ids) > 1:
            disposition = UtteranceMappingDisposition.SPLIT
        elif len(reverse[successor_ids[0]]) > 1:
            disposition = UtteranceMappingDisposition.MERGED
            predecessor_values = tuple(
                old_by_id[item] for item in reverse[successor_ids[0]]
            )
        else:
            provisional_changes = _change_kinds(
                predecessor_values,
                successor_values,
                UtteranceMappingDisposition.REBUILT_ONE_TO_ONE,
            )
            disposition = (
                UtteranceMappingDisposition.UNCHANGED_EQUIVALENT
                if not provisional_changes
                else UtteranceMappingDisposition.REBUILT_ONE_TO_ONE
            )
        changes = _change_kinds(
            predecessor_values, successor_values, disposition
        )
        invalidations = _invalidations(changes)
        segmentation_review = (
            Phase4ChangeKind.SEGMENTATION in changes
            or (
                Phase4ChangeKind.TIMING in changes
                and policy.boundary_crossing_requires_segmentation_review
            )
        )
        explanation = (
            "Predecessor evidence is unchanged and remains reusable."
            if not changes
            else (
                "Successor evidence was rebuilt; predecessor artifacts remain "
                "preserved and the listed dependent artifacts are invalidated."
            )
        )
        impact_predecessors = tuple(
            sorted(item.utterance_id for item in predecessor_values)
        )
        impact_successors = tuple(
            sorted(item.utterance_id for item in successor_values)
        )
        impact_key = (
            impact_predecessors,
            impact_successors,
            tuple(item.value for item in changes),
        )
        impact = _seal(
            UtterancePropagationImpact,
            {
                "impact_id": typed_id(
                    "propagationimpact", run_id, impact_key
                ),
                "predecessor_utterance_ids": impact_predecessors,
                "successor_utterance_ids": impact_successors,
                "disposition": disposition,
                "change_kinds": changes,
                "invalidated_artifact_kinds": invalidations,
                "affected": bool(changes),
                "segmentation_review_required": segmentation_review,
                "predecessor_identifier_preserved": (
                    impact_predecessors == impact_successors
                ),
                "explanation": explanation,
                "evidence_references": tuple(
                    sorted(
                        {
                            predecessor.corpus.corpus_id,
                            successor.corpus.corpus_id,
                            *impact_predecessors,
                            *impact_successors,
                        }
                    )
                ),
            },
        )
        if impact not in impacts:
            impacts.append(impact)
    for successor_id in sorted(set(new_by_id) - referenced_successors):
        changes = (
            Phase4ChangeKind.SEGMENTATION,
            Phase4ChangeKind.SOURCE_LINEAGE,
        )
        impacts.append(
            _seal(
                UtterancePropagationImpact,
                {
                    "impact_id": typed_id(
                        "propagationimpact", run_id, "added", successor_id
                    ),
                    "predecessor_utterance_ids": (),
                    "successor_utterance_ids": (successor_id,),
                    "disposition": UtteranceMappingDisposition.ADDED,
                    "change_kinds": changes,
                    "invalidated_artifact_kinds": _invalidations(changes),
                    "affected": True,
                    "segmentation_review_required": True,
                    "predecessor_identifier_preserved": False,
                    "explanation": (
                        "The rebuilt corpus contains a new utterance without "
                        "a unique predecessor mapping."
                    ),
                    "evidence_references": (
                        successor.corpus.corpus_id,
                        successor_id,
                    ),
                },
            )
        )
    predecessor_impacts = [
        item for item in impacts if item.predecessor_utterance_ids
    ]
    changed = tuple(
        sorted(
            {
                utterance_id
                for item in predecessor_impacts
                if item.affected
                for utterance_id in item.predecessor_utterance_ids
            }
        )
    )
    unaffected = tuple(
        sorted(set(old_by_id) - set(changed))
    )
    return _seal(
        Phase4PropagationRun,
        {
            "propagation_run_id": run_id,
            "predecessor_utterance_corpus_id": predecessor.corpus.corpus_id,
            "successor_utterance_corpus_id": successor.corpus.corpus_id,
            "predecessor_transcript_view_bundle_id": (
                predecessor.transcript_views.bundle_id
            ),
            "successor_transcript_view_bundle_id": (
                successor.transcript_views.bundle_id
            ),
            "predecessor_context_bundle_id": (
                predecessor.context_windows.context_bundle_id
            ),
            "successor_context_bundle_id": (
                successor.context_windows.context_bundle_id
            ),
            "policy": policy,
            "configuration_hash": configuration_hash,
            "impacts": tuple(impacts),
            "changed_predecessor_utterance_ids": changed,
            "unaffected_predecessor_utterance_ids": unaffected,
            "created_at": timestamp,
            "complete": True,
        },
    )


def _report(
    run: Phase4PropagationRun,
    successor_count: int,
) -> Phase4PropagationReport:
    counts = {
        kind: sum(kind in item.change_kinds for item in run.impacts)
        for kind in Phase4ChangeKind
    }
    return _seal(
        Phase4PropagationReport,
        {
            "report_id": typed_id(
                "phase4propagationreport",
                run.propagation_run_id,
                run.integrity_sha256,
            ),
            "propagation_run_id": run.propagation_run_id,
            "created_at": run.created_at,
            "predecessor_utterance_count": len(
                set(run.changed_predecessor_utterance_ids).union(
                    run.unaffected_predecessor_utterance_ids
                )
            ),
            "successor_utterance_count": successor_count,
            "changed_utterance_count": len(
                run.changed_predecessor_utterance_ids
            ),
            "unaffected_utterance_count": len(
                run.unaffected_predecessor_utterance_ids
            ),
            "added_utterance_count": sum(
                item.disposition == UtteranceMappingDisposition.ADDED
                for item in run.impacts
            ),
            "removed_utterance_count": sum(
                item.disposition == UtteranceMappingDisposition.REMOVED
                for item in run.impacts
            ),
            "segmentation_review_count": sum(
                item.segmentation_review_required for item in run.impacts
            ),
            "change_kind_counts": tuple(
                f"{kind.value}={counts[kind]}" for kind in Phase4ChangeKind
            ),
            "status": (
                "warning"
                if any(
                    item.segmentation_review_required for item in run.impacts
                )
                else "complete"
            ),
            "limitations": (
                "Corpus-scoped successor identifiers cannot be represented as "
                "unchanged when upstream lineage changes.",
                "Predecessor artifacts remain immutable and addressable.",
                "Mapping uses canonical word ownership before bounded temporal "
                "fallback.",
            ),
        },
    )


def validate_phase4_propagation(
    run: Phase4PropagationRun,
    predecessor: Phase4ArtifactSet,
    successor: Phase4ArtifactSet,
    *,
    report: Phase4PropagationReport | None = None,
) -> None:
    _validate_set(predecessor)
    _validate_set(successor)
    _verify_seal(run, "Phase 4 propagation run")
    for impact in run.impacts:
        _verify_seal(impact, impact.impact_id)
    expected = build_phase4_propagation(
        predecessor,
        successor,
        policy=run.policy,
        created_at=run.created_at,
    )
    if expected != run:
        raise Phase4PropagationIntegrityError(
            "propagation is not the deterministic source comparison"
        )
    if report is not None:
        _verify_seal(report, "Phase 4 propagation report")
        expected_report = _report(run, len(successor.corpus.utterances))
        if report != expected_report:
            raise Phase4PropagationIntegrityError(
                "Phase 4 propagation report is invalid"
            )


def propagation_report_markdown(report: Phase4PropagationReport) -> str:
    return "\n".join(
        (
            "# Phase 4 correction-propagation report",
            "",
            f"- Run: `{report.propagation_run_id}`",
            f"- Predecessor utterances: {report.predecessor_utterance_count}",
            f"- Successor utterances: {report.successor_utterance_count}",
            f"- Changed predecessors: {report.changed_utterance_count}",
            f"- Unaffected predecessors: {report.unaffected_utterance_count}",
            f"- Added successors: {report.added_utterance_count}",
            f"- Removed predecessors: {report.removed_utterance_count}",
            f"- Segmentation review: {report.segmentation_review_count}",
            f"- Status: {report.status}",
            "",
        )
    )


def persist_phase4_propagation(
    run: Phase4PropagationRun,
    predecessor: Phase4ArtifactSet,
    successor: Phase4ArtifactSet,
    destination: Path,
) -> tuple[Phase4PropagationRun, Phase4PropagationReport, Path, bool]:
    destination = destination.expanduser().resolve()
    validate_phase4_propagation(run, predecessor, successor)
    report = _report(run, len(successor.corpus.utterances))
    root = destination / "phase4-propagation" / run.propagation_run_id
    paths = (root / "run.json", root / "report.json", root / "report.md")
    existing = tuple(path.exists() for path in paths)
    if any(existing) and not all(existing):
        raise Phase4PropagationIntegrityError(
            "cached propagation artifact is incomplete"
        )
    if all(existing):
        stored, stored_report = load_phase4_propagation(root)
        validate_phase4_propagation(
            stored, predecessor, successor, report=stored_report
        )
        if (
            stored != run
            or stored_report != report
            or paths[2].read_text(encoding="utf-8")
            != propagation_report_markdown(report)
        ):
            raise Phase4PropagationIntegrityError(
                "cached propagation artifact is incompatible"
            )
        return stored, stored_report, root, True
    _atomic(paths[0], canonical_bytes(run))
    _atomic(paths[1], canonical_bytes(report))
    _atomic(paths[2], propagation_report_markdown(report).encode("utf-8"))
    return run, report, root, False


def load_phase4_propagation(
    root: Path,
) -> tuple[Phase4PropagationRun, Phase4PropagationReport]:
    root = root.expanduser().resolve(strict=True)
    return (
        load_contract(
            (root / "run.json").read_bytes(), Phase4PropagationRun
        ),
        load_contract(
            (root / "report.json").read_bytes(), Phase4PropagationReport
        ),
    )
