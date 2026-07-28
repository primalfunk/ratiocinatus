"""Construct structural question artifacts and bounded answer relations."""

from __future__ import annotations

import os
import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from .context_window_contracts import ContextWindowBundle, ContextWindowKind
from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase2_contracts import ConfidenceMeasure, ConfidenceOrigin
from .phase5_contracts import (
    DiscourseAct,
    DiscourseActFamily,
    DiscourseActType,
    DiscourseCorpus,
    DiscourseReviewStatus,
    DiscourseTargetStatus,
    DiscourseTargetType,
)
from .phase5_foundation import validate_discourse_corpus_seal
from .phase5_question_answer_contracts import (
    AddresseeStatus,
    AnswerExplicitness,
    AnswerPolarity,
    AnswerRelation,
    QuestionAnswerPolicy,
    QuestionAnswerReport,
    QuestionAnswerRun,
    QuestionArtifact,
    QuestionDomain,
    QuestionRequestedForm,
)


class QuestionAnswerIntegrityError(RuntimeError):
    """Question-answer artifacts are corrupt, stale, or incompatible."""


_REQUESTED_FORMS = {
    DiscourseActType.INFORMATION_QUESTION: QuestionRequestedForm.INFORMATION,
    DiscourseActType.YES_NO_QUESTION: QuestionRequestedForm.BOOLEAN_DECISION,
    DiscourseActType.ALTERNATIVE_QUESTION:
        QuestionRequestedForm.EXPLICIT_ALTERNATIVE,
    DiscourseActType.CLARIFICATION_QUESTION:
        QuestionRequestedForm.CLARIFICATION,
    DiscourseActType.CONFIRMATION_QUESTION:
        QuestionRequestedForm.CONFIRMATION,
    DiscourseActType.CHALLENGE_QUESTION: QuestionRequestedForm.CHALLENGE,
    DiscourseActType.RHETORICAL_QUESTION:
        QuestionRequestedForm.RHETORICAL_FORM,
    DiscourseActType.FOLLOW_UP_QUESTION: QuestionRequestedForm.FOLLOW_UP,
    DiscourseActType.PROCEDURAL_QUESTION: QuestionRequestedForm.PROCEDURAL,
    DiscourseActType.EMBEDDED_OR_QUOTED_QUESTION:
        QuestionRequestedForm.EMBEDDED_OR_QUOTED,
}
_PRESUPPOSITION_MARKER = re.compile(
    r"\b(?:again|already|still|continue|stop(?:ped)?|resume(?:d)?|why)\b",
    re.IGNORECASE,
)


def _seal(model, payload: dict):
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


def _verify_seal(item, label: str) -> None:
    expected = _seal(
        type(item),
        item.model_dump(mode="python", exclude={"integrity_sha256"}),
    )
    if expected != item:
        raise QuestionAnswerIntegrityError(f"{label} integrity is invalid")


def _question_domain(act: DiscourseAct) -> QuestionDomain:
    if act.act_type == DiscourseActType.PROCEDURAL_QUESTION:
        return QuestionDomain.PROCEDURAL
    if act.act_type == DiscourseActType.EMBEDDED_OR_QUOTED_QUESTION:
        return QuestionDomain.EMBEDDED_OR_QUOTED
    return QuestionDomain.SUBSTANTIVE


def _question_text(act: DiscourseAct) -> str:
    return " ".join(
        dict.fromkeys(
            item.exact_displayed_text for item in act.evidence_spans
        )
    ).strip()


def _alternatives(act: DiscourseAct) -> tuple[str, ...]:
    if act.act_type != DiscourseActType.ALTERNATIVE_QUESTION:
        return ()
    text = _question_text(act).rstrip(" ?")
    parts = tuple(
        item.strip(" ,")
        for item in re.split(r"\s+or\s+", text, flags=re.IGNORECASE)
        if item.strip(" ,")
    )
    return parts if len(parts) >= 2 else ()


def _presupposition_markers(act: DiscourseAct) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            match.group(0)
            for match in _PRESUPPOSITION_MARKER.finditer(
                _question_text(act)
            )
        )
    )


def _question(act: DiscourseAct, created_at: datetime) -> QuestionArtifact:
    requested_form = _REQUESTED_FORMS.get(
        act.act_type, QuestionRequestedForm.UNRESOLVED
    )
    confidence = act.confidence.question_type or act.confidence.act_type
    return _seal(
        QuestionArtifact,
        {
            "question_id": typed_id(
                "question", act.discourse_corpus_id, act.act_id
            ),
            "discourse_corpus_id": act.discourse_corpus_id,
            "source_act_id": act.act_id,
            "utterance_id": act.utterance_id,
            "question_type": act.act_type,
            "question_spans": act.evidence_spans,
            "requested_form": requested_form,
            "requested_information_or_decision": (
                _question_text(act) or None
            ),
            "explicit_alternatives": _alternatives(act),
            "presupposition_markers": _presupposition_markers(act),
            "addressee_status": AddresseeStatus.UNRESOLVED,
            "addressee_ids": (),
            "candidate_addressee_ids": (),
            "domain": _question_domain(act),
            "scope_span_ids": tuple(
                item.span_id for item in act.evidence_spans
            ),
            "confidence": confidence,
            "review_status": (
                DiscourseReviewStatus.REVIEW_REQUIRED
                if _presupposition_markers(act)
                or requested_form == QuestionRequestedForm.UNRESOLVED
                else act.review_status
            ),
            "created_at": created_at,
        },
    )


def _explicitness(act_type: DiscourseActType) -> AnswerExplicitness:
    if act_type == DiscourseActType.PARTIAL_ANSWER:
        return AnswerExplicitness.PARTIAL
    if act_type == DiscourseActType.QUALIFIED_ANSWER:
        return AnswerExplicitness.QUALIFIED
    if act_type == DiscourseActType.INDIRECT_ANSWER:
        return AnswerExplicitness.INDIRECT
    if act_type == DiscourseActType.UNRESOLVED_TARGET_ANSWER:
        return AnswerExplicitness.UNRESOLVED
    return AnswerExplicitness.EXPLICIT


def _polarity(act_type: DiscourseActType) -> AnswerPolarity:
    if act_type == DiscourseActType.AFFIRMATIVE_ANSWER:
        return AnswerPolarity.AFFIRMATIVE
    if act_type == DiscourseActType.NEGATIVE_ANSWER:
        return AnswerPolarity.NEGATIVE
    if act_type in {
        DiscourseActType.ANSWER_BY_CORRECTION,
        DiscourseActType.ANSWER_BY_REJECTION_OF_PREMISE,
    }:
        return AnswerPolarity.MIXED
    if act_type in {
        DiscourseActType.ANSWER_DEFERRED,
        DiscourseActType.REFUSAL_TO_ANSWER,
        DiscourseActType.INABILITY_TO_ANSWER,
    }:
        return AnswerPolarity.NOT_APPLICABLE
    return AnswerPolarity.UNRESOLVED


def _window(bundle: ContextWindowBundle, utterance_id: str):
    return next(
        (
            item
            for item in bundle.windows
            if item.target_utterance_id == utterance_id
            and item.kind == ContextWindowKind.BOUNDED_TEMPORAL
        ),
        None,
    )


def _temporal_candidates(
    act: DiscourseAct,
    questions: tuple[QuestionArtifact, ...],
    bundle: ContextWindowBundle,
    policy: QuestionAnswerPolicy,
) -> tuple[tuple[QuestionArtifact, ...], str | None]:
    window = _window(bundle, act.utterance_id)
    if window is None:
        return (), None
    positions = {
        item.utterance_id: item.order_position for item in window.members
    }
    answer_position = positions.get(act.utterance_id)
    if answer_position is None:
        return (), window.context_window_id
    candidates = [
        item
        for item in questions
        if item.utterance_id in positions
        and positions[item.utterance_id] < answer_position
    ]
    candidates.sort(
        key=lambda item: (
            -positions[item.utterance_id],
            item.question_id,
        )
    )
    return (
        tuple(candidates[: policy.maximum_previous_question_candidates]),
        window.context_window_id,
    )


def _explicit_targets(
    act: DiscourseAct,
    questions: tuple[QuestionArtifact, ...],
) -> tuple[tuple[str, ...], tuple[str, ...], bool]:
    by_question = {item.question_id: item for item in questions}
    by_act = {item.source_act_id: item for item in questions}
    by_utterance = defaultdict(list)
    for item in questions:
        by_utterance[item.utterance_id].append(item)
    targets, alternatives = [], []
    explicit = False
    for proposal in act.relation_targets:
        resolved = []
        for identifier in (
            *((proposal.target_id,) if proposal.target_id else ()),
            *proposal.alternative_target_ids,
        ):
            if proposal.target_type == DiscourseTargetType.QUESTION:
                question = by_question.get(identifier)
                resolved.extend((question,) if question else ())
            elif proposal.target_type == DiscourseTargetType.DISCOURSE_ACT:
                question = by_act.get(identifier)
                resolved.extend((question,) if question else ())
            elif proposal.target_type == DiscourseTargetType.UTTERANCE:
                resolved.extend(by_utterance.get(identifier, ()))
        if resolved:
            explicit = True
        ids = [item.question_id for item in resolved]
        if proposal.target_status in {
            DiscourseTargetStatus.IDENTIFIED,
            DiscourseTargetStatus.PROBABLE,
        }:
            targets.extend(ids)
        else:
            alternatives.extend(ids)
    return (
        tuple(dict.fromkeys(targets)),
        tuple(
            item
            for item in dict.fromkeys(alternatives)
            if item not in targets
        ),
        explicit,
    )


def _distance(
    answer: DiscourseAct,
    question_ids: tuple[str, ...],
    by_question: dict[str, QuestionArtifact],
) -> int | None:
    if not question_ids:
        return None
    answer_start = min(
        item.source_interval.start_microseconds
        for item in answer.evidence_spans
    )
    question_end = max(
        span.source_interval.start_microseconds
        + span.source_interval.duration_microseconds
        for question_id in question_ids
        for span in by_question[question_id].question_spans
    )
    return answer_start - question_end


def _relation_payload(
    act: DiscourseAct,
    questions: tuple[QuestionArtifact, ...],
    qualification_ids: tuple[str, ...],
    bundle: ContextWindowBundle,
    policy: QuestionAnswerPolicy,
    created_at: datetime,
) -> dict:
    targets, alternatives, explicit = _explicit_targets(act, questions)
    temporal, context_window_id = _temporal_candidates(
        act, questions, bundle, policy
    )
    basis = []
    if explicit:
        status = (
            DiscourseTargetStatus.IDENTIFIED
            if targets
            else DiscourseTargetStatus.MULTIPLE_CANDIDATES
        )
        basis.append("explicit normalized relation target")
    elif act.act_type == DiscourseActType.UNRESOLVED_TARGET_ANSWER:
        status = DiscourseTargetStatus.UNRESOLVED
        alternatives = tuple(item.question_id for item in temporal)
        targets = ()
        basis.append("answer type explicitly preserves unresolved target")
    elif len(temporal) == 1:
        status = DiscourseTargetStatus.PROBABLE
        targets = (temporal[0].question_id,)
        basis.append("single preceding question in bounded temporal context")
    elif len(temporal) > 1:
        status = DiscourseTargetStatus.MULTIPLE_CANDIDATES
        alternatives = tuple(item.question_id for item in temporal)
        basis.append(
            "multiple preceding questions in bounded temporal context"
        )
    else:
        status = DiscourseTargetStatus.UNRESOLVED
        basis.append("no supported question target in bounded context")
    if status == DiscourseTargetStatus.IDENTIFIED:
        confidence = act.confidence.answer_link or ConfidenceMeasure(
            value=0.9,
            origin=ConfidenceOrigin.DERIVED,
            basis="uncalibrated explicit target-link strength",
            calibrated=False,
        )
    elif status == DiscourseTargetStatus.PROBABLE:
        confidence = ConfidenceMeasure(
            value=0.7,
            origin=ConfidenceOrigin.DERIVED,
            basis="uncalibrated single bounded temporal candidate",
            calibrated=False,
        )
    elif status == DiscourseTargetStatus.MULTIPLE_CANDIDATES:
        confidence = ConfidenceMeasure(
            value=0.5,
            origin=ConfidenceOrigin.DERIVED,
            basis="uncalibrated ambiguous bounded target set",
            calibrated=False,
        )
    else:
        confidence = ConfidenceMeasure(
            value=None,
            origin=ConfidenceOrigin.UNAVAILABLE,
            basis="no answer target is selected",
            calibrated=False,
        )
    by_question = {item.question_id: item for item in questions}
    return {
        "answer_relation_id": typed_id(
            "answerrelation",
            act.discourse_corpus_id,
            act.act_id,
            targets,
            alternatives,
        ),
        "discourse_corpus_id": act.discourse_corpus_id,
        "answer_act_id": act.act_id,
        "answer_utterance_id": act.utterance_id,
        "target_status": status,
        "target_question_ids": targets,
        "alternative_question_ids": alternatives,
        "answer_form": act.act_type,
        "explicitness": _explicitness(act.act_type),
        "polarity": _polarity(act.act_type),
        "qualification_act_ids": qualification_ids,
        "rejects_presupposition": (
            act.act_type
            == DiscourseActType.ANSWER_BY_REJECTION_OF_PREMISE
        ),
        "deferred": act.act_type == DiscourseActType.ANSWER_DEFERRED,
        "refused": act.act_type == DiscourseActType.REFUSAL_TO_ANSWER,
        "inability": act.act_type == DiscourseActType.INABILITY_TO_ANSWER,
        "co_answer_act_ids": (),
        "evidence_span_ids": tuple(
            item.span_id for item in act.evidence_spans
        ),
        "context_window_id": context_window_id,
        "temporal_distance_microseconds": _distance(
            act, targets or alternatives, by_question
        ),
        "confidence": confidence,
        "review_status": (
            act.review_status
            if status == DiscourseTargetStatus.IDENTIFIED
            else DiscourseReviewStatus.REVIEW_REQUIRED
        ),
        "basis": tuple(basis),
        "created_at": created_at,
    }


def build_question_answers(
    corpus: DiscourseCorpus,
    context: ContextWindowBundle,
    *,
    created_at: datetime,
    policy: QuestionAnswerPolicy | None = None,
) -> tuple[QuestionAnswerRun, QuestionAnswerReport]:
    """Construct structural question and answer artifacts without adequacy."""
    validate_discourse_corpus_seal(corpus)
    if context.utterance_corpus_id != corpus.phase4_utterance_corpus_id:
        raise QuestionAnswerIntegrityError(
            "context bundle uses incompatible Phase 4 lineage"
        )
    policy = policy or QuestionAnswerPolicy()
    questions = tuple(
        _question(item, created_at)
        for item in corpus.selected_acts
        if item.act_family == DiscourseActFamily.QUESTION
    )
    qualification_by_utterance = defaultdict(list)
    for item in corpus.selected_acts:
        if item.act_family == DiscourseActFamily.QUALIFICATION:
            qualification_by_utterance[item.utterance_id].append(item.act_id)
    payloads = [
        _relation_payload(
            item,
            questions,
            tuple(qualification_by_utterance[item.utterance_id]),
            context,
            policy,
            created_at,
        )
        for item in corpus.selected_acts
        if item.act_family == DiscourseActFamily.ANSWER
    ]
    co_answers = defaultdict(set)
    for payload in payloads:
        for question_id in payload["target_question_ids"]:
            co_answers[question_id].add(payload["answer_act_id"])
    relations = []
    for payload in payloads:
        peers = set()
        for question_id in payload["target_question_ids"]:
            peers.update(co_answers[question_id])
        peers.discard(payload["answer_act_id"])
        payload["co_answer_act_ids"] = tuple(sorted(peers))
        relations.append(_seal(AnswerRelation, payload))
    unlinked = tuple(
        item.answer_act_id
        for item in relations
        if item.target_status
        in {
            DiscourseTargetStatus.IMPLICIT,
            DiscourseTargetStatus.UNRESOLVED,
        }
    )
    configuration_hash = canonical_hash(
        {
            "operation": "discourse.question_answer_construction",
            "discourse_corpus_sha256": canonical_hash(corpus),
            "context_bundle_sha256": canonical_hash(context),
            "policy": policy.model_dump(mode="json"),
        }
    )
    run_id = typed_id(
        "questionanswerrun", corpus.corpus_id, configuration_hash
    )
    run = _seal(
        QuestionAnswerRun,
        {
            "question_answer_run_id": run_id,
            "discourse_corpus_id": corpus.corpus_id,
            "discourse_corpus_sha256": canonical_hash(corpus),
            "context_bundle_id": context.context_bundle_id,
            "context_bundle_sha256": canonical_hash(context),
            "policy": policy,
            "configuration_hash": configuration_hash,
            "questions": questions,
            "answer_relations": tuple(relations),
            "unlinked_answer_act_ids": unlinked,
            "created_at": created_at,
            "complete": True,
        },
    )
    statuses = Counter(item.target_status for item in relations)
    target_answers = defaultdict(set)
    for item in relations:
        for question_id in item.target_question_ids:
            target_answers[question_id].add(item.answer_act_id)
    report = _seal(
        QuestionAnswerReport,
        {
            "report_id": typed_id("questionanswerreport", run_id),
            "question_answer_run_id": run_id,
            "generated_at": created_at,
            "question_count": len(questions),
            "procedural_question_count": sum(
                item.domain == QuestionDomain.PROCEDURAL
                for item in questions
            ),
            "substantive_question_count": sum(
                item.domain == QuestionDomain.SUBSTANTIVE
                for item in questions
            ),
            "answer_relation_count": len(relations),
            "identified_answer_count": statuses[
                DiscourseTargetStatus.IDENTIFIED
            ],
            "probable_answer_count": statuses[
                DiscourseTargetStatus.PROBABLE
            ],
            "ambiguous_answer_count": statuses[
                DiscourseTargetStatus.MULTIPLE_CANDIDATES
            ],
            "unresolved_answer_count": statuses[
                DiscourseTargetStatus.UNRESOLVED
            ],
            "deferred_answer_count": sum(item.deferred for item in relations),
            "refused_answer_count": sum(item.refused for item in relations),
            "inability_answer_count": sum(
                item.inability for item in relations
            ),
            "premise_rejection_count": sum(
                item.rejects_presupposition for item in relations
            ),
            "multi_question_answer_count": sum(
                len(item.target_question_ids) > 1 for item in relations
            ),
            "jointly_answered_question_count": sum(
                len(answer_ids) > 1
                for answer_ids in target_answers.values()
            ),
            "limitations": (
                "Temporal proximity creates a reviewable candidate link, "
                "not a responsiveness or adequacy judgment.",
                "Addressees remain unresolved without explicit evidence.",
                "Surface presupposition markers do not establish that a "
                "question is loaded, unfair, misleading, or unanswerable.",
                "No adequacy, completeness, or evasion score is produced.",
            ),
            "status": (
                "warning"
                if unlinked
                or statuses[DiscourseTargetStatus.MULTIPLE_CANDIDATES]
                else "complete"
            ),
        },
    )
    return run, report


def validate_question_answers(
    run: QuestionAnswerRun,
    report: QuestionAnswerReport,
    corpus: DiscourseCorpus,
    context: ContextWindowBundle,
) -> None:
    _verify_seal(run, "question-answer run")
    _verify_seal(report, "question-answer report")
    if (
        run.discourse_corpus_id != corpus.corpus_id
        or run.discourse_corpus_sha256 != canonical_hash(corpus)
        or run.context_bundle_id != context.context_bundle_id
        or run.context_bundle_sha256 != canonical_hash(context)
        or report.question_answer_run_id != run.question_answer_run_id
    ):
        raise QuestionAnswerIntegrityError(
            "question-answer source lineage or report is stale"
        )
    acts = {item.act_id: item for item in corpus.selected_acts}
    questions = {item.question_id: item for item in run.questions}
    if any(
        item.source_act_id not in acts
        or acts[item.source_act_id].act_family
        != DiscourseActFamily.QUESTION
        or acts[item.source_act_id].evidence_spans != item.question_spans
        for item in run.questions
    ):
        raise QuestionAnswerIntegrityError(
            "question artifact does not match its canonical source act"
        )
    if any(
        item.answer_act_id not in acts
        or acts[item.answer_act_id].act_family != DiscourseActFamily.ANSWER
        or not (
            set(item.target_question_ids)
            | set(item.alternative_question_ids)
        ).issubset(questions)
        for item in run.answer_relations
    ):
        raise QuestionAnswerIntegrityError(
            "answer relation does not match canonical evidence"
        )
    expected = build_question_answers(
        corpus, context, created_at=run.created_at, policy=run.policy
    )
    if expected != (run, report):
        raise QuestionAnswerIntegrityError(
            "question-answer construction does not replay"
        )


def persist_question_answers(
    run: QuestionAnswerRun,
    report: QuestionAnswerReport,
    corpus: DiscourseCorpus,
    context: ContextWindowBundle,
    destination: Path,
) -> tuple[Path, Path, bool]:
    validate_question_answers(run, report, corpus, context)
    root = destination.expanduser().resolve()
    paths = (
        root / "question-answer-run.json",
        root / "question-answer-report.json",
    )
    root.mkdir(parents=True, exist_ok=True)
    existing = tuple(path.exists() for path in paths)
    if any(existing) and not all(existing):
        raise QuestionAnswerIntegrityError(
            "persisted question-answer pair is incomplete"
        )
    if all(existing):
        stored = load_question_answers(root)
        if stored != (run, report):
            raise QuestionAnswerIntegrityError(
                "persisted question-answer artifacts conflict"
            )
        return (*paths, True)
    for path, item in zip(paths, (run, report)):
        temporary = path.with_name(
            f"{path.name}.partial-{uuid.uuid4().hex}"
        )
        temporary.write_bytes(canonical_bytes(item))
        os.replace(temporary, path)
    return (*paths, False)


def load_question_answers(
    root: Path,
) -> tuple[QuestionAnswerRun, QuestionAnswerReport]:
    resolved = root.expanduser().resolve(strict=True)
    run = load_contract(
        (resolved / "question-answer-run.json").read_bytes(),
        QuestionAnswerRun,
    )
    report = load_contract(
        (resolved / "question-answer-report.json").read_bytes(),
        QuestionAnswerReport,
    )
    _verify_seal(run, "question-answer run")
    _verify_seal(report, "question-answer report")
    return run, report
