"""Controlled, source-addressed Phase 4 utterance evaluation."""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from itertools import combinations
from pathlib import Path

from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase4_contracts import (
    Utterance,
    UtteranceCompletenessClassification,
    UtteranceOverlapStatus,
    UtteranceTextKind,
)
from .phase4_evaluation_contracts import (
    EvaluationMetricStatus,
    Phase4ControlledReference,
    Phase4EvaluationMetric,
    Phase4EvaluationMetricKind,
    Phase4EvaluationPolicy,
    Phase4EvaluationReport,
    Phase4EvaluationStratum,
    Phase4StratumEvaluation,
    Phase4UtteranceEvaluation,
)
from .phase4_propagation import (
    Phase4ArtifactSet,
    validate_phase4_artifact_set,
)
from .context_window_contracts import ContextExclusionKind
from .phase4_review_contracts import (
    Phase4PropagationRun,
    UtteranceReviewLedger,
)


class Phase4EvaluationIntegrityError(RuntimeError):
    """Controlled evaluation evidence is corrupt or incompatible."""


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
        raise Phase4EvaluationIntegrityError(f"{label} integrity is invalid")


def _word_ids(utterance: Utterance) -> frozenset[str]:
    return frozenset(
        word_id
        for component in utterance.components
        for word_id in component.transcript_word_ids
    )


def _source_bounds(intervals) -> tuple[int, int]:
    return (
        min(item.start_microseconds for item in intervals),
        max(
            item.start_microseconds + item.duration_microseconds
            for item in intervals
        ),
    )


def _display_text(utterance: Utterance) -> str:
    return next(
        item.text
        for item in utterance.text_views
        if item.kind == UtteranceTextKind.DISPLAY
    )


def _match_reference(
    reference: Phase4ControlledReference,
    artifacts: Phase4ArtifactSet,
    collar: int,
) -> tuple[dict[str, str], tuple[str, ...], tuple[str, ...]]:
    available = {
        item.utterance_id: item for item in artifacts.corpus.utterances
    }
    matched: dict[str, str] = {}
    for item in reference.utterances:
        reference_words = set(item.transcript_word_ids)
        scored = []
        ref_start, ref_end = _source_bounds(item.source_intervals)
        for system_id, system in available.items():
            word_overlap = len(reference_words.intersection(_word_ids(system)))
            start, end = _source_bounds(system.source_intervals)
            temporal_overlap = min(ref_end, end) - max(ref_start, start)
            if word_overlap or temporal_overlap > 0 or (
                abs(ref_start - start) <= collar
                and abs(ref_end - end) <= collar
            ):
                scored.append(
                    (
                        word_overlap > 0,
                        word_overlap,
                        max(temporal_overlap, 0),
                        -abs(ref_start - start) - abs(ref_end - end),
                        system_id,
                    )
                )
        if scored:
            chosen = max(scored)[-1]
            matched[item.reference_utterance_id] = chosen
            available.pop(chosen)
    unmatched_reference = tuple(
        item.reference_utterance_id
        for item in reference.utterances
        if item.reference_utterance_id not in matched
    )
    return matched, unmatched_reference, tuple(sorted(available))


def _metric(
    kind: Phase4EvaluationMetricKind,
    numerator: int,
    denominator: int,
    basis: str,
    evidence: tuple[str, ...],
    *,
    unit: str = "ratio",
    explicit_value: float | None = None,
) -> Phase4EvaluationMetric:
    if denominator == 0:
        return Phase4EvaluationMetric(
            kind=kind,
            status=EvaluationMetricStatus.NOT_APPLICABLE,
            numerator=0,
            denominator=0,
            value=None,
            unit=unit,
            basis=f"{basis} No eligible controlled reference was present.",
            evidence_references=(),
        )
    return Phase4EvaluationMetric(
        kind=kind,
        status=EvaluationMetricStatus.MEASURED,
        numerator=numerator,
        denominator=denominator,
        value=(
            explicit_value
            if explicit_value is not None
            else numerator / denominator
        ),
        unit=unit,
        basis=basis,
        evidence_references=evidence,
    )


def _boundary_metrics(
    reference: Phase4ControlledReference,
    artifacts: Phase4ArtifactSet,
    policy: Phase4EvaluationPolicy,
) -> tuple[Phase4EvaluationMetric, ...]:
    reference_boundaries = sorted(
        point
        for item in reference.utterances
        for point in _source_bounds(item.source_intervals)
    )
    system_boundaries = sorted(
        point
        for item in artifacts.corpus.utterances
        for point in _source_bounds(item.source_intervals)
    )
    unused = list(reference_boundaries)
    errors = []
    for point in system_boundaries:
        eligible = [
            value
            for value in unused
            if abs(value - point) <= policy.boundary_collar_microseconds
        ]
        if eligible:
            chosen = min(eligible, key=lambda value: (abs(value - point), value))
            unused.remove(chosen)
            errors.append(abs(chosen - point))
    evidence = (reference.reference_id, artifacts.corpus.corpus_id)
    return (
        _metric(
            Phase4EvaluationMetricKind.BOUNDARY_PRECISION,
            len(errors),
            len(system_boundaries),
            "System boundaries matched one-to-one within the declared collar.",
            evidence,
        ),
        _metric(
            Phase4EvaluationMetricKind.BOUNDARY_RECALL,
            len(errors),
            len(reference_boundaries),
            "Reference boundaries matched one-to-one within the declared collar.",
            evidence,
        ),
        _metric(
            Phase4EvaluationMetricKind.BOUNDARY_TIMING_ERROR,
            sum(errors),
            len(errors),
            "Mean absolute error over collar-matched boundaries.",
            evidence,
            unit="microseconds",
            explicit_value=(sum(errors) / len(errors) if errors else None),
        ),
    )


def _segmentation_metric(
    reference: Phase4ControlledReference,
    artifacts: Phase4ArtifactSet,
) -> Phase4EvaluationMetric:
    reference_owner = {
        word_id: item.reference_utterance_id
        for item in reference.utterances
        for word_id in item.transcript_word_ids
    }
    system_owner = {
        word_id: item.utterance_id
        for item in artifacts.corpus.utterances
        for word_id in _word_ids(item)
    }
    words = sorted(set(reference_owner).intersection(system_owner))
    pairs = tuple(combinations(words, 2))
    correct = sum(
        (reference_owner[left] == reference_owner[right])
        == (system_owner[left] == system_owner[right])
        for left, right in pairs
    )
    return _metric(
        Phase4EvaluationMetricKind.SEGMENTATION_SIMILARITY,
        correct,
        len(pairs),
        "Pairwise canonical-word co-ownership agreement.",
        (reference.reference_id, artifacts.corpus.corpus_id),
    )


def evaluate_phase4(
    artifacts: Phase4ArtifactSet,
    reference: Phase4ControlledReference,
    *,
    propagation: Phase4PropagationRun | None = None,
    review_ledger: UtteranceReviewLedger | None = None,
    policy: Phase4EvaluationPolicy | None = None,
    generated_at: datetime | None = None,
) -> Phase4UtteranceEvaluation:
    """Measure Phase 4 behavior against a controlled source-addressed reference."""
    validate_phase4_artifact_set(artifacts)
    _verify_seal(reference, "Phase 4 controlled reference")
    for item in reference.utterances:
        _verify_seal(item, item.reference_utterance_id)
    for item in reference.relations:
        _verify_seal(item, item.reference_relation_id)
    if reference.source_id != artifacts.corpus.utterances[0].source_id:
        raise Phase4EvaluationIntegrityError(
            "controlled reference and corpus use different sources"
        )
    policy = policy or Phase4EvaluationPolicy()
    if policy.require_independent_source_addressing and not (
        reference.independent_of_system_output
        or reference.evidence_class == "synthetic_mechanics"
    ):
        raise Phase4EvaluationIntegrityError(
            "controlled reference preparation is not independent"
        )
    matched, unmatched_reference, unmatched_system = _match_reference(
        reference, artifacts, policy.boundary_collar_microseconds
    )
    ref_by_id = {
        item.reference_utterance_id: item for item in reference.utterances
    }
    system_by_id = {
        item.utterance_id: item for item in artifacts.corpus.utterances
    }
    eligible = tuple(
        (ref_by_id[ref_id], system_by_id[system_id])
        for ref_id, system_id in matched.items()
    )
    evidence = (reference.reference_id, artifacts.corpus.corpus_id)
    metrics = [*_boundary_metrics(reference, artifacts, policy)]
    metrics.append(_segmentation_metric(reference, artifacts))

    def accuracy(kind, predicate, selected=eligible, basis="Exact agreement."):
        return _metric(
            kind,
            sum(predicate(ref, system) for ref, system in selected),
            len(selected),
            basis,
            evidence,
        )

    metrics.append(
        accuracy(
            Phase4EvaluationMetricKind.SPEAKER_ATTRIBUTION_ACCURACY,
            lambda ref, system: (
                ref.attribution_status == system.attribution.status
                and ref.speaker_target_id == system.attribution.target_id
            ),
        )
    )
    unknown = tuple(
        pair
        for pair in eligible
        if pair[0].attribution_status.value == "unknown"
    )
    metrics.append(
        accuracy(
            Phase4EvaluationMetricKind.UNKNOWN_ATTRIBUTION_APPROPRIATENESS,
            lambda ref, system: system.attribution.status.value == "unknown",
            unknown,
            "Unknown reference speakers must remain unknown.",
        )
    )
    predicted_interruptions = {
        (
            item.interrupted_utterance_id,
            item.interrupting_utterance_id,
        )
        for item in artifacts.relations.interruptions
        if item.interrupting_utterance_id is not None
    }
    predicted_continuations = {
        (item.predecessor_utterance_id, item.successor_utterance_id)
        for item in artifacts.relations.continuations
    }
    reference_interruptions = {
        (
            matched[item.predecessor_reference_utterance_id],
            matched[item.successor_reference_utterance_id],
        )
        for item in reference.relations
        if item.kind == "interruption"
        and item.predecessor_reference_utterance_id in matched
        and item.successor_reference_utterance_id in matched
    }
    reference_continuations = {
        (
            matched[item.predecessor_reference_utterance_id],
            matched[item.successor_reference_utterance_id],
        )
        for item in reference.relations
        if item.kind == "continuation"
        and item.predecessor_reference_utterance_id in matched
        and item.successor_reference_utterance_id in matched
    }
    interruption_correct = len(
        predicted_interruptions.intersection(reference_interruptions)
    )
    metrics.extend(
        (
            _metric(
                Phase4EvaluationMetricKind.INTERRUPTION_PRECISION,
                interruption_correct,
                len(predicted_interruptions),
                "Exact source-mapped interruption endpoint agreement.",
                evidence,
            ),
            _metric(
                Phase4EvaluationMetricKind.INTERRUPTION_RECALL,
                interruption_correct,
                len(reference_interruptions),
                "Exact source-mapped interruption endpoint agreement.",
                evidence,
            ),
            _metric(
                Phase4EvaluationMetricKind.CONTINUATION_LINK_ACCURACY,
                len(predicted_continuations.intersection(reference_continuations)),
                len(reference_continuations),
                "Exact source-mapped continuation endpoint agreement.",
                evidence,
            ),
        )
    )
    incomplete = tuple(
        pair
        for pair in eligible
        if pair[0].completeness
        != UtteranceCompletenessClassification.COMPLETE
    )
    metrics.extend(
        (
            accuracy(
                Phase4EvaluationMetricKind.INCOMPLETE_CLASSIFICATION_ACCURACY,
                lambda ref, system: ref.completeness == system.completeness,
                incomplete,
            ),
            accuracy(
                Phase4EvaluationMetricKind.OVERLAP_PRESERVATION_ACCURACY,
                lambda ref, system: ref.overlap_expected
                == (system.overlap_status != UtteranceOverlapStatus.NONE),
            ),
        )
    )
    self_repair_ids = {
        item.utterance_id for item in artifacts.analysis.self_repairs
    }
    metrics.append(
        accuracy(
            Phase4EvaluationMetricKind.SELF_REPAIR_DETECTION_ACCURACY,
            lambda ref, system: ref.self_repair_expected
            == (system.utterance_id in self_repair_ids),
        )
    )
    quotations = {
        item.quoting_utterance_id: item
        for item in artifacts.quotation.quotations
    }
    quotation_pairs = tuple(
        pair for pair in eligible if pair[0].quotation_type is not None
    )
    metrics.extend(
        (
            accuracy(
                Phase4EvaluationMetricKind.QUOTATION_SPAN_ACCURACY,
                lambda ref, system: (
                    system.utterance_id in quotations
                    and quotations[
                        system.utterance_id
                    ].quoted_span.quoted_text
                    == ref.quoted_text
                ),
                quotation_pairs,
            ),
            accuracy(
                Phase4EvaluationMetricKind.QUOTATION_TYPE_ACCURACY,
                lambda ref, system: (
                    system.utterance_id in quotations
                    and quotations[system.utterance_id].quotation_type
                    == ref.quotation_type
                ),
                quotation_pairs,
            ),
        )
    )
    quoted_speakers = tuple(
        pair
        for pair in quotation_pairs
        if pair[0].quoted_speaker_target_id is not None
    )
    metrics.append(
        accuracy(
            Phase4EvaluationMetricKind.QUOTED_SPEAKER_ATTRIBUTION_ACCURACY,
            lambda ref, system: (
                system.utterance_id in quotations
                and quotations[
                    system.utterance_id
                ].quoted_speaker_target_id
                == ref.quoted_speaker_target_id
            ),
            quoted_speakers,
        )
    )
    affected_successors = (
        {
            utterance_id
            for item in propagation.impacts
            if item.affected
            for utterance_id in item.successor_utterance_ids
        }
        if propagation is not None
        else set()
    )
    correction_refs = tuple(
        pair for pair in eligible if pair[0].correction_affected
    )
    metrics.append(
        accuracy(
            Phase4EvaluationMetricKind.CORRECTION_PROPAGATION_COMPLETENESS,
            lambda ref, system: system.utterance_id in affected_successors,
            correction_refs,
        )
    )
    stable_refs = tuple(
        pair for pair in eligible if not pair[0].correction_affected
    )
    stable_successors = (
        {
            utterance_id
            for item in propagation.impacts
            if not item.affected
            for utterance_id in item.successor_utterance_ids
        }
        if propagation is not None
        else {system.utterance_id for _, system in stable_refs}
    )
    metrics.append(
        accuracy(
            Phase4EvaluationMetricKind.UNAFFECTED_ARTIFACT_STABILITY,
            lambda ref, system: system.utterance_id in stable_successors,
            stable_refs,
        )
    )
    metrics.append(
        _metric(
            Phase4EvaluationMetricKind.CONTEXT_WINDOW_REPRODUCIBILITY,
            1,
            1,
            "The context bundle passed deterministic source reconstruction.",
            (
                artifacts.context_windows.context_bundle_id,
                artifacts.context_windows.integrity_sha256,
            ),
        )
    )
    budget_kinds = {
        ContextExclusionKind.MAXIMUM_UTTERANCE_COUNT,
        ContextExclusionKind.MAXIMUM_TOKEN_ESTIMATE,
        ContextExclusionKind.MAXIMUM_SOURCE_DURATION,
    }
    windows = artifacts.context_windows.windows
    correct_truncation = sum(
        window.truncated
        == any(item.kind in budget_kinds for item in window.exclusions)
        for window in windows
    )
    metrics.append(
        _metric(
            Phase4EvaluationMetricKind.CONTEXT_TRUNCATION_CORRECTNESS,
            correct_truncation,
            len(windows),
            "Truncation flags agree with explicit budget exclusions.",
            (artifacts.context_windows.context_bundle_id,),
        )
    )
    reviewed_targets = (
        {
            utterance_id
            for action in review_ledger.actions
            for utterance_id in action.target_utterance_ids
        }
        if review_ledger is not None
        else set()
    )
    review_refs = tuple(
        pair for pair in eligible if pair[0].review_action_expected
    )
    metrics.append(
        accuracy(
            Phase4EvaluationMetricKind.MANUAL_REVIEW_IMPACT,
            lambda ref, system: system.utterance_id in reviewed_targets,
            review_refs,
            "Expected reviewed utterances have append-only review actions.",
        )
    )
    strata = tuple(
        Phase4StratumEvaluation(
            stratum=stratum,
            reference_utterance_count=sum(
                stratum in item.strata for item in reference.utterances
            ),
            matched_utterance_count=sum(
                stratum in ref_by_id[ref_id].strata for ref_id in matched
            ),
            metrics=tuple(
                item
                for item in metrics
                if item.kind
                in {
                    Phase4EvaluationMetricKind.SPEAKER_ATTRIBUTION_ACCURACY,
                    Phase4EvaluationMetricKind.INCOMPLETE_CLASSIFICATION_ACCURACY,
                    Phase4EvaluationMetricKind.OVERLAP_PRESERVATION_ACCURACY,
                }
            ),
        )
        for stratum in Phase4EvaluationStratum
        if any(stratum in item.strata for item in reference.utterances)
    )
    timestamp = generated_at or artifacts.context_windows.created_at
    evaluation_id = typed_id(
        "phase4evaluation",
        artifacts.corpus.corpus_id,
        reference.reference_id,
        policy.model_dump(mode="json"),
        tuple(item.model_dump(mode="json") for item in metrics),
    )
    return _seal(
        Phase4UtteranceEvaluation,
        {
            "evaluation_id": evaluation_id,
            "utterance_corpus_id": artifacts.corpus.corpus_id,
            "controlled_reference_id": reference.reference_id,
            "policy": policy,
            "metrics": tuple(metrics),
            "strata": strata,
            "matched_reference_count": len(matched),
            "unmatched_reference_count": len(unmatched_reference),
            "unmatched_system_count": len(unmatched_system),
            "generated_at": timestamp,
            "evidence_class": (
                "measured_evaluation"
                if reference.evidence_class == "controlled_reference"
                else "synthetic_mechanics"
            ),
            "limitations": (
                "Synthetic references qualify mechanics, not natural-speech "
                "performance."
                if reference.evidence_class == "synthetic_mechanics"
                else "Controlled-corpus results do not establish general performance.",
                "Not-applicable metrics make no accuracy claim.",
            ),
        },
    )


def _report(
    evaluation: Phase4UtteranceEvaluation,
    reference_count: int,
) -> Phase4EvaluationReport:
    measured = sum(
        item.status == EvaluationMetricStatus.MEASURED
        for item in evaluation.metrics
    )
    return _seal(
        Phase4EvaluationReport,
        {
            "report_id": typed_id(
                "phase4evaluationreport",
                evaluation.evaluation_id,
                evaluation.integrity_sha256,
            ),
            "evaluation_id": evaluation.evaluation_id,
            "generated_at": evaluation.generated_at,
            "measured_metric_count": measured,
            "not_applicable_metric_count": len(evaluation.metrics) - measured,
            "reference_utterance_count": reference_count,
            "matched_reference_count": evaluation.matched_reference_count,
            "status": (
                "complete"
                if evaluation.matched_reference_count == reference_count
                else "warning"
            ),
        },
    )


def validate_phase4_evaluation(
    evaluation: Phase4UtteranceEvaluation,
    artifacts: Phase4ArtifactSet,
    reference: Phase4ControlledReference,
    *,
    propagation: Phase4PropagationRun | None = None,
    review_ledger: UtteranceReviewLedger | None = None,
    report: Phase4EvaluationReport | None = None,
) -> None:
    _verify_seal(evaluation, "Phase 4 evaluation")
    expected = evaluate_phase4(
        artifacts,
        reference,
        propagation=propagation,
        review_ledger=review_ledger,
        policy=evaluation.policy,
        generated_at=evaluation.generated_at,
    )
    if expected != evaluation:
        raise Phase4EvaluationIntegrityError(
            "evaluation is not the deterministic controlled comparison"
        )
    if report is not None:
        _verify_seal(report, "Phase 4 evaluation report")
        if report != _report(evaluation, len(reference.utterances)):
            raise Phase4EvaluationIntegrityError(
                "Phase 4 evaluation report is invalid"
            )


def persist_phase4_evaluation(
    evaluation: Phase4UtteranceEvaluation,
    artifacts: Phase4ArtifactSet,
    reference: Phase4ControlledReference,
    destination: Path,
    *,
    propagation: Phase4PropagationRun | None = None,
    review_ledger: UtteranceReviewLedger | None = None,
) -> tuple[Phase4UtteranceEvaluation, Phase4EvaluationReport, Path, bool]:
    validate_phase4_evaluation(
        evaluation,
        artifacts,
        reference,
        propagation=propagation,
        review_ledger=review_ledger,
    )
    report = _report(evaluation, len(reference.utterances))
    root = destination.expanduser().resolve() / "phase4-evaluation" / (
        evaluation.evaluation_id
    )
    paths = (root / "evaluation.json", root / "report.json")
    existing = tuple(path.exists() for path in paths)
    if any(existing) and not all(existing):
        raise Phase4EvaluationIntegrityError(
            "cached evaluation artifact is incomplete"
        )
    if all(existing):
        stored, stored_report = load_phase4_evaluation(root)
        validate_phase4_evaluation(
            stored,
            artifacts,
            reference,
            propagation=propagation,
            review_ledger=review_ledger,
            report=stored_report,
        )
        if stored != evaluation or stored_report != report:
            raise Phase4EvaluationIntegrityError(
                "cached evaluation artifact is incompatible"
            )
        return stored, stored_report, root, True
    _atomic(paths[0], canonical_bytes(evaluation))
    _atomic(paths[1], canonical_bytes(report))
    return evaluation, report, root, False


def load_phase4_evaluation(
    root: Path,
) -> tuple[Phase4UtteranceEvaluation, Phase4EvaluationReport]:
    root = root.expanduser().resolve(strict=True)
    return (
        load_contract(
            (root / "evaluation.json").read_bytes(),
            Phase4UtteranceEvaluation,
        ),
        load_contract(
            (root / "report.json").read_bytes(), Phase4EvaluationReport
        ),
    )
