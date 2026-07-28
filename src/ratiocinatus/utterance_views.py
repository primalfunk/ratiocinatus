"""Deterministic canonical speaker-attributed transcript views."""

from __future__ import annotations

import os
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase4_contracts import (
    Utterance,
    UtteranceAnalysisRun,
    UtteranceAttributionStatus,
    UtteranceCompletenessClassification,
    UtteranceCorpus,
    UtteranceReviewStatus,
    UtteranceRun,
    UtteranceTextKind,
)
from .quotation_contracts import QuotationEvidenceRun
from .turn_repair_contracts import TurnRepairRun
from .utterance_relation_contracts import (
    InterruptionKind,
    UtteranceRelationRun,
    UtteranceTemporalRelation,
)
from .utterance_view_contracts import (
    RenderedUtterance,
    SpeakerAttributedTranscriptBundle,
    SpeakerAttributedTranscriptPolicy,
    SpeakerAttributedTranscriptReport,
    SpeakerAttributedTranscriptView,
    SpeakerAttributedViewKind,
    UtterancePresentationLoss,
    UtterancePresentationLossKind,
    UtterancePresentationMarker,
)


class UtteranceViewIntegrityError(RuntimeError):
    """Speaker-attributed transcript views are corrupt or incompatible."""


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
        raise UtteranceViewIntegrityError(f"{label} integrity is invalid")


def _bounds(utterance: Utterance) -> tuple[int, int]:
    starts = [
        item.start_microseconds for item in utterance.normalized_audio_intervals
    ]
    ends = [
        item.start_microseconds + item.duration_microseconds
        for item in utterance.normalized_audio_intervals
    ]
    return min(starts), max(ends)


def _ordered(corpus: UtteranceCorpus) -> tuple[Utterance, ...]:
    return tuple(
        sorted(
            corpus.utterances,
            key=lambda item: (_bounds(item)[0], item.utterance_id),
        )
    )


def _timestamp(microseconds: int) -> str:
    sign = "-" if microseconds < 0 else ""
    value = abs(microseconds)
    hours, remainder = divmod(value, 3_600_000_000)
    minutes, remainder = divmod(remainder, 60_000_000)
    seconds, micros = divmod(remainder, 1_000_000)
    return (
        f"{sign}{hours:02d}:{minutes:02d}:{seconds:02d}."
        f"{micros // 1_000:03d}"
    )


def _display_text(utterance: Utterance) -> str:
    return next(
        item.text
        for item in utterance.text_views
        if item.kind == UtteranceTextKind.DISPLAY
    )


def _corrected_text(utterance: Utterance) -> str | None:
    return next(
        (
            item.text
            for item in utterance.text_views
            if item.kind == UtteranceTextKind.CURRENT_CORRECTED_TRANSCRIPT
        ),
        None,
    )


def _temporal_groups(
    corpus: UtteranceCorpus,
    relations: UtteranceRelationRun,
) -> tuple[dict[str, str], dict[str, tuple[str, ...]], dict[str, int]]:
    utterance_ids = {item.utterance_id for item in corpus.utterances}
    parent = {item: item for item in utterance_ids}

    def find(item: str) -> str:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    for overlap in relations.overlaps:
        values = overlap.affected_utterance_ids
        for left, right in zip(values, values[1:]):
            union(left, right)
    for adjacency in relations.adjacencies:
        if adjacency.temporal_relation in {
            UtteranceTemporalRelation.OVERLAPPING,
            UtteranceTemporalRelation.SIMULTANEOUS_START,
        }:
            union(
                adjacency.preceding_utterance_id,
                adjacency.following_utterance_id,
            )
    members: dict[str, list[str]] = defaultdict(list)
    for utterance_id in utterance_ids:
        members[find(utterance_id)].append(utterance_id)
    group_ids: dict[str, str] = {}
    simultaneous: dict[str, tuple[str, ...]] = {}
    lanes: dict[str, int] = {}
    by_id = {item.utterance_id: item for item in corpus.utterances}
    for values in members.values():
        ordered = sorted(
            values, key=lambda item: (_bounds(by_id[item])[0], item)
        )
        group_id = typed_id(
            "temporalgroup", corpus.corpus_id, tuple(ordered)
        )
        for lane, utterance_id in enumerate(ordered):
            group_ids[utterance_id] = group_id
            simultaneous[utterance_id] = tuple(
                item for item in ordered if item != utterance_id
            )
            lanes[utterance_id] = lane
    return group_ids, simultaneous, lanes


def _marker_maps(
    corpus: UtteranceCorpus,
    analysis: UtteranceAnalysisRun,
    relations: UtteranceRelationRun,
    repair: TurnRepairRun,
    quotation: QuotationEvidenceRun,
) -> tuple[
    dict[str, set[UtterancePresentationMarker]],
    dict[str, list[str]],
]:
    markers: dict[str, set[UtterancePresentationMarker]] = defaultdict(set)
    details: dict[str, list[str]] = defaultdict(list)
    assessments = {
        item.utterance_id: item for item in analysis.completeness_assessments
    }
    for utterance in corpus.utterances:
        assessment = assessments[utterance.utterance_id]
        if assessment.classification != UtteranceCompletenessClassification.COMPLETE:
            markers[utterance.utterance_id].add(
                UtterancePresentationMarker.INCOMPLETE
            )
            details[utterance.utterance_id].append(
                f"completeness={assessment.classification.value}"
            )
        if utterance.attribution.status == UtteranceAttributionStatus.UNKNOWN:
            markers[utterance.utterance_id].add(
                UtterancePresentationMarker.UNKNOWN_SPEAKER
            )
        if utterance.attribution.status == UtteranceAttributionStatus.CONFLICTING:
            markers[utterance.utterance_id].add(
                UtterancePresentationMarker.CONFLICTING_SPEAKER
            )
        if utterance.review_status == UtteranceReviewStatus.REVIEW_REQUIRED:
            markers[utterance.utterance_id].add(
                UtterancePresentationMarker.REVIEW_REQUIRED
            )
    for item in relations.interruptions:
        markers[item.interrupted_utterance_id].add(
            UtterancePresentationMarker.INTERRUPTED
        )
        details[item.interrupted_utterance_id].append(
            f"interruption={item.interruption_id}"
        )
        if item.interrupting_utterance_id is not None:
            markers[item.interrupting_utterance_id].add(
                UtterancePresentationMarker.INTERRUPTING
            )
        if item.original_utterance_resumes:
            markers[item.interrupted_utterance_id].add(
                UtterancePresentationMarker.RESUMES
            )
    for item in relations.continuations:
        for utterance_id in (
            item.predecessor_utterance_id,
            item.successor_utterance_id,
        ):
            markers[utterance_id].add(
                UtterancePresentationMarker.CONTINUATION
            )
            details[utterance_id].append(
                f"continuation={item.continuation_id}"
            )
    for item in relations.overlaps:
        for utterance_id in item.affected_utterance_ids:
            markers[utterance_id].add(UtterancePresentationMarker.OVERLAP)
            details[utterance_id].append(
                f"overlap={item.overlap_relation_id}"
            )
    decided = {item.proposal_id: item for item in repair.decisions}
    for item in repair.proposals:
        for utterance_id in item.proposed_change.source_utterance_ids:
            marker = (
                UtterancePresentationMarker.REPAIR_ACCEPTED
                if item.proposal_id in decided
                and decided[item.proposal_id].disposition.value == "accepted"
                else UtterancePresentationMarker.REPAIR_PROPOSED
            )
            markers[utterance_id].add(marker)
            details[utterance_id].append(f"repair={item.proposal_id}")
    for item in quotation.quotations:
        markers[item.quoting_utterance_id].add(
            UtterancePresentationMarker.QUOTATION
        )
        details[item.quoting_utterance_id].append(
            f"quotation={item.quotation_id}:{item.quotation_type.value}"
        )
    for item in quotation.embedded_sources:
        markers[item.utterance_id].add(
            UtterancePresentationMarker.EMBEDDED_SOURCE
        )
        details[item.utterance_id].append(
            f"source={item.embedded_source_id}:{item.source_type.value}"
        )
    return markers, details


def _loss(
    bundle_id: str,
    kind: UtterancePresentationLossKind,
    utterance_ids: tuple[str, ...],
    explanation: str,
) -> UtterancePresentationLoss:
    payload = {
        "loss_id": typed_id(
            "utteranceviewloss", bundle_id, kind.value, utterance_ids
        ),
        "kind": kind,
        "affected_utterance_ids": utterance_ids,
        "explanation": explanation,
        "underlying_evidence_preserved": True,
    }
    return _seal(UtterancePresentationLoss, payload)


def _label(
    utterance: Utterance,
    kind: SpeakerAttributedViewKind,
    policy: SpeakerAttributedTranscriptPolicy,
) -> tuple[str, UtterancePresentationLossKind | None]:
    status = utterance.attribution.status
    if kind == SpeakerAttributedViewKind.MACHINE_CLUSTER:
        if status == UtteranceAttributionStatus.MACHINE_CLUSTERED:
            return utterance.attribution.display_label, None
        return policy.unknown_label, (
            UtterancePresentationLossKind.MACHINE_CLUSTER_LABEL_UNAVAILABLE
        )
    if kind == SpeakerAttributedViewKind.REVIEWED_IDENTITY:
        if status in {
            UtteranceAttributionStatus.MANUALLY_BOUND,
            UtteranceAttributionStatus.ROLE_LABELED,
        }:
            return utterance.attribution.display_label, None
        return policy.unknown_label, (
            UtterancePresentationLossKind.REVIEWED_IDENTITY_LABEL_UNAVAILABLE
        )
    if status == UtteranceAttributionStatus.CONFLICTING:
        return policy.conflict_label, None
    if status == UtteranceAttributionStatus.UNKNOWN:
        return policy.unknown_label, None
    return utterance.attribution.display_label, None


def _view(
    bundle_id: str,
    corpus: UtteranceCorpus,
    kind: SpeakerAttributedViewKind,
    policy: SpeakerAttributedTranscriptPolicy,
    markers: dict[str, set[UtterancePresentationMarker]],
    details: dict[str, list[str]],
    group_ids: dict[str, str],
    simultaneous: dict[str, tuple[str, ...]],
    lanes: dict[str, int],
    generated_at: datetime,
) -> SpeakerAttributedTranscriptView:
    rendered: list[RenderedUtterance] = []
    losses: list[UtterancePresentationLoss] = []
    for position, utterance in enumerate(_ordered(corpus)):
        label, label_loss = _label(utterance, kind, policy)
        if label_loss is not None:
            losses.append(
                _loss(
                    bundle_id,
                    label_loss,
                    (utterance.utterance_id,),
                    f"{kind.value} cannot represent the available attribution.",
                )
            )
        text = _display_text(utterance)
        if kind == SpeakerAttributedViewKind.CORRECTION_AWARE:
            corrected = _corrected_text(utterance)
            if corrected is None:
                losses.append(
                    _loss(
                        bundle_id,
                        UtterancePresentationLossKind.CORRECTED_TEXT_UNAVAILABLE,
                        (utterance.utterance_id,),
                        "No corrected text view exists; display text is retained.",
                    )
                )
            else:
                text = corrected
        values = tuple(sorted(markers[utterance.utterance_id], key=lambda x: x.value))
        marker_text = " ".join(f"<{item.value}>" for item in values)
        source_start = min(
            item.start_microseconds for item in utterance.source_intervals
        )
        timestamp = _timestamp(source_start)
        identifier = (
            ""
            if kind == SpeakerAttributedViewKind.COMPACT_READING
            else f"[{utterance.utterance_id}] "
        )
        lane_text = (
            f"[lane={lanes[utterance.utterance_id]}] "
            if kind == SpeakerAttributedViewKind.OVERLAP_EXPANDED
            else ""
        )
        line = (
            f"{timestamp} {lane_text}{identifier}{label}: "
            f"{marker_text} {text}"
        ).rstrip()
        evidence = (
            utterance.utterance_id,
            utterance.attribution.attribution_id,
            *details[utterance.utterance_id],
        )
        rendered.append(
            _seal(
                RenderedUtterance,
                {
                    "rendered_utterance_id": typed_id(
                        "renderedutterance",
                        bundle_id,
                        kind.value,
                        utterance.utterance_id,
                    ),
                    "utterance_id": utterance.utterance_id,
                    "sequence_position": position,
                    "temporal_group_id": group_ids[utterance.utterance_id],
                    "temporal_lane": lanes[utterance.utterance_id],
                    "simultaneous_with_utterance_ids": simultaneous[
                        utterance.utterance_id
                    ],
                    "source_intervals": utterance.source_intervals,
                    "normalized_audio_intervals": (
                        utterance.normalized_audio_intervals
                    ),
                    "source_timestamp_text": timestamp,
                    "speaker_label": label,
                    "attribution_status": utterance.attribution.status,
                    "text": text,
                    "markers": values,
                    "marker_details": tuple(details[utterance.utterance_id]),
                    "rendered_line": line,
                    "review_status": utterance.review_status,
                    "evidence_references": evidence,
                },
            )
        )
        if (
            len(utterance.source_intervals) > 1
            and kind != SpeakerAttributedViewKind.OVERLAP_EXPANDED
        ):
            losses.append(
                _loss(
                    bundle_id,
                    UtterancePresentationLossKind.NONCONTIGUOUS_INTERVALS_LINEARIZED,
                    (utterance.utterance_id,),
                    "Multiple source intervals are shown on one presentation line.",
                )
            )
    overlap_groups = {
        value
        for utterance_id, value in group_ids.items()
        if simultaneous[utterance_id]
    }
    if kind != SpeakerAttributedViewKind.OVERLAP_EXPANDED:
        for group_id in sorted(overlap_groups):
            affected = tuple(
                sorted(
                    item
                    for item, item_group in group_ids.items()
                    if item_group == group_id
                )
            )
            losses.append(
                _loss(
                    bundle_id,
                    UtterancePresentationLossKind.OVERLAP_LINEARIZED,
                    affected,
                    "Stable line order does not replace the simultaneous timeline.",
                )
            )
    payload = {
        "view_id": typed_id(
            "utteranceview",
            bundle_id,
            kind.value,
            tuple(item.integrity_sha256 for item in rendered),
        ),
        "bundle_id": bundle_id,
        "utterance_corpus_id": corpus.corpus_id,
        "kind": kind,
        "policy": policy,
        "rendered_utterances": tuple(rendered),
        "losses": tuple(losses),
        "rendered_text": "\n".join(item.rendered_line for item in rendered),
        "preserves_overlap_partial_order": (
            kind == SpeakerAttributedViewKind.OVERLAP_EXPANDED
        ),
        "order_basis": (
            "temporal groups with explicit lanes"
            if kind == SpeakerAttributedViewKind.OVERLAP_EXPANDED
            else "start time then stable identifier; simultaneity disclosed"
        ),
        "generated_at": generated_at,
    }
    return _seal(SpeakerAttributedTranscriptView, payload)


def _lineage(
    utterance_run: UtteranceRun,
    corpus: UtteranceCorpus,
    analysis: UtteranceAnalysisRun,
    relations: UtteranceRelationRun,
    repair: TurnRepairRun,
    quotation: QuotationEvidenceRun,
) -> None:
    for item, label in (
        (utterance_run, "utterance run"),
        (corpus, "utterance corpus"),
        (analysis, "utterance analysis"),
        (relations, "utterance relations"),
        (repair, "turn-repair run"),
        (quotation, "quotation run"),
    ):
        _verify_seal(item, label)
    if (
        corpus.run_id != utterance_run.run_id
        or corpus.corpus_id != utterance_run.utterance_corpus_id
        or analysis.utterance_corpus_id != corpus.corpus_id
        or analysis.utterance_run_id != utterance_run.run_id
        or relations.utterance_corpus_id != corpus.corpus_id
        or relations.utterance_run_id != utterance_run.run_id
        or relations.utterance_analysis_id != analysis.analysis_id
        or repair.utterance_corpus_id != corpus.corpus_id
        or repair.utterance_run_id != utterance_run.run_id
        or quotation.utterance_corpus_id != corpus.corpus_id
        or quotation.utterance_run_id != utterance_run.run_id
    ):
        raise UtteranceViewIntegrityError(
            "speaker-attributed view lineage is incompatible"
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
    for values, id_name in (
        (analysis.completeness_assessments, "assessment_id"),
        (relations.adjacencies, "adjacency_id"),
        (relations.overlaps, "overlap_relation_id"),
        (relations.interruptions, "interruption_id"),
        (relations.continuations, "continuation_id"),
        (repair.conflicts, "conflict_id"),
        (repair.proposals, "proposal_id"),
        (repair.decisions, "decision_id"),
        (repair.successors, "successor_id"),
        (quotation.quotations, "quotation_id"),
        (quotation.embedded_sources, "embedded_source_id"),
    ):
        for item in values:
            _verify_seal(item, getattr(item, id_name))
            if id_name == "quotation_id":
                _verify_seal(item.quoted_span, item.quoted_span.span_id)


def build_speaker_attributed_views(
    utterance_run: UtteranceRun,
    corpus: UtteranceCorpus,
    analysis: UtteranceAnalysisRun,
    relations: UtteranceRelationRun,
    repair: TurnRepairRun,
    quotation: QuotationEvidenceRun,
    *,
    policy: SpeakerAttributedTranscriptPolicy | None = None,
    generated_at: datetime | None = None,
) -> SpeakerAttributedTranscriptBundle:
    """Build all canonical presentation views without replacing evidence."""
    _lineage(utterance_run, corpus, analysis, relations, repair, quotation)
    policy = policy or SpeakerAttributedTranscriptPolicy()
    timestamp = generated_at or quotation.created_at
    configuration_hash = canonical_hash(
        {
            "utterance_run": utterance_run.integrity_sha256,
            "corpus": corpus.integrity_sha256,
            "analysis": analysis.integrity_sha256,
            "relations": relations.integrity_sha256,
            "repair": repair.integrity_sha256,
            "quotation": quotation.integrity_sha256,
            "policy": policy.model_dump(mode="json"),
        }
    )
    bundle_id = typed_id(
        "utteranceviewbundle", corpus.corpus_id, configuration_hash
    )
    group_ids, simultaneous, lanes = _temporal_groups(corpus, relations)
    markers, details = _marker_maps(
        corpus, analysis, relations, repair, quotation
    )
    views = tuple(
        _view(
            bundle_id,
            corpus,
            kind,
            policy,
            markers,
            details,
            group_ids,
            simultaneous,
            lanes,
            timestamp,
        )
        for kind in SpeakerAttributedViewKind
    )
    return _seal(
        SpeakerAttributedTranscriptBundle,
        {
            "bundle_id": bundle_id,
            "utterance_corpus_id": corpus.corpus_id,
            "utterance_run_id": utterance_run.run_id,
            "utterance_analysis_id": analysis.analysis_id,
            "utterance_relation_run_id": relations.relation_run_id,
            "turn_repair_run_id": repair.repair_run_id,
            "quotation_run_id": quotation.quotation_run_id,
            "configuration_hash": configuration_hash,
            "views": views,
            "generated_at": timestamp,
        },
    )


def _report(
    bundle: SpeakerAttributedTranscriptBundle,
) -> SpeakerAttributedTranscriptReport:
    expanded = next(
        item
        for item in bundle.views
        if item.kind == SpeakerAttributedViewKind.OVERLAP_EXPANDED
    )
    records = expanded.rendered_utterances
    overlap_groups = {
        item.temporal_group_id for item in records if item.simultaneous_with_utterance_ids
    }
    marker_count = lambda marker: sum(
        marker in item.markers for item in records
    )
    return _seal(
        SpeakerAttributedTranscriptReport,
        {
            "report_id": typed_id(
                "utteranceviewreport",
                bundle.bundle_id,
                bundle.integrity_sha256,
            ),
            "bundle_id": bundle.bundle_id,
            "utterance_corpus_id": bundle.utterance_corpus_id,
            "generated_at": bundle.generated_at,
            "view_count": len(bundle.views),
            "utterance_count_per_view": len(records),
            "overlap_group_count": len(overlap_groups),
            "marked_interruption_count": marker_count(
                UtterancePresentationMarker.INTERRUPTED
            ),
            "marked_continuation_count": marker_count(
                UtterancePresentationMarker.CONTINUATION
            ),
            "marked_quotation_count": marker_count(
                UtterancePresentationMarker.QUOTATION
            ),
            "marked_embedded_source_count": marker_count(
                UtterancePresentationMarker.EMBEDDED_SOURCE
            ),
            "unknown_preserved_count": marker_count(
                UtterancePresentationMarker.UNKNOWN_SPEAKER
            ),
            "loss_record_count": sum(len(item.losses) for item in bundle.views),
            "limitations": (
                "Presentation views do not replace the utterance corpus.",
                "Sequential views explicitly disclose overlap linearization.",
                "Unavailable reviewed or corrected data degrades to visible losses.",
            ),
            "status": "warning"
            if any(item.losses for item in bundle.views)
            else "complete",
        },
    )


def validate_speaker_attributed_views(
    bundle: SpeakerAttributedTranscriptBundle,
    utterance_run: UtteranceRun,
    corpus: UtteranceCorpus,
    analysis: UtteranceAnalysisRun,
    relations: UtteranceRelationRun,
    repair: TurnRepairRun,
    quotation: QuotationEvidenceRun,
    *,
    report: SpeakerAttributedTranscriptReport | None = None,
) -> None:
    _lineage(utterance_run, corpus, analysis, relations, repair, quotation)
    _verify_seal(bundle, "speaker-attributed transcript bundle")
    for view in bundle.views:
        _verify_seal(view, view.view_id)
        for item in view.rendered_utterances:
            _verify_seal(item, item.rendered_utterance_id)
        for loss in view.losses:
            _verify_seal(loss, loss.loss_id)
    if (
        bundle.utterance_corpus_id != corpus.corpus_id
        or bundle.utterance_run_id != utterance_run.run_id
        or bundle.utterance_analysis_id != analysis.analysis_id
        or bundle.utterance_relation_run_id != relations.relation_run_id
        or bundle.turn_repair_run_id != repair.repair_run_id
        or bundle.quotation_run_id != quotation.quotation_run_id
    ):
        raise UtteranceViewIntegrityError(
            "transcript bundle and source lineage disagree"
        )
    expected = build_speaker_attributed_views(
        utterance_run,
        corpus,
        analysis,
        relations,
        repair,
        quotation,
        policy=bundle.views[0].policy,
        generated_at=bundle.generated_at,
    )
    if expected != bundle:
        raise UtteranceViewIntegrityError(
            "transcript views are not the deterministic source projection"
        )
    if report is not None:
        _verify_seal(report, "speaker-attributed transcript report")
        if report != _report(bundle):
            raise UtteranceViewIntegrityError(
                "speaker-attributed transcript report is invalid"
            )


def speaker_attributed_report_markdown(
    report: SpeakerAttributedTranscriptReport,
) -> str:
    return "\n".join(
        (
            "# Phase 4 speaker-attributed transcript report",
            "",
            f"- Bundle: `{report.bundle_id}`",
            f"- Views: {report.view_count}",
            f"- Utterances per view: {report.utterance_count_per_view}",
            f"- Overlap groups: {report.overlap_group_count}",
            f"- Interruption markers: {report.marked_interruption_count}",
            f"- Continuation markers: {report.marked_continuation_count}",
            f"- Quotation markers: {report.marked_quotation_count}",
            f"- Embedded-source markers: {report.marked_embedded_source_count}",
            f"- Unknown speakers preserved: {report.unknown_preserved_count}",
            f"- Declared presentation losses: {report.loss_record_count}",
            f"- Status: {report.status}",
            "",
        )
    )


def persist_speaker_attributed_views(
    bundle: SpeakerAttributedTranscriptBundle,
    utterance_run: UtteranceRun,
    corpus: UtteranceCorpus,
    analysis: UtteranceAnalysisRun,
    relations: UtteranceRelationRun,
    repair: TurnRepairRun,
    quotation: QuotationEvidenceRun,
    destination: Path,
) -> tuple[
    SpeakerAttributedTranscriptBundle,
    SpeakerAttributedTranscriptReport,
    Path,
    bool,
]:
    destination = destination.expanduser().resolve()
    validate_speaker_attributed_views(
        bundle,
        utterance_run,
        corpus,
        analysis,
        relations,
        repair,
        quotation,
    )
    report = _report(bundle)
    root = destination / "utterance-views" / bundle.bundle_id
    paths = (
        root / "bundle.json",
        root / "report.json",
        root / "report.md",
    )
    view_paths = tuple(
        root / f"{item.kind.value}.txt" for item in bundle.views
    )
    all_paths = paths + view_paths
    existing = tuple(path.exists() for path in all_paths)
    if any(existing) and not all(existing):
        raise UtteranceViewIntegrityError(
            "cached transcript view bundle is incomplete"
        )
    if all(existing):
        stored = load_contract(
            paths[0].read_bytes(), SpeakerAttributedTranscriptBundle
        )
        stored_report = load_contract(
            paths[1].read_bytes(), SpeakerAttributedTranscriptReport
        )
        validate_speaker_attributed_views(
            stored,
            utterance_run,
            corpus,
            analysis,
            relations,
            repair,
            quotation,
            report=stored_report,
        )
        if (
            stored != bundle
            or stored_report != report
            or paths[2].read_text(encoding="utf-8")
            != speaker_attributed_report_markdown(report)
            or any(
                path.read_text(encoding="utf-8") != view.rendered_text
                for path, view in zip(view_paths, bundle.views)
            )
        ):
            raise UtteranceViewIntegrityError(
                "cached transcript view bundle is incompatible"
            )
        return stored, stored_report, root, True
    _atomic(paths[0], canonical_bytes(bundle))
    _atomic(paths[1], canonical_bytes(report))
    _atomic(
        paths[2], speaker_attributed_report_markdown(report).encode("utf-8")
    )
    for path, view in zip(view_paths, bundle.views):
        _atomic(path, view.rendered_text.encode("utf-8"))
    return bundle, report, root, False


def load_speaker_attributed_views(
    root: Path,
) -> tuple[
    SpeakerAttributedTranscriptBundle,
    SpeakerAttributedTranscriptReport,
]:
    root = root.expanduser().resolve(strict=True)
    return (
        load_contract(
            (root / "bundle.json").read_bytes(),
            SpeakerAttributedTranscriptBundle,
        ),
        load_contract(
            (root / "report.json").read_bytes(),
            SpeakerAttributedTranscriptReport,
        ),
    )
