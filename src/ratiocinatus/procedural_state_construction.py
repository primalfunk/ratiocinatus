"""Construct an ordered, descriptive procedural conversation state."""

from __future__ import annotations

import os
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path

from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase4_contracts import UtteranceCorpus
from .phase5_contracts import (
    DiscourseActFamily,
    DiscourseActType,
    DiscourseCorpus,
    DiscourseReviewStatus,
    DiscourseTargetStatus,
)
from .phase5_foundation import validate_discourse_corpus_seal
from .phase5_procedural_state_contracts import (
    ProceduralEvent,
    ProceduralEventKind,
    ProceduralStatePolicy,
    ProceduralStateReport,
    ProceduralStateRun,
    ProceduralStateSnapshot,
)


class ProceduralStateIntegrityError(RuntimeError):
    """Procedural state is corrupt, stale, or source-incompatible."""


_EVENT_KINDS = {
    DiscourseActType.FLOOR_REQUEST: ProceduralEventKind.FLOOR_REQUEST,
    DiscourseActType.FLOOR_GRANT: ProceduralEventKind.FLOOR_GRANT,
    DiscourseActType.FLOOR_DENIAL: ProceduralEventKind.FLOOR_DENIAL,
    DiscourseActType.TURN_YIELD: ProceduralEventKind.TURN_YIELD,
    DiscourseActType.TIME_WARNING: ProceduralEventKind.TIME_WARNING,
    DiscourseActType.TIME_EXPIRED_NOTICE: ProceduralEventKind.TIME_EXPIRED,
    DiscourseActType.TOPIC_TRANSITION:
        ProceduralEventKind.TOPIC_TRANSITION,
    DiscourseActType.AGENDA_SETTING: ProceduralEventKind.AGENDA_SETTING,
    DiscourseActType.REQUEST_TO_ANSWER:
        ProceduralEventKind.ANSWER_REQUEST,
    DiscourseActType.REQUEST_TO_CLARIFY:
        ProceduralEventKind.CLARIFICATION_REQUEST,
    DiscourseActType.REQUEST_TO_STOP: ProceduralEventKind.STOP_REQUEST,
    DiscourseActType.MODERATOR_INTERVENTION:
        ProceduralEventKind.MODERATOR_INSTRUCTION,
    DiscourseActType.RULE_INVOCATION: ProceduralEventKind.RULE_EVENT,
    DiscourseActType.RULE_EXPLANATION: ProceduralEventKind.RULE_EVENT,
    DiscourseActType.PROCEDURE_ACKNOWLEDGMENT:
        ProceduralEventKind.PROCEDURE_ACKNOWLEDGMENT,
    DiscourseActType.INTRODUCTION:
        ProceduralEventKind.OPENING_OR_CLOSING,
    DiscourseActType.CLOSING: ProceduralEventKind.OPENING_OR_CLOSING,
    DiscourseActType.GREETING: ProceduralEventKind.SOCIAL_PROCEDURAL,
    DiscourseActType.THANKS: ProceduralEventKind.SOCIAL_PROCEDURAL,
    DiscourseActType.APOLOGY: ProceduralEventKind.SOCIAL_PROCEDURAL,
    DiscourseActType.TECHNICAL_INTERRUPTION_NOTICE:
        ProceduralEventKind.TECHNICAL_INTERRUPTION,
    DiscourseActType.PROCEDURAL_QUESTION:
        ProceduralEventKind.PROCEDURAL_QUESTION,
}


def _seal(model, payload):
    provisional = model(**payload, integrity_sha256="0" * 64)
    return provisional.model_copy(
        update={
            "integrity_sha256": canonical_hash(
                provisional.model_copy(
                    update={"integrity_sha256": "0" * 64}
                )
            )
        }
    )


def _verify_seal(item, label):
    expected = _seal(
        type(item),
        item.model_dump(mode="python", exclude={"integrity_sha256"}),
    )
    if expected != item:
        raise ProceduralStateIntegrityError(f"{label} integrity is invalid")


def _start(act):
    return min(
        item.source_interval.start_microseconds for item in act.evidence_spans
    )


def _intervals(act):
    return tuple(
        {
            (
                item.source_interval.start_microseconds,
                item.source_interval.duration_microseconds,
            ): item.source_interval
            for item in act.evidence_spans
        }.values()
    )


def _question_targets(act, acts):
    questions = [
        item
        for item in acts
        if item.act_family == DiscourseActFamily.QUESTION
        and _start(item) < _start(act)
    ]
    if not questions:
        return DiscourseTargetStatus.UNRESOLVED, (), ()
    nearest_start = max(_start(item) for item in questions)
    nearest = tuple(
        item.act_id for item in questions if _start(item) == nearest_start
    )
    if len(nearest) == 1:
        return DiscourseTargetStatus.PROBABLE, nearest, ()
    return DiscourseTargetStatus.MULTIPLE_CANDIDATES, (), nearest


def _targets(act, acts):
    target_ids = tuple(
        dict.fromkeys(
            item.target_id
            for item in act.relation_targets
            if item.target_id is not None
        )
    )
    alternatives = tuple(
        dict.fromkeys(
            target
            for item in act.relation_targets
            for target in item.alternative_target_ids
            if target not in target_ids
        )
    )
    if target_ids:
        return DiscourseTargetStatus.IDENTIFIED, target_ids, alternatives
    if len(alternatives) >= 2:
        return (
            DiscourseTargetStatus.MULTIPLE_CANDIDATES,
            (),
            alternatives,
        )
    if act.act_type == DiscourseActType.REQUEST_TO_ANSWER:
        return _question_targets(act, acts)
    if act.act_type in {
        DiscourseActType.PROCEDURAL_QUESTION,
        DiscourseActType.TIME_WARNING,
        DiscourseActType.TIME_EXPIRED_NOTICE,
        DiscourseActType.TOPIC_TRANSITION,
        DiscourseActType.AGENDA_SETTING,
        DiscourseActType.RULE_INVOCATION,
        DiscourseActType.RULE_EXPLANATION,
        DiscourseActType.PROCEDURE_ACKNOWLEDGMENT,
        DiscourseActType.INTRODUCTION,
        DiscourseActType.CLOSING,
        DiscourseActType.GREETING,
        DiscourseActType.THANKS,
        DiscourseActType.APOLOGY,
        DiscourseActType.TECHNICAL_INTERRUPTION_NOTICE,
    }:
        return DiscourseTargetStatus.IMPLICIT, (), ()
    return DiscourseTargetStatus.UNRESOLVED, (), ()


def _effects(act_type):
    mapping = {
        DiscourseActType.FLOOR_REQUEST:
            ("floor requested; no grant inferred",),
        DiscourseActType.FLOOR_GRANT:
            ("response interval opened; recipient may be unresolved",),
        DiscourseActType.FLOOR_DENIAL:
            ("floor denial recorded; fault is not inferred",),
        DiscourseActType.TURN_YIELD:
            ("response interval closed by explicit yield",),
        DiscourseActType.TIME_WARNING:
            ("time warning recorded",),
        DiscourseActType.TIME_EXPIRED_NOTICE:
            ("time expiration notice recorded",),
        DiscourseActType.TOPIC_TRANSITION:
            ("topic transition recorded",),
        DiscourseActType.AGENDA_SETTING:
            ("agenda-setting instruction recorded",),
        DiscourseActType.REQUEST_TO_ANSWER:
            ("answer request recorded; pending question target preserved",),
        DiscourseActType.REQUEST_TO_CLARIFY:
            ("clarification request recorded",),
        DiscourseActType.REQUEST_TO_STOP:
            ("stop request recorded; compliance is not inferred",),
        DiscourseActType.MODERATOR_INTERVENTION:
            ("moderator intervention recorded descriptively",),
        DiscourseActType.RULE_INVOCATION:
            ("rule invocation recorded; violation is not inferred",),
        DiscourseActType.RULE_EXPLANATION:
            ("rule explanation recorded",),
        DiscourseActType.PROCEDURE_ACKNOWLEDGMENT:
            ("procedure acknowledgment recorded",),
        DiscourseActType.PROCEDURAL_QUESTION:
            ("procedural question recorded as pending",),
    }
    return mapping.get(
        act_type, ("procedural speech event recorded descriptively",)
    )


def build_procedural_state(
    corpus: DiscourseCorpus,
    phase4_corpus: UtteranceCorpus,
    *,
    created_at: datetime,
    policy: ProceduralStatePolicy | None = None,
):
    validate_discourse_corpus_seal(corpus)
    if (
        corpus.phase4_utterance_corpus_id != phase4_corpus.corpus_id
        or corpus.phase4_utterance_corpus_sha256
        != canonical_hash(phase4_corpus)
    ):
        raise ProceduralStateIntegrityError(
            "procedural state uses incompatible Phase 4 lineage"
        )
    policy = policy or ProceduralStatePolicy()
    utterances = {
        item.utterance_id: item for item in phase4_corpus.utterances
    }
    procedural_acts = tuple(
        sorted(
            (
                item
                for item in corpus.selected_acts
                if item.act_family == DiscourseActFamily.PROCEDURAL
                or item.act_type == DiscourseActType.PROCEDURAL_QUESTION
            ),
            key=lambda item: (_start(item), item.act_id),
        )
    )
    events = []
    for act in procedural_acts:
        utterance = utterances[act.utterance_id]
        status, targets, alternatives = _targets(
            act, corpus.selected_acts
        )
        events.append(
            _seal(
                ProceduralEvent,
                {
                    "event_id": typed_id(
                        "proceduralevent", corpus.corpus_id, act.act_id
                    ),
                    "discourse_corpus_id": corpus.corpus_id,
                    "source_act_id": act.act_id,
                    "utterance_id": act.utterance_id,
                    "procedural_act_type": act.act_type,
                    "event_kind": _EVENT_KINDS.get(
                        act.act_type, ProceduralEventKind.UNRESOLVED
                    ),
                    "source_intervals": _intervals(act),
                    "evidence_span_ids": tuple(
                        item.span_id for item in act.evidence_spans
                    ),
                    "observed_attribution_id": (
                        utterance.attribution.attribution_id
                    ),
                    "observed_speaker_target_id": (
                        utterance.attribution.target_id
                    ),
                    "observed_speaker_display_label": (
                        utterance.attribution.display_label
                    ),
                    "procedural_target_status": status,
                    "procedural_target_ids": targets,
                    "alternative_procedural_target_ids": alternatives,
                    "descriptive_effects": _effects(act.act_type),
                    "confidence": (
                        act.confidence.procedural_state
                        or act.confidence.act_type
                    ),
                    "review_status": (
                        act.review_status
                        if status == DiscourseTargetStatus.IDENTIFIED
                        else DiscourseReviewStatus.REVIEW_REQUIRED
                    ),
                    "created_at": created_at,
                },
            )
        )
    configuration_hash = canonical_hash(
        {
            "operation": "discourse.procedural_state",
            "discourse_corpus_sha256": canonical_hash(corpus),
            "phase4_utterance_corpus_sha256": canonical_hash(
                phase4_corpus
            ),
            "policy": policy.model_dump(mode="json"),
        }
    )
    run_id = typed_id(
        "proceduralstaterun", corpus.corpus_id, configuration_hash
    )
    state = {
        "recognized_speaker_target_id": None,
        "recognized_speaker_status": DiscourseTargetStatus.UNRESOLVED,
        "pending_question_act_ids": (),
        "alternative_pending_question_act_ids": (),
        "active_response": False,
        "active_response_started_microseconds": None,
        "active_response_target_id": None,
        "latest_moderator_instruction_act_id": None,
        "latest_time_warning_act_id": None,
        "time_expired": False,
        "granted_extension": False,
        "latest_clarification_request_act_id": None,
        "latest_topic_transition_act_id": None,
        "unresolved_event_ids": (),
    }
    snapshots = []
    unresolved = []
    moderator_types = {
        DiscourseActType.FLOOR_GRANT,
        DiscourseActType.FLOOR_DENIAL,
        DiscourseActType.REQUEST_TO_ANSWER,
        DiscourseActType.REQUEST_TO_CLARIFY,
        DiscourseActType.REQUEST_TO_STOP,
        DiscourseActType.MODERATOR_INTERVENTION,
        DiscourseActType.RULE_INVOCATION,
        DiscourseActType.RULE_EXPLANATION,
    }
    for position, (act, event) in enumerate(zip(procedural_acts, events)):
        start = _start(act)
        if event.procedural_target_status in {
            DiscourseTargetStatus.MULTIPLE_CANDIDATES,
            DiscourseTargetStatus.UNRESOLVED,
        }:
            unresolved.append(event.event_id)
        if act.act_type == DiscourseActType.FLOOR_GRANT:
            state["active_response"] = True
            state["active_response_started_microseconds"] = start
            state["active_response_target_id"] = (
                event.procedural_target_ids[0]
                if len(event.procedural_target_ids) == 1
                else None
            )
        elif act.act_type in {
            DiscourseActType.TURN_YIELD,
            DiscourseActType.TIME_EXPIRED_NOTICE,
        }:
            state["active_response"] = False
            state["active_response_started_microseconds"] = None
            state["active_response_target_id"] = None
        if act.act_type == DiscourseActType.REQUEST_TO_ANSWER:
            state["pending_question_act_ids"] = (
                event.procedural_target_ids
            )
            state["alternative_pending_question_act_ids"] = (
                event.alternative_procedural_target_ids
            )
        elif act.act_type == DiscourseActType.PROCEDURAL_QUESTION:
            state["pending_question_act_ids"] = (act.act_id,)
            state["alternative_pending_question_act_ids"] = ()
        if act.act_type in moderator_types:
            state["latest_moderator_instruction_act_id"] = act.act_id
        if act.act_type == DiscourseActType.TIME_WARNING:
            state["latest_time_warning_act_id"] = act.act_id
        if act.act_type == DiscourseActType.TIME_EXPIRED_NOTICE:
            state["time_expired"] = True
        if act.act_type == DiscourseActType.REQUEST_TO_CLARIFY:
            state["latest_clarification_request_act_id"] = act.act_id
        if act.act_type == DiscourseActType.TOPIC_TRANSITION:
            state["latest_topic_transition_act_id"] = act.act_id
        state["unresolved_event_ids"] = tuple(unresolved)
        snapshots.append(
            _seal(
                ProceduralStateSnapshot,
                {
                    "snapshot_id": typed_id(
                        "proceduralstate",
                        run_id,
                        position,
                        event.event_id,
                    ),
                    "procedural_state_run_id": run_id,
                    "sequence_position": position,
                    "triggering_event_id": event.event_id,
                    "effective_source_microseconds": start,
                    "observed_speaker_target_id": (
                        event.observed_speaker_target_id
                    ),
                    "observed_speaker_display_label": (
                        event.observed_speaker_display_label
                    ),
                    **state,
                },
            )
        )
    run = _seal(
        ProceduralStateRun,
        {
            "procedural_state_run_id": run_id,
            "discourse_corpus_id": corpus.corpus_id,
            "discourse_corpus_sha256": canonical_hash(corpus),
            "phase4_utterance_corpus_id": phase4_corpus.corpus_id,
            "phase4_utterance_corpus_sha256": canonical_hash(
                phase4_corpus
            ),
            "policy": policy,
            "configuration_hash": configuration_hash,
            "events": tuple(events),
            "snapshots": tuple(snapshots),
            "final_snapshot_id": (
                snapshots[-1].snapshot_id if snapshots else None
            ),
            "created_at": created_at,
            "complete": True,
        },
    )
    counts = Counter(item.event_kind for item in events)
    final = snapshots[-1] if snapshots else None
    report = _seal(
        ProceduralStateReport,
        {
            "report_id": typed_id("proceduralstatereport", run_id),
            "procedural_state_run_id": run_id,
            "generated_at": created_at,
            "event_count": len(events),
            "floor_event_count": sum(
                counts[item]
                for item in {
                    ProceduralEventKind.FLOOR_REQUEST,
                    ProceduralEventKind.FLOOR_GRANT,
                    ProceduralEventKind.FLOOR_DENIAL,
                    ProceduralEventKind.TURN_YIELD,
                }
            ),
            "timing_event_count": (
                counts[ProceduralEventKind.TIME_WARNING]
                + counts[ProceduralEventKind.TIME_EXPIRED]
            ),
            "moderator_instruction_count": sum(
                act.act_type in moderator_types for act in procedural_acts
            ),
            "pending_question_event_count": (
                counts[ProceduralEventKind.ANSWER_REQUEST]
                + counts[ProceduralEventKind.PROCEDURAL_QUESTION]
            ),
            "topic_transition_count": counts[
                ProceduralEventKind.TOPIC_TRANSITION
            ],
            "technical_interruption_count": counts[
                ProceduralEventKind.TECHNICAL_INTERRUPTION
            ],
            "unresolved_event_count": len(unresolved),
            "final_active_response": (
                final.active_response if final else False
            ),
            "final_time_expired": (
                final.time_expired if final else False
            ),
            "limitations": (
                "Observed acoustic speaker is distinct from procedurally "
                "recognized speaker.",
                "Pronouns do not identify floor recipients automatically.",
                "Pending questions persist until an explicit later "
                "procedural event changes state.",
                "State is descriptive and assigns no violation, fault, "
                "blame, or sanction.",
            ),
            "status": "warning" if unresolved else "complete",
        },
    )
    return run, report


def validate_procedural_state(run, report, corpus, phase4_corpus):
    _verify_seal(run, "procedural state run")
    _verify_seal(report, "procedural state report")
    if (
        run.discourse_corpus_id != corpus.corpus_id
        or run.discourse_corpus_sha256 != canonical_hash(corpus)
        or run.phase4_utterance_corpus_id != phase4_corpus.corpus_id
        or run.phase4_utterance_corpus_sha256
        != canonical_hash(phase4_corpus)
        or report.procedural_state_run_id != run.procedural_state_run_id
    ):
        raise ProceduralStateIntegrityError(
            "procedural state source lineage or report is stale"
        )
    expected = build_procedural_state(
        corpus,
        phase4_corpus,
        created_at=run.created_at,
        policy=run.policy,
    )
    if expected != (run, report):
        raise ProceduralStateIntegrityError(
            "procedural state does not replay"
        )


def persist_procedural_state(
    run, report, corpus, phase4_corpus, destination: Path
):
    validate_procedural_state(run, report, corpus, phase4_corpus)
    root = destination.expanduser().resolve()
    paths = (
        root / "procedural-state-run.json",
        root / "procedural-state-report.json",
    )
    root.mkdir(parents=True, exist_ok=True)
    existing = tuple(path.exists() for path in paths)
    if any(existing) and not all(existing):
        raise ProceduralStateIntegrityError(
            "persisted procedural state pair is incomplete"
        )
    if all(existing):
        stored = load_procedural_state(root)
        if stored != (run, report):
            raise ProceduralStateIntegrityError(
                "persisted procedural state conflicts"
            )
        return (*paths, True)
    for path, item in zip(paths, (run, report)):
        temporary = path.with_name(
            f"{path.name}.partial-{uuid.uuid4().hex}"
        )
        temporary.write_bytes(canonical_bytes(item))
        os.replace(temporary, path)
    return (*paths, False)


def load_procedural_state(root: Path):
    resolved = root.expanduser().resolve(strict=True)
    run = load_contract(
        (resolved / "procedural-state-run.json").read_bytes(),
        ProceduralStateRun,
    )
    report = load_contract(
        (resolved / "procedural-state-report.json").read_bytes(),
        ProceduralStateReport,
    )
    _verify_seal(run, "procedural state run")
    _verify_seal(report, "procedural state report")
    return run, report
