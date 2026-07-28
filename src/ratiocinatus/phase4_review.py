"""Append-only Phase 4 utterance review ledgers and evidence queues."""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path

from .context_window_contracts import ContextWindowBundle, ContextWindowKind
from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase4_contracts import (
    Utterance,
    UtteranceAttributionStatus,
    UtteranceCompletenessClassification,
    UtteranceCorpus,
    UtteranceReviewStatus,
)
from .phase4_propagation import (
    Phase4ArtifactSet,
    validate_phase4_artifact_set,
)
from .phase4_review_contracts import (
    Phase4PropagationRun,
    ReviewActionDisposition,
    ReviewActionKind,
    ReviewQueueItem,
    ReviewQueueKind,
    ReviewQueueReport,
    ReviewerCertainty,
    ReviewStateEntry,
    UtteranceReviewAction,
    UtteranceReviewLedger,
)
from .utterance_view_contracts import SpeakerAttributedTranscriptBundle


class Phase4ReviewIntegrityError(RuntimeError):
    """Review evidence is corrupt or incompatible."""


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
        raise Phase4ReviewIntegrityError(f"{label} integrity is invalid")


def _initial_view_version(
    corpus: UtteranceCorpus,
    views: SpeakerAttributedTranscriptBundle,
) -> str:
    return typed_id(
        "utterancereviewview",
        corpus.corpus_id,
        views.bundle_id,
        "machine-proposal",
    )


def create_review_ledger(
    corpus: UtteranceCorpus,
    views: SpeakerAttributedTranscriptBundle,
    *,
    created_at: datetime | None = None,
) -> UtteranceReviewLedger:
    """Create the immutable version-zero review ledger."""
    if views.utterance_corpus_id != corpus.corpus_id:
        raise Phase4ReviewIntegrityError(
            "review ledger sources use different utterance corpora"
        )
    timestamp = created_at or views.generated_at
    current = _initial_view_version(corpus, views)
    return _seal(
        UtteranceReviewLedger,
        {
            "review_ledger_id": typed_id(
                "reviewledger", corpus.corpus_id, views.bundle_id, 0
            ),
            "predecessor_review_ledger_id": None,
            "utterance_corpus_id": corpus.corpus_id,
            "transcript_view_bundle_id": views.bundle_id,
            "ledger_version": 0,
            "actions": (),
            "current_utterance_view_version": current,
            "created_at": timestamp,
        },
    )


def append_review_action(
    ledger: UtteranceReviewLedger,
    corpus: UtteranceCorpus,
    views: SpeakerAttributedTranscriptBundle,
    action: ReviewActionKind,
    target_utterance_ids: tuple[str, ...],
    *,
    target_artifact_ids: tuple[str, ...],
    prior_state: dict[str, str],
    proposed_state: dict[str, str],
    author: str,
    reviewed_at: datetime,
    rationale: str,
    evidence_references: tuple[str, ...],
    reviewer_certainty: ReviewerCertainty,
) -> UtteranceReviewLedger:
    """Append one review action without modifying machine evidence."""
    validate_review_ledger(ledger, corpus, views)
    known = {item.utterance_id for item in corpus.utterances}
    if not set(target_utterance_ids).issubset(known):
        raise Phase4ReviewIntegrityError(
            "manual review references an unknown utterance"
        )
    disposition = (
        ReviewActionDisposition.DEFERRED
        if action == ReviewActionKind.DEFER_DECISION
        else ReviewActionDisposition.APPLIED
    )
    predecessor_action_id = (
        ledger.actions[-1].review_action_id if ledger.actions else None
    )
    sequence = ledger.ledger_version + 1
    action_id = typed_id(
        "utterancereview",
        ledger.review_ledger_id,
        sequence,
        action.value,
        target_utterance_ids,
        author,
        reviewed_at.isoformat(),
    )
    resulting_view = typed_id(
        "utterancereviewview",
        ledger.current_utterance_view_version,
        action_id,
    )
    review = _seal(
        UtteranceReviewAction,
        {
            "review_action_id": action_id,
            "predecessor_review_action_id": predecessor_action_id,
            "action": action,
            "disposition": disposition,
            "target_artifact_ids": target_artifact_ids,
            "target_utterance_ids": target_utterance_ids,
            "prior_state": tuple(
                ReviewStateEntry(key=key, value=value)
                for key, value in sorted(prior_state.items())
            ),
            "proposed_state": tuple(
                ReviewStateEntry(key=key, value=value)
                for key, value in sorted(proposed_state.items())
            ),
            "author": author,
            "reviewed_at": reviewed_at,
            "rationale": rationale,
            "evidence_references": evidence_references,
            "reviewer_certainty": reviewer_certainty,
            "resulting_utterance_view_version": resulting_view,
        },
    )
    actions = (*ledger.actions, review)
    return _seal(
        UtteranceReviewLedger,
        {
            "review_ledger_id": typed_id(
                "reviewledger",
                corpus.corpus_id,
                views.bundle_id,
                sequence,
                action_id,
            ),
            "predecessor_review_ledger_id": ledger.review_ledger_id,
            "utterance_corpus_id": corpus.corpus_id,
            "transcript_view_bundle_id": views.bundle_id,
            "ledger_version": sequence,
            "actions": actions,
            "current_utterance_view_version": resulting_view,
            "created_at": reviewed_at,
        },
    )


def validate_review_ledger(
    ledger: UtteranceReviewLedger,
    corpus: UtteranceCorpus,
    views: SpeakerAttributedTranscriptBundle,
) -> None:
    _verify_seal(corpus, "utterance corpus")
    _verify_seal(views, "speaker-attributed transcript bundle")
    _verify_seal(ledger, "utterance review ledger")
    for action in ledger.actions:
        _verify_seal(action, action.review_action_id)
    if (
        ledger.utterance_corpus_id != corpus.corpus_id
        or ledger.transcript_view_bundle_id != views.bundle_id
        or views.utterance_corpus_id != corpus.corpus_id
    ):
        raise Phase4ReviewIntegrityError(
            "review ledger lineage is incompatible"
        )
    known = {item.utterance_id for item in corpus.utterances}
    if any(
        not set(action.target_utterance_ids).issubset(known)
        for action in ledger.actions
    ):
        raise Phase4ReviewIntegrityError(
            "review ledger references an unknown utterance"
        )


def _duration(utterance: Utterance) -> int:
    return sum(item.duration_microseconds for item in utterance.source_intervals)


def _queue_item(
    kind: ReviewQueueKind,
    utterances: tuple[Utterance, ...],
    contexts: ContextWindowBundle,
    evidence: tuple[str, ...],
    proposed: tuple[ReviewActionKind, ...],
    alternatives: tuple[str, ...],
) -> ReviewQueueItem:
    utterance_ids = tuple(item.utterance_id for item in utterances)
    intervals = tuple(
        sorted(
            (
                interval
                for utterance in utterances
                for interval in utterance.source_intervals
            ),
            key=lambda item: (item.start_microseconds, item.duration_microseconds),
        )
    )
    start = min(item.start_microseconds for item in intervals)
    end = max(
        item.start_microseconds + item.duration_microseconds
        for item in intervals
    )
    source_id = utterances[0].source_id
    context_ids = tuple(
        item.context_window_id
        for item in contexts.windows
        if item.target_utterance_id in utterance_ids
        and item.kind
        in {ContextWindowKind.EXCHANGE, ContextWindowKind.BOUNDED_TEMPORAL}
    )
    return _seal(
        ReviewQueueItem,
        {
            "review_queue_item_id": typed_id(
                "reviewqueue", kind.value, utterance_ids, evidence
            ),
            "kind": kind,
            "utterance_ids": utterance_ids,
            "source_intervals": intervals,
            "media_reference": source_id,
            "extraction_command": (
                "ratiocinatus media extract "
                f"--source {source_id} --start-microseconds {start} "
                f"--duration-microseconds {end - start}"
            ),
            "local_context_window_ids": context_ids,
            "speaker_evidence_references": tuple(
                sorted(
                    {
                        item.attribution.attribution_id
                        for item in utterances
                    }
                )
            ),
            "proposed_actions": proposed,
            "competing_alternatives": alternatives,
            "current_review_status": (
                UtteranceReviewStatus.REVIEW_REQUIRED
                if any(
                    item.review_status == UtteranceReviewStatus.REVIEW_REQUIRED
                    for item in utterances
                )
                else utterances[0].review_status
            ),
            "evidence_references": tuple(
                sorted({*evidence, *utterance_ids})
            ),
        },
    )


def build_review_queue(
    ledger: UtteranceReviewLedger,
    artifacts: Phase4ArtifactSet,
    *,
    propagation: Phase4PropagationRun | None = None,
    generated_at: datetime | None = None,
) -> ReviewQueueReport:
    """Build evidence-complete review queues without reconstructing lineage."""
    validate_review_ledger(
        ledger, artifacts.corpus, artifacts.transcript_views
    )
    validate_phase4_artifact_set(artifacts)
    by_id = {
        item.utterance_id: item for item in artifacts.corpus.utterances
    }
    items: list[ReviewQueueItem] = []

    def add(
        kind: ReviewQueueKind,
        utterance_ids: tuple[str, ...],
        evidence: tuple[str, ...],
        proposed: tuple[ReviewActionKind, ...],
        alternatives: tuple[str, ...],
    ) -> None:
        known_ids = tuple(item for item in utterance_ids if item in by_id)
        if not known_ids:
            return
        value = _queue_item(
            kind,
            tuple(by_id[item] for item in known_ids),
            artifacts.context_windows,
            evidence,
            proposed,
            alternatives,
        )
        if value not in items:
            items.append(value)

    for utterance in artifacts.corpus.utterances:
        utterance_id = utterance.utterance_id
        if (
            utterance.review_status == UtteranceReviewStatus.REVIEW_REQUIRED
            or utterance.completeness
            == UtteranceCompletenessClassification.UNKNOWN
        ):
            add(
                ReviewQueueKind.LOW_CONFIDENCE_SEGMENTATION,
                (utterance_id,),
                tuple(utterance.completeness_evidence_references),
                (
                    ReviewActionKind.APPROVE_UTTERANCE,
                    ReviewActionKind.SPLIT_UTTERANCE,
                    ReviewActionKind.DEFER_DECISION,
                ),
                ("retain machine segmentation", "split at reviewed boundary"),
            )
        if utterance.attribution.status == UtteranceAttributionStatus.UNKNOWN:
            add(
                ReviewQueueKind.UNCERTAIN_SPEAKER_BOUNDARY,
                (utterance_id,),
                (utterance.attribution.attribution_id,),
                (
                    ReviewActionKind.FLAG_UNCERTAIN_SPEAKER,
                    ReviewActionKind.MOVE_BOUNDARY,
                ),
                ("preserve unknown speaker", "review adjacent boundary"),
            )
        if utterance.attribution.status == UtteranceAttributionStatus.CONFLICTING:
            add(
                ReviewQueueKind.CONFLICTING_SPEAKER_ATTRIBUTION,
                (utterance_id,),
                (utterance.attribution.attribution_id,),
                (
                    ReviewActionKind.FLAG_UNCERTAIN_SPEAKER,
                    ReviewActionKind.DEFER_DECISION,
                ),
                ("preserve conflict", "select only with reviewed evidence"),
            )
        if _duration(utterance) > 30_000_000:
            add(
                ReviewQueueKind.LONG_UTTERANCE,
                (utterance_id,),
                (utterance_id,),
                (
                    ReviewActionKind.SPLIT_UTTERANCE,
                    ReviewActionKind.APPROVE_UTTERANCE,
                ),
                ("retain long utterance", "split at source-addressed boundary"),
            )
        if _duration(utterance) < 300_000:
            add(
                ReviewQueueKind.VERY_SHORT_FRAGMENT,
                (utterance_id,),
                (utterance_id,),
                (
                    ReviewActionKind.MERGE_UTTERANCES,
                    ReviewActionKind.APPROVE_UTTERANCE,
                ),
                ("retain fragment", "merge with compatible neighbor"),
            )
    for conflict in artifacts.repair.conflicts:
        kind = (
            ReviewQueueKind.WORD_CROSSING_SPEAKER_BOUNDARY
            if "word_crosses" in conflict.kind.value
            else ReviewQueueKind.LIKELY_TURN_REPAIR
        )
        add(
            kind,
            conflict.utterance_ids,
            (conflict.conflict_id,),
            (
                ReviewActionKind.MOVE_BOUNDARY,
                ReviewActionKind.SPLIT_UTTERANCE,
                ReviewActionKind.DEFER_DECISION,
            ),
            ("accept repair proposal", "preserve unresolved conflict"),
        )
    for interruption in artifacts.relations.interruptions:
        if interruption.review_status == UtteranceReviewStatus.REVIEW_REQUIRED:
            add(
                ReviewQueueKind.UNRESOLVED_INTERRUPTION,
                tuple(
                    item
                    for item in (
                        interruption.interrupted_utterance_id,
                        interruption.interrupting_utterance_id,
                    )
                    if item is not None
                ),
                (interruption.interruption_id,),
                (
                    ReviewActionKind.MARK_INTERRUPTION,
                    ReviewActionKind.REMOVE_INTERRUPTION,
                ),
                ("retain candidate", "remove unsupported relation"),
            )
    for continuation in artifacts.relations.continuations:
        if continuation.review_status == UtteranceReviewStatus.REVIEW_REQUIRED:
            add(
                ReviewQueueKind.UNRESOLVED_CONTINUATION,
                (
                    continuation.predecessor_utterance_id,
                    continuation.successor_utterance_id,
                ),
                (continuation.continuation_id,),
                (
                    ReviewActionKind.LINK_CONTINUATION,
                    ReviewActionKind.UNLINK_CONTINUATION,
                ),
                ("link as continuation", "retain separate utterances"),
            )
    for overlap in artifacts.relations.overlaps:
        if overlap.review_status == UtteranceReviewStatus.REVIEW_REQUIRED:
            add(
                ReviewQueueKind.UNCERTAIN_OVERLAP_ATTRIBUTION,
                overlap.affected_utterance_ids,
                (overlap.overlap_relation_id,),
                (
                    ReviewActionKind.FLAG_UNCERTAIN_SPEAKER,
                    ReviewActionKind.DEFER_DECISION,
                ),
                ("preserve mixed overlap", "review speaker assignment"),
            )
    for repair in artifacts.analysis.self_repairs:
        add(
            ReviewQueueKind.PROBABLE_SELF_REPAIR,
            (repair.utterance_id,),
            (repair.self_repair_id,),
            (
                ReviewActionKind.APPROVE_UTTERANCE,
                ReviewActionKind.FLAG_UNCERTAIN_TEXT,
            ),
            ("retain audible repair", "flag transcript uncertainty"),
        )
    for quotation in artifacts.quotation.quotations:
        if quotation.review_status == UtteranceReviewStatus.REVIEW_REQUIRED:
            add(
                ReviewQueueKind.UNCERTAIN_QUOTATION,
                (quotation.quoting_utterance_id,),
                (quotation.quotation_id,),
                (
                    ReviewActionKind.REVISE_QUOTATION_SPAN,
                    ReviewActionKind.CHANGE_QUOTATION_TYPE,
                ),
                ("retain candidate span", "revise with source evidence"),
            )
    if propagation is not None:
        for impact in propagation.impacts:
            if impact.affected:
                add(
                    ReviewQueueKind.CORRECTION_AFFECTED,
                    impact.successor_utterance_ids,
                    (impact.impact_id,),
                    (
                        ReviewActionKind.APPROVE_UTTERANCE,
                        ReviewActionKind.DEFER_DECISION,
                    ),
                    ("accept rebuilt successor", "inspect predecessor evidence"),
                )
    items = sorted(
        items,
        key=lambda item: (
            item.kind.value,
            item.utterance_ids,
            item.review_queue_item_id,
        ),
    )
    counts = {
        kind: sum(item.kind == kind for item in items)
        for kind in ReviewQueueKind
    }
    timestamp = generated_at or ledger.created_at
    return _seal(
        ReviewQueueReport,
        {
            "report_id": typed_id(
                "reviewqueuereport",
                ledger.review_ledger_id,
                tuple(item.integrity_sha256 for item in items),
            ),
            "utterance_corpus_id": artifacts.corpus.corpus_id,
            "review_ledger_id": ledger.review_ledger_id,
            "generated_at": timestamp,
            "items": tuple(items),
            "queue_kind_counts": tuple(
                f"{kind.value}={counts[kind]}" for kind in ReviewQueueKind
            ),
            "unresolved_item_count": len(items),
        },
    )


def persist_review_ledger(
    ledger: UtteranceReviewLedger,
    corpus: UtteranceCorpus,
    views: SpeakerAttributedTranscriptBundle,
    destination: Path,
) -> tuple[UtteranceReviewLedger, Path, bool]:
    validate_review_ledger(ledger, corpus, views)
    root = (
        destination.expanduser().resolve()
        / "review-ledgers"
        / ledger.review_ledger_id
    )
    path = root / "ledger.json"
    if path.exists():
        stored = load_review_ledger(root)
        validate_review_ledger(stored, corpus, views)
        if stored != ledger:
            raise Phase4ReviewIntegrityError(
                "cached review ledger is incompatible"
            )
        return stored, root, True
    _atomic(path, canonical_bytes(ledger))
    return ledger, root, False


def load_review_ledger(root: Path) -> UtteranceReviewLedger:
    root = root.expanduser().resolve(strict=True)
    return load_contract(
        (root / "ledger.json").read_bytes(), UtteranceReviewLedger
    )


def persist_review_queue(
    report: ReviewQueueReport,
    destination: Path,
) -> tuple[ReviewQueueReport, Path, bool]:
    _verify_seal(report, "review queue report")
    for item in report.items:
        _verify_seal(item, item.review_queue_item_id)
    root = (
        destination.expanduser().resolve()
        / "review-queues"
        / report.report_id
    )
    path = root / "report.json"
    if path.exists():
        stored = load_contract(path.read_bytes(), ReviewQueueReport)
        if stored != report:
            raise Phase4ReviewIntegrityError(
                "cached review queue is incompatible"
            )
        return stored, root, True
    _atomic(path, canonical_bytes(report))
    return report, root, False


def load_review_queue(root: Path) -> ReviewQueueReport:
    root = root.expanduser().resolve(strict=True)
    report = load_contract(
        (root / "report.json").read_bytes(), ReviewQueueReport
    )
    _verify_seal(report, "review queue report")
    for item in report.items:
        _verify_seal(item, item.review_queue_item_id)
    return report