"""Controlled, source-grounded Phase 5 discourse evaluation."""

from __future__ import annotations

import os
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from .discourse_review import (
    validate_discourse_propagation,
    validate_discourse_review_ledger,
)
from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase4_contracts import UtteranceCorpus
from .phase5_contracts import (
    DiscourseActFamily,
    DiscourseActType,
    DiscourseCorpus,
)
from .phase5_evaluation_contracts import (
    Phase5ControlledReference,
    Phase5DiscourseEvaluation,
    Phase5EvaluationMetric,
    Phase5EvaluationMetricKind,
    Phase5EvaluationMetricStatus,
    Phase5EvaluationPolicy,
    Phase5EvaluationReport,
    Phase5EvaluationStratum,
    Phase5StratumEvaluation,
)
from .phase5_foundation import validate_discourse_corpus
from .phase5_review_contracts import (
    DiscoursePropagationReport,
    DiscoursePropagationRun,
    DiscourseReviewLedger,
)


class Phase5EvaluationIntegrityError(RuntimeError):
    """Controlled evaluation evidence is corrupt or incompatible."""


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
        raise Phase5EvaluationIntegrityError(f"{label} integrity is invalid")


def _metric(kind, numerator, denominator, basis, evidence, *, value=None):
    if denominator == 0:
        return Phase5EvaluationMetric(
            kind=kind,
            status=Phase5EvaluationMetricStatus.NOT_APPLICABLE,
            numerator=0,
            denominator=0,
            value=None,
            basis=f"{basis} No eligible controlled reference was present.",
            evidence_references=(),
        )
    return Phase5EvaluationMetric(
        kind=kind,
        status=Phase5EvaluationMetricStatus.MEASURED,
        numerator=numerator,
        denominator=denominator,
        value=numerator / denominator if value is None else value,
        basis=basis,
        evidence_references=evidence,
    )


def _prf(kinds, reference, system, evidence):
    common = sum((reference & system).values())
    precision = common / sum(system.values()) if system else None
    recall = common / sum(reference.values()) if reference else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else 0.0
    )
    label = "family" if "FAMILY" in kinds[0].name else "type"
    return (
        _metric(
            kinds[0],
            common,
            sum(system.values()),
            f"Micro {label} precision over utterance-owned labels.",
            evidence,
        ),
        _metric(
            kinds[1],
            common,
            sum(reference.values()),
            f"Micro {label} recall over utterance-owned labels.",
            evidence,
        ),
        _metric(
            kinds[2],
            common,
            1 if reference or system else 0,
            f"Harmonic mean of micro {label} precision and recall.",
            evidence,
            value=f1,
        ),
    )


def _iou(left, right) -> float:
    overlap = max(
        0,
        min(left.end_text_offset, right.end_text_offset)
        - max(left.start_text_offset, right.start_text_offset),
    )
    union = max(left.end_text_offset, right.end_text_offset) - min(
        left.start_text_offset, right.start_text_offset
    )
    return overlap / union if union else 0.0


def _span_pairs(reference_spans, system_spans, threshold):
    candidates = sorted(
        (
            (_iou(ref, system), ref.reference_span_id, system.span_id, ref, system)
            for ref in reference_spans
            for system in system_spans
            if ref.utterance_id == system.utterance_id
        ),
        reverse=True,
    )
    matched_ref, matched_system, pairs = set(), set(), []
    for score, ref_id, system_id, ref, system in candidates:
        if (
            score >= threshold
            and ref_id not in matched_ref
            and system_id not in matched_system
        ):
            matched_ref.add(ref_id)
            matched_system.add(system_id)
            pairs.append((score, ref, system))
    return tuple(pairs)


def _targets(act) -> frozenset[str]:
    return frozenset(
        value
        for proposal in act.relation_targets
        for value in (
            *((proposal.target_id,) if proposal.target_id else ()),
            *proposal.alternative_target_ids,
        )
    )


def evaluate_phase5(
    corpus: DiscourseCorpus,
    phase4_corpus: UtteranceCorpus,
    reference: Phase5ControlledReference,
    *,
    propagation: tuple[
        DiscoursePropagationRun, DiscoursePropagationReport
    ]
    | None = None,
    review_ledger: DiscourseReviewLedger | None = None,
    policy: Phase5EvaluationPolicy | None = None,
    generated_at: datetime | None = None,
) -> tuple[Phase5DiscourseEvaluation, Phase5EvaluationReport]:
    """Evaluate machine discourse evidence against a controlled reference."""
    integrity = validate_discourse_corpus(
        corpus, phase4_corpus, checked_at=generated_at or corpus.created_at
    )
    if not integrity.valid:
        raise Phase5EvaluationIntegrityError(
            "discourse corpus failed source validation"
        )
    _verify(reference, "Phase 5 controlled reference")
    for item in reference.acts:
        _verify(item, item.reference_act_id)
    if reference.phase4_utterance_corpus_id != phase4_corpus.corpus_id:
        raise Phase5EvaluationIntegrityError(
            "controlled reference uses another Phase 4 corpus"
        )
    policy = policy or Phase5EvaluationPolicy()
    if (
        not reference.independent_of_system_output
        and reference.evidence_class != "synthetic_mechanics"
    ):
        raise Phase5EvaluationIntegrityError(
            "controlled reference preparation is not independent"
        )
    if review_ledger is not None:
        validate_discourse_review_ledger(review_ledger, corpus)
    if propagation is not None:
        run, propagation_report = propagation
        _verify(run, "discourse propagation run")
        _verify(propagation_report, "discourse propagation report")
        if run.predecessor_discourse_corpus_id != corpus.corpus_id:
            raise Phase5EvaluationIntegrityError(
                "propagation uses another discourse corpus"
            )
    evidence = (reference.reference_id, corpus.corpus_id)
    reference_family = Counter(
        (item.utterance_id, item.act_family) for item in reference.acts
    )
    system_family = Counter(
        (item.utterance_id, item.act_family) for item in corpus.selected_acts
    )
    reference_type = Counter(
        (item.utterance_id, item.act_type) for item in reference.acts
    )
    system_type = Counter(
        (item.utterance_id, item.act_type) for item in corpus.selected_acts
    )
    metrics = [
        *_prf(
            (
                Phase5EvaluationMetricKind.ACT_FAMILY_PRECISION,
                Phase5EvaluationMetricKind.ACT_FAMILY_RECALL,
                Phase5EvaluationMetricKind.ACT_FAMILY_F1,
            ),
            reference_family,
            system_family,
            evidence,
        ),
        *_prf(
            (
                Phase5EvaluationMetricKind.ACT_TYPE_PRECISION,
                Phase5EvaluationMetricKind.ACT_TYPE_RECALL,
                Phase5EvaluationMetricKind.ACT_TYPE_F1,
            ),
            reference_type,
            system_type,
            evidence,
        ),
    ]
    reference_by_utterance = defaultdict(set)
    system_by_utterance = defaultdict(set)
    for item in reference.acts:
        reference_by_utterance[item.utterance_id].add(item.act_type)
    for item in corpus.selected_acts:
        system_by_utterance[item.utterance_id].add(item.act_type)
    utterance_ids = sorted(
        set(reference_by_utterance) | set(system_by_utterance)
    )
    exact = sum(
        reference_by_utterance[item] == system_by_utterance[item]
        for item in utterance_ids
    )
    partial_values = []
    for item in utterance_ids:
        union = reference_by_utterance[item] | system_by_utterance[item]
        partial_values.append(
            len(reference_by_utterance[item] & system_by_utterance[item])
            / len(union)
            if union
            else 1.0
        )
    metrics.extend(
        (
            _metric(
                Phase5EvaluationMetricKind.MULTI_LABEL_EXACT_MATCH,
                exact,
                len(utterance_ids),
                "Exact compatible-label set agreement per utterance.",
                evidence,
            ),
            _metric(
                Phase5EvaluationMetricKind.MULTI_LABEL_PARTIAL_MATCH,
                sum(partial_values),
                len(partial_values),
                "Mean Jaccard overlap of label sets per utterance.",
                evidence,
            ),
        )
    )
    reference_spans = tuple(
        span for item in reference.acts for span in item.evidence_spans
    )
    system_spans = tuple(
        span for item in corpus.selected_acts for span in item.evidence_spans
    )
    pairs = _span_pairs(
        reference_spans, system_spans, policy.minimum_span_iou
    )
    metrics.extend(
        (
            _metric(
                Phase5EvaluationMetricKind.EVIDENCE_SPAN_PRECISION,
                len(pairs),
                len(system_spans),
                "One-to-one span IoU at or above the policy threshold.",
                evidence,
            ),
            _metric(
                Phase5EvaluationMetricKind.EVIDENCE_SPAN_RECALL,
                len(pairs),
                len(reference_spans),
                "One-to-one span IoU at or above the policy threshold.",
                evidence,
            ),
            _metric(
                Phase5EvaluationMetricKind.EVIDENCE_SPAN_OVERLAP,
                sum(item[0] for item in pairs),
                len(pairs),
                "Mean IoU over threshold-matched evidence spans.",
                evidence,
            ),
        )
    )
    system_exact = defaultdict(list)
    for item in corpus.selected_acts:
        system_exact[(item.utterance_id, item.act_type)].append(item)

    def eligible(families):
        return tuple(
            item for item in reference.acts if item.act_family in families
        )

    def type_accuracy(kind, families, basis):
        selected = eligible(families)
        correct = sum(
            bool(system_exact.get((item.utterance_id, item.act_type)))
            for item in selected
        )
        return _metric(kind, correct, len(selected), basis, evidence)

    def target_accuracy(kind, families, basis):
        selected = tuple(
            item for item in eligible(families) if item.target_ids
        )
        correct = 0
        for item in selected:
            predicted = frozenset(
                value
                for act in system_exact.get(
                    (item.utterance_id, item.act_type), ()
                )
                for value in _targets(act)
            )
            correct += predicted == frozenset(item.target_ids)
        return _metric(kind, correct, len(selected), basis, evidence)

    target_eligible = tuple(item for item in reference.acts if item.target_ids)
    target_correct = 0
    for item in target_eligible:
        predicted = frozenset(
            value
            for act in system_exact.get(
                (item.utterance_id, item.act_type), ()
            )
            for value in _targets(act)
        )
        target_correct += predicted == frozenset(item.target_ids)
    metrics.extend(
        (
            _metric(
                Phase5EvaluationMetricKind.RELATION_TARGET_ACCURACY,
                target_correct,
                len(target_eligible),
                "Exact target-set agreement for reference-targeted acts.",
                evidence,
            ),
            type_accuracy(
                Phase5EvaluationMetricKind.QUESTION_TYPE_ACCURACY,
                {DiscourseActFamily.QUESTION},
                "Exact question-type agreement.",
            ),
            target_accuracy(
                Phase5EvaluationMetricKind.ANSWER_LINK_ACCURACY,
                {DiscourseActFamily.ANSWER},
                "Exact answer-to-question target agreement.",
            ),
            target_accuracy(
                Phase5EvaluationMetricKind.OBJECTION_TARGET_ACCURACY,
                {DiscourseActFamily.OBJECTION},
                "Exact objection-target agreement.",
            ),
            target_accuracy(
                Phase5EvaluationMetricKind.REBUTTAL_TARGET_ACCURACY,
                {DiscourseActFamily.REBUTTAL},
                "Exact rebuttal-target agreement.",
            ),
            type_accuracy(
                Phase5EvaluationMetricKind.CONCESSION_SCOPE_ACCURACY,
                {DiscourseActFamily.CONCESSION},
                "Source-grounded concession type and scope presence.",
            ),
            type_accuracy(
                Phase5EvaluationMetricKind.QUALIFICATION_SCOPE_ACCURACY,
                {DiscourseActFamily.QUALIFICATION},
                "Source-grounded qualification type and scope presence.",
            ),
            type_accuracy(
                Phase5EvaluationMetricKind.DEFINITION_SPAN_ACCURACY,
                {DiscourseActFamily.DEFINITION},
                "Source-grounded definition type and defining span presence.",
            ),
            target_accuracy(
                Phase5EvaluationMetricKind.EXAMPLE_TARGET_ACCURACY,
                {DiscourseActFamily.EXAMPLE},
                "Exact example-to-generalization target agreement.",
            ),
            type_accuracy(
                Phase5EvaluationMetricKind.QUOTATION_USE_ACCURACY,
                {DiscourseActFamily.QUOTATION},
                "Exact quotation-use type agreement.",
            ),
            type_accuracy(
                Phase5EvaluationMetricKind.PROCEDURAL_ACT_ACCURACY,
                {DiscourseActFamily.PROCEDURAL},
                "Exact procedural-act type agreement.",
            ),
        )
    )
    candidates = {
        item.utterance_id: {
            candidate.act_type
            for candidate_set in corpus.candidate_sets
            if candidate_set.utterance_id == item.utterance_id
            for candidate in candidate_set.candidates
        }
        for item in reference.acts
    }
    alternatives = [
        (item, alternative)
        for item in reference.acts
        for alternative in item.alternative_act_types
    ]
    metrics.append(
        _metric(
            Phase5EvaluationMetricKind.ALTERNATIVE_CANDIDATE_RECALL,
            sum(
                alternative in candidates.get(item.utterance_id, set())
                for item, alternative in alternatives
            ),
            len(alternatives),
            "Declared alternative act types retained in candidate sets.",
            evidence,
        )
    )
    confidence_values = []
    for act in corpus.selected_acts:
        value = act.confidence.selection.value
        if value is not None:
            correct = (
                (act.utterance_id, act.act_type) in reference_type
            )
            confidence_values.append(1.0 - abs(value - float(correct)))
    metrics.append(
        _metric(
            Phase5EvaluationMetricKind.CONFIDENCE_RELIABILITY,
            sum(confidence_values),
            len(confidence_values),
            "One minus mean absolute confidence error; uncalibrated scores "
            "remain disclosed as ranking aids.",
            evidence,
        )
    )
    unknown = tuple(
        item
        for item in reference.acts
        if item.act_family == DiscourseActFamily.UNKNOWN
    )
    metrics.append(
        _metric(
            Phase5EvaluationMetricKind.UNKNOWN_STATE_APPROPRIATENESS,
            sum(
                bool(system_exact.get((item.utterance_id, item.act_type)))
                for item in unknown
            ),
            len(unknown),
            "Unknown reference outcomes remain unknown.",
            evidence,
        )
    )
    if propagation is None:
        metrics.extend(
            (
                _metric(
                    Phase5EvaluationMetricKind.CORRECTION_PROPAGATION_COMPLETENESS,
                    0,
                    0,
                    "Affected reference acts require a propagation run.",
                    (),
                ),
                _metric(
                    Phase5EvaluationMetricKind.UNAFFECTED_ARTIFACT_STABILITY,
                    0,
                    0,
                    "Unaffected stability requires a propagation run.",
                    (),
                ),
            )
        )
    else:
        run, _ = propagation
        expected_affected = {
            item.utterance_id
            for item in reference.acts
            if Phase5EvaluationStratum.CORRECTION_AFFECTED in item.strata
        }
        observed_affected = {
            utterance_id
            for impact in run.impacts
            for utterance_id in impact.predecessor_utterance_ids
            if impact.invalidated_act_ids
        }
        metrics.extend(
            (
                _metric(
                    Phase5EvaluationMetricKind.CORRECTION_PROPAGATION_COMPLETENESS,
                    len(expected_affected & observed_affected),
                    len(expected_affected),
                    "Reference-affected utterances appear in invalidating impacts.",
                    evidence,
                ),
                _metric(
                    Phase5EvaluationMetricKind.UNAFFECTED_ARTIFACT_STABILITY,
                    len(run.preserved_act_ids),
                    len(corpus.selected_acts) - len(run.invalidated_act_ids),
                    "Non-invalidated act identifiers remain preserved.",
                    evidence,
                ),
            )
        )
    if review_ledger is None:
        metrics.append(
            _metric(
                Phase5EvaluationMetricKind.HUMAN_REVIEW_IMPACT,
                0,
                0,
                "Human-review impact requires a review ledger.",
                (),
            )
        )
    else:
        metrics.append(
            _metric(
                Phase5EvaluationMetricKind.HUMAN_REVIEW_IMPACT,
                sum(
                    item.action.value != "defer_decision"
                    for item in review_ledger.actions
                ),
                len(review_ledger.actions),
                "Fraction of review actions proposing a non-deferred change.",
                (reference.reference_id, review_ledger.ledger_id),
            )
        )
    strata = []
    for stratum in Phase5EvaluationStratum:
        selected = tuple(
            item for item in reference.acts if stratum in item.strata
        )
        if not selected:
            continue
        system_count = sum(
            len(
                [
                    act
                    for act in corpus.selected_acts
                    if act.utterance_id == item.utterance_id
                ]
            )
            for item in selected
        )
        exact_count = sum(
            bool(system_exact.get((item.utterance_id, item.act_type)))
            for item in selected
        )
        strata.append(
            Phase5StratumEvaluation(
                stratum=stratum,
                reference_act_count=len(selected),
                system_act_count=system_count,
                exact_type_match_count=exact_count,
            )
        )
    timestamp = generated_at or corpus.created_at
    evaluation = _seal(
        Phase5DiscourseEvaluation,
        {
            "evaluation_id": typed_id(
                "phase5evaluation",
                corpus.corpus_id,
                reference.reference_id,
                policy.model_dump(mode="json"),
                (
                    propagation[0].propagation_run_id
                    if propagation is not None
                    else None
                ),
                review_ledger.ledger_id if review_ledger else None,
            ),
            "discourse_corpus_id": corpus.corpus_id,
            "controlled_reference_id": reference.reference_id,
            "policy": policy,
            "metrics": tuple(metrics),
            "strata": tuple(strata),
            "generated_at": timestamp,
            "evidence_class": (
                "synthetic_mechanics"
                if reference.evidence_class == "synthetic_mechanics"
                else "measured_evaluation"
            ),
            "limitations": (
                "Conversational-function labels do not establish truth, "
                "adequacy, argumentative success, intent, or participant merit.",
                "Synthetic mechanics evidence is not natural-conversation "
                "performance evidence.",
                "Confidence reliability evaluates disclosed uncalibrated "
                "ranking scores and is not probability calibration.",
            ),
        },
    )
    measured = sum(
        item.status == Phase5EvaluationMetricStatus.MEASURED
        for item in metrics
    )
    report = _seal(
        Phase5EvaluationReport,
        {
            "report_id": typed_id(
                "phase5evaluationreport", evaluation.evaluation_id
            ),
            "evaluation_id": evaluation.evaluation_id,
            "generated_at": timestamp,
            "reference_act_count": len(reference.acts),
            "system_act_count": len(corpus.selected_acts),
            "measured_metric_count": measured,
            "not_applicable_metric_count": len(metrics) - measured,
            "status": "complete",
        },
    )
    return evaluation, report


def validate_phase5_evaluation(
    evaluation,
    report,
    corpus,
    phase4_corpus,
    reference,
):
    integrity = validate_discourse_corpus(
        corpus, phase4_corpus, checked_at=evaluation.generated_at
    )
    if not integrity.valid:
        raise Phase5EvaluationIntegrityError(
            "discourse corpus failed source validation"
        )
    _verify(evaluation, "Phase 5 discourse evaluation")
    _verify(report, "Phase 5 evaluation report")
    _verify(reference, "Phase 5 controlled reference")
    for item in reference.acts:
        _verify(item, item.reference_act_id)
    if (
        evaluation.discourse_corpus_id != corpus.corpus_id
        or evaluation.controlled_reference_id != reference.reference_id
        or report.evaluation_id != evaluation.evaluation_id
    ):
        raise Phase5EvaluationIntegrityError(
            "evaluation sources are incompatible"
        )


def persist_phase5_evaluation(
    evaluation,
    report,
    corpus,
    phase4_corpus,
    reference,
    destination,
):
    validate_phase5_evaluation(
        evaluation, report, corpus, phase4_corpus, reference
    )
    root = (
        destination.expanduser().resolve()
        / "phase5-evaluation"
        / evaluation.evaluation_id
    )
    evaluation_path = root / "evaluation.json"
    report_path = root / "report.json"
    if evaluation_path.exists() and report_path.exists():
        stored = load_phase5_evaluation(root)
        if stored != (evaluation, report):
            raise Phase5EvaluationIntegrityError(
                "cached evaluation is incompatible"
            )
        return evaluation, report, root, True
    _atomic(evaluation_path, canonical_bytes(evaluation))
    _atomic(report_path, canonical_bytes(report))
    return evaluation, report, root, False


def load_phase5_evaluation(root: Path):
    resolved = root.expanduser().resolve(strict=True)
    evaluation = load_contract(
        (resolved / "evaluation.json").read_bytes(),
        Phase5DiscourseEvaluation,
    )
    report = load_contract(
        (resolved / "report.json").read_bytes(), Phase5EvaluationReport
    )
    return evaluation, report


def load_phase5_reference(path: Path):
    return load_contract(
        path.expanduser().resolve(strict=True).read_bytes(),
        Phase5ControlledReference,
    )
