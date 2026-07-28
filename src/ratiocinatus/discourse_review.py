"""Immutable discourse review ledgers, queues, and selective propagation."""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path

from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase4_contracts import Utterance, UtteranceCorpus, UtteranceTextKind
from .phase5_contracts import (
    DiscourseCorrectionPropagationPolicy,
    DiscourseCorpus,
    DiscourseReviewStatus,
    DiscourseTargetStatus,
)
from .phase5_review_contracts import (
    DiscoursePropagationReport,
    DiscoursePropagationRun,
    DiscourseReviewAction,
    DiscourseReviewActionKind,
    DiscourseReviewLedger,
    DiscourseReviewQueue,
    DiscourseReviewQueueItem,
    DiscourseReviewQueueKind,
    DiscourseReviewStateEntry,
    Phase5ChangeKind,
    UtteranceDiscourseImpact,
)


class DiscourseReviewIntegrityError(RuntimeError):
    """Review or propagation evidence is corrupt or incompatible."""


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


def _verify(item, label: str) -> None:
    expected = canonical_hash(
        item.model_dump(mode="json", exclude={"integrity_sha256"})
    )
    if expected != item.integrity_sha256:
        raise DiscourseReviewIntegrityError(f"{label} integrity is invalid")


def _state(values: dict[str, str]) -> tuple[DiscourseReviewStateEntry, ...]:
    return tuple(
        DiscourseReviewStateEntry(key=key, value=value)
        for key, value in sorted(values.items())
    )


def _initial_view(corpus: DiscourseCorpus) -> str:
    return typed_id("discourseview", corpus.corpus_id, "machine-proposal")


def create_discourse_review_ledger(
    corpus: DiscourseCorpus, *, created_at: datetime | None = None
) -> DiscourseReviewLedger:
    """Create version zero without modifying the Phase 4 source corpus."""
    timestamp = created_at or corpus.created_at
    return _seal(
        DiscourseReviewLedger,
        {
            "ledger_id": typed_id("discourseledger", corpus.corpus_id, 0),
            "predecessor_ledger_id": None,
            "discourse_corpus_id": corpus.corpus_id,
            "phase4_utterance_corpus_id": corpus.phase4_utterance_corpus_id,
            "ledger_version": 0,
            "actions": (),
            "current_discourse_view_version": _initial_view(corpus),
            "created_at": timestamp,
        },
    )


def validate_discourse_review_ledger(
    ledger: DiscourseReviewLedger, corpus: DiscourseCorpus
) -> None:
    _verify(ledger, "discourse review ledger")
    if (
        ledger.discourse_corpus_id != corpus.corpus_id
        or ledger.phase4_utterance_corpus_id
        != corpus.phase4_utterance_corpus_id
    ):
        raise DiscourseReviewIntegrityError(
            "review ledger uses incompatible source evidence"
        )
    for item in ledger.actions:
        _verify(item, item.review_id)


def append_discourse_review_action(
    ledger: DiscourseReviewLedger,
    corpus: DiscourseCorpus,
    action: DiscourseReviewActionKind,
    target_artifact_ids: tuple[str, ...],
    *,
    prior_state: dict[str, str],
    proposed_state: dict[str, str],
    author: str,
    reviewed_at: datetime,
    rationale: str,
    evidence_references: tuple[str, ...],
    certainty: float,
    resulting_review_status: DiscourseReviewStatus,
) -> DiscourseReviewLedger:
    """Return a successor ledger containing exactly one new immutable action."""
    validate_discourse_review_ledger(ledger, corpus)
    if not prior_state or not proposed_state:
        raise DiscourseReviewIntegrityError(
            "review actions require prior and proposed state"
        )
    known = {
        *(item.observation_id for item in corpus.observations),
        *(item.candidate_set_id for item in corpus.candidate_sets),
        *(item.act_id for item in corpus.selected_acts),
    }
    if not target_artifact_ids or not set(target_artifact_ids).issubset(known):
        raise DiscourseReviewIntegrityError(
            "review action targets unknown discourse artifacts"
        )
    predecessor = ledger.actions[-1].review_id if ledger.actions else None
    ordinal = ledger.ledger_version + 1
    review_id = typed_id(
        "discoursereview",
        ledger.ledger_id,
        ordinal,
        action.value,
        target_artifact_ids,
        reviewed_at.isoformat(),
    )
    view = typed_id(
        "discourseview",
        ledger.current_discourse_view_version,
        review_id,
        proposed_state,
    )
    item = _seal(
        DiscourseReviewAction,
        {
            "review_id": review_id,
            "predecessor_review_id": predecessor,
            "action": action,
            "target_artifact_ids": tuple(dict.fromkeys(target_artifact_ids)),
            "prior_state": _state(prior_state),
            "proposed_state": _state(proposed_state),
            "author": author,
            "reviewed_at": reviewed_at,
            "rationale": rationale,
            "evidence_references": tuple(
                dict.fromkeys(evidence_references)
            ),
            "certainty": certainty,
            "resulting_discourse_view_version": view,
            "resulting_review_status": resulting_review_status,
        },
    )
    return _seal(
        DiscourseReviewLedger,
        {
            "ledger_id": typed_id(
                "discourseledger", ledger.ledger_id, review_id
            ),
            "predecessor_ledger_id": ledger.ledger_id,
            "discourse_corpus_id": ledger.discourse_corpus_id,
            "phase4_utterance_corpus_id": (
                ledger.phase4_utterance_corpus_id
            ),
            "ledger_version": ordinal,
            "actions": (*ledger.actions, item),
            "current_discourse_view_version": view,
            "created_at": reviewed_at,
        },
    )


def _display(utterance: Utterance) -> str:
    return next(
        item.text
        for item in utterance.text_views
        if item.kind == UtteranceTextKind.DISPLAY
    )


def _queue_item(
    kind,
    utterance,
    targets,
    acts,
    spans,
    alternatives,
    confidence,
    actions,
    evidence,
):
    intervals = tuple(
        "source:"
        f"{item.start_microseconds}:"
        f"{item.start_microseconds + item.duration_microseconds}"
        for item in utterance.source_intervals
    )
    context = utterance.context_reference_ids or (utterance.utterance_id,)
    payload = {
        "kind": kind,
        "target_artifact_ids": tuple(targets),
        "utterance_ids": (utterance.utterance_id,),
        "source_interval_references": intervals,
        "utterance_text": _display(utterance),
        "speaker_attribution": utterance.attribution.display_label,
        "local_context_references": context,
        "proposed_act_ids": tuple(acts),
        "evidence_span_ids": tuple(spans),
        "relation_target_ids": (),
        "alternatives": tuple(alternatives),
        "confidence": confidence,
        "proposed_actions": tuple(actions),
        "evidence_references": tuple(evidence),
    }
    payload["item_id"] = typed_id(
        "discoursereviewqueue", kind.value, targets, evidence
    )
    return _seal(DiscourseReviewQueueItem, payload)


def build_discourse_review_queue(
    corpus: DiscourseCorpus,
    phase4_corpus: UtteranceCorpus,
    ledger: DiscourseReviewLedger,
    *,
    propagation: DiscoursePropagationRun | None = None,
    generated_at: datetime | None = None,
) -> DiscourseReviewQueue:
    """Derive evidence-rich queues while retaining every machine proposal."""
    validate_discourse_review_ledger(ledger, corpus)
    if corpus.phase4_utterance_corpus_id != phase4_corpus.corpus_id:
        raise DiscourseReviewIntegrityError("queue sources are incompatible")
    utterances = {
        item.utterance_id: item for item in phase4_corpus.utterances
    }
    acts_by_utterance: dict[str, list] = {}
    for act in corpus.selected_acts:
        acts_by_utterance.setdefault(act.utterance_id, []).append(act)
    items = []
    for candidate_set in corpus.candidate_sets:
        if not candidate_set.unresolved:
            continue
        utterance = utterances[candidate_set.utterance_id]
        candidate_ids = tuple(
            item.candidate_id for item in candidate_set.candidates
        )
        items.append(
            _queue_item(
                DiscourseReviewQueueKind.INCOMPATIBLE_CANDIDATES,
                utterance,
                (candidate_set.candidate_set_id,),
                tuple(
                    item.act_id
                    for item in acts_by_utterance.get(
                        utterance.utterance_id, ()
                    )
                ),
                tuple(
                    span_id
                    for candidate in candidate_set.candidates
                    for span_id in candidate.evidence_span_ids
                ),
                candidate_ids,
                max(
                    (
                        item.selection_confidence.value
                        for item in candidate_set.candidates
                        if item.selection_confidence.value is not None
                    ),
                    default=None,
                ),
                (
                    DiscourseReviewActionKind.ADD_ALTERNATIVE,
                    DiscourseReviewActionKind.REMOVE_ALTERNATIVE,
                    DiscourseReviewActionKind.DEFER_DECISION,
                ),
                (candidate_set.candidate_set_id, *candidate_ids),
            )
        )
    for act in corpus.selected_acts:
        utterance = utterances[act.utterance_id]
        score = act.confidence.selection.value
        if score is not None and score < 0.8:
            items.append(
                _queue_item(
                    DiscourseReviewQueueKind.LOW_CONFIDENCE_ACT,
                    utterance,
                    (act.act_id,),
                    (act.act_id,),
                    tuple(span.span_id for span in act.evidence_spans),
                    (),
                    score,
                    (
                        DiscourseReviewActionKind.APPROVE_ACT,
                        DiscourseReviewActionKind.REJECT_ACT,
                        DiscourseReviewActionKind.CHANGE_ACT_TYPE,
                    ),
                    (act.act_id, *act.source_observation_ids),
                )
            )
        if any(
            target.target_status == DiscourseTargetStatus.UNRESOLVED
            for target in act.relation_targets
        ):
            items.append(
                _queue_item(
                    DiscourseReviewQueueKind.RELATION_WITHOUT_TARGET,
                    utterance,
                    (act.act_id,),
                    (act.act_id,),
                    tuple(span.span_id for span in act.evidence_spans),
                    (),
                    act.confidence.target_relation.value,
                    (
                        DiscourseReviewActionKind.CHANGE_RELATION_TARGET,
                        DiscourseReviewActionKind.MARK_TARGET_UNRESOLVED,
                    ),
                    (act.act_id,),
                )
            )
    if propagation is not None:
        for impact in propagation.impacts:
            for act_id in impact.invalidated_act_ids:
                act = next(
                    item
                    for item in corpus.selected_acts
                    if item.act_id == act_id
                )
                utterance = utterances[act.utterance_id]
                items.append(
                    _queue_item(
                        DiscourseReviewQueueKind.CORRECTION_AFFECTED_ACT,
                        utterance,
                        (act_id,),
                        (act_id,),
                        tuple(span.span_id for span in act.evidence_spans),
                        (),
                        act.confidence.selection.value,
                        (
                            DiscourseReviewActionKind.APPROVE_ACT,
                            DiscourseReviewActionKind.CHANGE_EVIDENCE_SPAN,
                            DiscourseReviewActionKind.DEFER_DECISION,
                        ),
                        (impact.impact_id, act_id),
                    )
                )
    items = sorted(items, key=lambda item: (item.kind.value, item.item_id))
    counts = tuple(
        f"{kind.value}={sum(item.kind == kind for item in items)}"
        for kind in DiscourseReviewQueueKind
    )
    timestamp = generated_at or ledger.created_at
    return _seal(
        DiscourseReviewQueue,
        {
            "queue_id": typed_id(
                "discoursequeue",
                ledger.ledger_id,
                tuple(item.integrity_sha256 for item in items),
            ),
            "discourse_corpus_id": corpus.corpus_id,
            "ledger_id": ledger.ledger_id,
            "generated_at": timestamp,
            "items": tuple(items),
            "queue_kind_counts": counts,
            "unresolved_item_count": len(items),
        },
    )


def _attribution_core(utterance: Utterance):
    value = utterance.attribution
    return (
        value.status,
        value.target_kind,
        value.target_id,
        value.candidate_target_ids,
    )


def _boundary(utterance: Utterance):
    return (
        utterance.source_intervals,
        utterance.normalized_audio_intervals,
        tuple(
            (
                item.source_interval,
                item.normalized_audio_interval,
                item.transcript_segment_ids,
                item.transcript_word_ids,
            )
            for item in utterance.components
        ),
    )


def _structural(utterance: Utterance):
    return (
        utterance.interruption_status,
        utterance.repair_status,
        utterance.context_reference_ids,
        utterance.predecessor_utterance_ids,
        utterance.invalidates_utterance_ids,
    )


def build_discourse_propagation(
    predecessor_phase4: UtteranceCorpus,
    successor_phase4: UtteranceCorpus,
    discourse: DiscourseCorpus,
    *,
    created_at: datetime,
    identity_specific_context_utterance_ids: tuple[str, ...] = (),
    policy: DiscourseCorrectionPropagationPolicy | None = None,
) -> tuple[DiscoursePropagationRun, DiscoursePropagationReport]:
    """Plan selective invalidation without rewriting any source artifact."""
    policy = policy or DiscourseCorrectionPropagationPolicy()
    if (
        discourse.phase4_utterance_corpus_id != predecessor_phase4.corpus_id
        or discourse.phase4_utterance_corpus_sha256
        != canonical_hash(predecessor_phase4)
    ):
        raise DiscourseReviewIntegrityError(
            "discourse corpus is not derived from the predecessor Phase 4 corpus"
        )
    old = {item.utterance_id: item for item in predecessor_phase4.utterances}
    new = {item.utterance_id: item for item in successor_phase4.utterances}
    observations = {}
    sets = {}
    acts = {}
    for item in discourse.observations:
        observations.setdefault(item.utterance_id, []).append(item)
    for item in discourse.candidate_sets:
        sets.setdefault(item.utterance_id, []).append(item)
    for item in discourse.selected_acts:
        acts.setdefault(item.utterance_id, []).append(item)
    identity_context = set(identity_specific_context_utterance_ids)
    impacts = []
    all_ids = sorted(set(old) | set(new))
    for utterance_id in all_ids:
        prior, current = old.get(utterance_id), new.get(utterance_id)
        changes = []
        if prior is None:
            changes.append(Phase5ChangeKind.ADDED_UTTERANCE)
        elif current is None:
            changes.append(Phase5ChangeKind.REMOVED_UTTERANCE)
        else:
            if _display(prior) != _display(current):
                changes.append(Phase5ChangeKind.TEXT)
            if _boundary(prior) != _boundary(current):
                changes.append(Phase5ChangeKind.BOUNDARY)
            attribution_changed = _attribution_core(prior) != _attribution_core(
                current
            )
            label_changed = (
                prior.attribution.display_label
                != current.attribution.display_label
            )
            if attribution_changed:
                changes.append(Phase5ChangeKind.SPEAKER_ATTRIBUTION)
            elif label_changed:
                changes.append(Phase5ChangeKind.DISPLAY_LABEL_ONLY)
            if prior.quotation_status != current.quotation_status:
                changes.append(Phase5ChangeKind.QUOTATION_STRUCTURE)
            if _structural(prior) != _structural(current):
                changes.append(
                    Phase5ChangeKind.INTERRUPTION_OR_CONTINUATION
                )
        if not changes:
            continue
        source_observations = observations.get(utterance_id, ())
        source_sets = sets.get(utterance_id, ())
        source_acts = acts.get(utterance_id, ())
        span_invalidating = bool(
            {
                Phase5ChangeKind.TEXT,
                Phase5ChangeKind.BOUNDARY,
                Phase5ChangeKind.REMOVED_UTTERANCE,
            }.intersection(changes)
        )
        quotation_invalidating = (
            Phase5ChangeKind.QUOTATION_STRUCTURE in changes
        )
        identity_invalidating = (
            Phase5ChangeKind.SPEAKER_ATTRIBUTION in changes
            and utterance_id in identity_context
        )
        invalidate = (
            span_invalidating
            or identity_invalidating
            or prior is None
        )
        invalid_obs = tuple(
            item.observation_id
            for item in source_observations
            if invalidate
            or (
                quotation_invalidating
                and item.act_family.value == "quotation_and_attribution"
            )
        )
        invalid_obs_set = set(invalid_obs)
        invalid_sets = tuple(
            item.candidate_set_id
            for item in source_sets
            if any(
                invalid_obs_set.intersection(candidate.observation_ids)
                for candidate in item.candidates
            )
        )
        invalid_set_set = set(invalid_sets)
        invalid_acts = tuple(
            item.act_id
            for item in source_acts
            if item.candidate_set_id in invalid_set_set
        )
        preserved = tuple(
            item.act_id
            for item in source_acts
            if item.act_id not in set(invalid_acts)
        )
        relation_rebuild = tuple(
            item.act_id
            for item in source_acts
            if Phase5ChangeKind.INTERRUPTION_OR_CONTINUATION in changes
            or item.act_id in invalid_acts
        )
        explanation = (
            "Display-label-only speaker change preserves classification."
            if changes == [Phase5ChangeKind.DISPLAY_LABEL_ONLY]
            else (
                "Text or boundary evidence changed; dependent spans, "
                "observations, candidates, and acts are invalidated."
                if span_invalidating
                else "Only artifacts with an explicit dependency are invalidated."
            )
        )
        impacts.append(
            _seal(
                UtteranceDiscourseImpact,
                {
                    "impact_id": typed_id(
                        "discourseimpact",
                        predecessor_phase4.corpus_id,
                        successor_phase4.corpus_id,
                        utterance_id,
                        tuple(item.value for item in changes),
                    ),
                    "predecessor_utterance_ids": (
                        (utterance_id,) if prior else ()
                    ),
                    "successor_utterance_ids": (
                        (utterance_id,) if current else ()
                    ),
                    "change_kinds": tuple(changes),
                    "invalidated_observation_ids": invalid_obs,
                    "invalidated_candidate_set_ids": invalid_sets,
                    "invalidated_act_ids": invalid_acts,
                    "preserved_act_ids": preserved,
                    "rebuild_relation_target_act_ids": relation_rebuild,
                    "identity_specific_context_used": (
                        utterance_id in identity_context
                    ),
                    "explanation": explanation,
                },
            )
        )
    def union(field):
        return tuple(
            sorted(
                {
                    value
                    for impact in impacts
                    for value in getattr(impact, field)
                }
            )
        )

    invalid_obs = union("invalidated_observation_ids")
    invalid_sets = union("invalidated_candidate_set_ids")
    invalid_acts = union("invalidated_act_ids")
    invalid_act_set = set(invalid_acts)
    preserved = tuple(
        sorted(
            item.act_id
            for item in discourse.selected_acts
            if item.act_id not in invalid_act_set
        )
    )
    relation_rebuild = union("rebuild_relation_target_act_ids")
    configuration_hash = canonical_hash(
        {
            "operation": "discourse.correction_propagation",
            "predecessor": canonical_hash(predecessor_phase4),
            "successor": canonical_hash(successor_phase4),
            "discourse": canonical_hash(discourse),
            "policy": policy.model_dump(mode="json"),
            "identity_specific_context": sorted(identity_context),
        }
    )
    run = _seal(
        DiscoursePropagationRun,
        {
            "propagation_run_id": typed_id(
                "discoursepropagation",
                predecessor_phase4.corpus_id,
                successor_phase4.corpus_id,
                configuration_hash,
            ),
            "predecessor_phase4_corpus_id": predecessor_phase4.corpus_id,
            "successor_phase4_corpus_id": successor_phase4.corpus_id,
            "predecessor_discourse_corpus_id": discourse.corpus_id,
            "policy": policy,
            "configuration_hash": configuration_hash,
            "impacts": tuple(impacts),
            "invalidated_observation_ids": invalid_obs,
            "invalidated_candidate_set_ids": invalid_sets,
            "invalidated_act_ids": invalid_acts,
            "preserved_act_ids": preserved,
            "rebuild_relation_target_act_ids": relation_rebuild,
            "rebuild_procedural_state": bool(impacts),
            "rebuild_review_queues": bool(impacts),
            "created_at": created_at,
            "complete": True,
        },
    )
    label_count = sum(
        impact.change_kinds == (Phase5ChangeKind.DISPLAY_LABEL_ONLY,)
        for impact in impacts
    )
    report = _seal(
        DiscoursePropagationReport,
        {
            "report_id": typed_id(
                "discoursepropagationreport", run.propagation_run_id
            ),
            "propagation_run_id": run.propagation_run_id,
            "generated_at": created_at,
            "changed_utterance_count": len(impacts),
            "invalidated_observation_count": len(invalid_obs),
            "invalidated_act_count": len(invalid_acts),
            "preserved_act_count": len(preserved),
            "relation_rebuild_count": len(relation_rebuild),
            "display_label_only_change_count": label_count,
            "status": "complete",
            "limitations": (
                "Propagation records a selective rebuild plan; successor "
                "artifacts are produced by their owning construction stages.",
                "Speaker attribution affects classification only when its "
                "identity-specific dependency is explicitly declared.",
            ),
        },
    )
    return run, report


def validate_discourse_propagation(run, report, predecessor, successor, corpus):
    _verify(run, "discourse propagation run")
    _verify(report, "discourse propagation report")
    for item in run.impacts:
        _verify(item, item.impact_id)
    if (
        run.predecessor_phase4_corpus_id != predecessor.corpus_id
        or run.successor_phase4_corpus_id != successor.corpus_id
        or run.predecessor_discourse_corpus_id != corpus.corpus_id
        or report.propagation_run_id != run.propagation_run_id
    ):
        raise DiscourseReviewIntegrityError(
            "propagation sources are incompatible"
        )


def persist_discourse_review_ledger(ledger, corpus, destination):
    validate_discourse_review_ledger(ledger, corpus)
    root = destination.expanduser().resolve() / "discourse-review" / ledger.ledger_id
    path = root / "ledger.json"
    if path.exists():
        stored = load_discourse_review_ledger(root)
        if stored != ledger:
            raise DiscourseReviewIntegrityError("cached ledger is incompatible")
        return stored, root, True
    _atomic(path, canonical_bytes(ledger))
    return ledger, root, False


def load_discourse_review_ledger(root: Path):
    return load_contract(
        (root.expanduser().resolve(strict=True) / "ledger.json").read_bytes(),
        DiscourseReviewLedger,
    )


def persist_discourse_review_queue(queue, destination):
    _verify(queue, "discourse review queue")
    root = destination.expanduser().resolve() / "discourse-queue" / queue.queue_id
    path = root / "queue.json"
    if path.exists():
        stored = load_discourse_review_queue(root)
        if stored != queue:
            raise DiscourseReviewIntegrityError("cached queue is incompatible")
        return stored, root, True
    _atomic(path, canonical_bytes(queue))
    return queue, root, False


def load_discourse_review_queue(root: Path):
    queue = load_contract(
        (root.expanduser().resolve(strict=True) / "queue.json").read_bytes(),
        DiscourseReviewQueue,
    )
    _verify(queue, "discourse review queue")
    for item in queue.items:
        _verify(item, item.item_id)
    return queue


def persist_discourse_propagation(run, report, predecessor, successor, corpus, destination):
    validate_discourse_propagation(
        run, report, predecessor, successor, corpus
    )
    root = destination.expanduser().resolve() / "discourse-propagation" / run.propagation_run_id
    run_path, report_path = root / "run.json", root / "report.json"
    if run_path.exists() and report_path.exists():
        stored = load_discourse_propagation(root)
        if stored != (run, report):
            raise DiscourseReviewIntegrityError(
                "cached propagation is incompatible"
            )
        return run, report, root, True
    _atomic(run_path, canonical_bytes(run))
    _atomic(report_path, canonical_bytes(report))
    return run, report, root, False


def load_discourse_propagation(root: Path):
    resolved = root.expanduser().resolve(strict=True)
    run = load_contract(
        (resolved / "run.json").read_bytes(), DiscoursePropagationRun
    )
    report = load_contract(
        (resolved / "report.json").read_bytes(), DiscoursePropagationReport
    )
    return run, report
