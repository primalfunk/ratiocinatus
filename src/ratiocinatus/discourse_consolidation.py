"""Evidence-preserving consolidation of deterministic and provider proposals."""

from __future__ import annotations

import os
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from .context_window_contracts import ContextWindowBundle
from .discourse_baseline import validate_deterministic_discourse
from .discourse_provider_analysis import validate_provider_analysis
from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase2_contracts import ConfidenceMeasure, ConfidenceOrigin
from .phase4_contracts import UtteranceCorpus
from .phase5_baseline_contracts import (
    DeterministicDiscourseReport,
    DeterministicDiscourseRun,
)
from .phase5_consolidation_contracts import (
    CandidateEvidenceDisposition,
    CandidateEvidenceSummary,
    DiscourseConsolidationPolicy,
    DiscourseConsolidationReport,
    DiscourseConsolidationRun,
)
from .phase5_contracts import (
    CandidateDisposition,
    DiscourseAct,
    DiscourseActCandidate,
    DiscourseActCandidateSet,
    DiscourseActObservation,
    DiscourseActType,
    DiscourseAnalysisMethod,
    DiscourseConfidence,
    DiscourseCorpus,
    DiscourseReviewStatus,
)
from .phase5_foundation import (
    seal_discourse_corpus,
    validate_discourse_corpus,
    validate_discourse_corpus_seal,
)
from .phase5_provider_analysis_contracts import (
    ProviderDiscourseReport,
    ProviderDiscourseRun,
)


class DiscourseConsolidationIntegrityError(RuntimeError):
    """Consolidation evidence is corrupt, stale, or incompatible."""


_EXCLUSIVE_GROUPS = (
    frozenset(
        {
            DiscourseActType.INFORMATION_QUESTION,
            DiscourseActType.YES_NO_QUESTION,
            DiscourseActType.ALTERNATIVE_QUESTION,
        }
    ),
    frozenset(
        {
            DiscourseActType.AFFIRMATIVE_ANSWER,
            DiscourseActType.NEGATIVE_ANSWER,
            DiscourseActType.REFUSAL_TO_ANSWER,
            DiscourseActType.INABILITY_TO_ANSWER,
            DiscourseActType.ANSWER_DEFERRED,
        }
    ),
    frozenset(
        {
            DiscourseActType.FULL_CONCESSION,
            DiscourseActType.PARTIAL_CONCESSION,
        }
    ),
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
        raise DiscourseConsolidationIntegrityError(
            f"{label} integrity is invalid"
        )


def _span_overlap(left, right) -> float:
    overlap = max(
        0,
        min(left.end_text_offset, right.end_text_offset)
        - max(left.start_text_offset, right.start_text_offset),
    )
    denominator = max(
        left.end_text_offset - left.start_text_offset,
        right.end_text_offset - right.start_text_offset,
    )
    return overlap / denominator if denominator else 0.0


def _observation_overlap(left, right) -> float:
    return max(
        (
            _span_overlap(a, b)
            for a in left.evidence_spans
            for b in right.evidence_spans
        ),
        default=0.0,
    )


def _group_observations(observations, policy):
    pending = list(sorted(observations, key=lambda item: item.observation_id))
    groups = []
    while pending:
        group = [pending.pop(0)]
        changed = True
        while changed:
            changed = False
            retained = []
            for item in pending:
                if (
                    item.utterance_id == group[0].utterance_id
                    and item.act_family == group[0].act_family
                    and item.act_type == group[0].act_type
                    and any(
                        _observation_overlap(item, peer)
                        >= policy.minimum_span_overlap_for_merge
                        for peer in group
                    )
                ):
                    group.append(item)
                    changed = True
                else:
                    retained.append(item)
            pending = retained
        groups.append(tuple(sorted(group, key=lambda item: item.observation_id)))
    return tuple(groups)


def _score(group, policy) -> float:
    result = max(
        (
            item.confidence.act_type.value
            for item in group
            if item.confidence.act_type.value is not None
        ),
        default=0.0,
    )
    methods = {item.analysis_method for item in group}
    if {
        DiscourseAnalysisMethod.DETERMINISTIC_RULE,
        DiscourseAnalysisMethod.PROVIDER_PROPOSAL,
    }.issubset(methods):
        result += policy.corroboration_bonus
    return min(1.0, result)


def _incompatible(left, right) -> bool:
    if max(
        (_observation_overlap(a, b) for a in left for b in right),
        default=0.0,
    ) <= 0:
        return False
    left_type, right_type = left[0].act_type, right[0].act_type
    if left_type == DiscourseActType.UNKNOWN:
        return right_type != DiscourseActType.UNKNOWN
    if right_type == DiscourseActType.UNKNOWN:
        return left_type != DiscourseActType.UNKNOWN
    return any(
        left_type in group and right_type in group
        for group in _EXCLUSIVE_GROUPS
    )


def _selected_confidence(source, score, source_count):
    return source.model_copy(
        update={
            "selection": ConfidenceMeasure(
                value=score,
                origin=ConfidenceOrigin.DERIVED,
                basis=(
                    "uncalibrated consolidation score from the strongest "
                    f"of {source_count} source observation(s)"
                ),
                calibrated=False,
            ),
            "derivation_method": "evidence-preserving hybrid consolidation",
            "source_features": tuple(
                dict.fromkeys((*source.source_features, "candidate consolidation"))
            ),
            "limitations": tuple(
                dict.fromkeys(
                    (
                        *source.limitations,
                        "Selection score is an uncalibrated ranking aid, "
                        "not a probability.",
                    )
                )
            ),
        }
    )


def _build_outputs(
    baseline,
    provider,
    phase4_corpus,
    *,
    created_at,
    policy,
):
    phase4_hash = canonical_hash(phase4_corpus)
    configuration_hash = canonical_hash(
        {
            "operation": "discourse.candidate_consolidation",
            "phase4_utterance_corpus_sha256": phase4_hash,
            "deterministic_baseline_run_id": baseline.baseline_run_id,
            "provider_run_id": provider.provider_run_id,
            "policy": policy.model_dump(mode="json"),
        }
    )
    discourse_run_id = typed_id(
        "discourserun", phase4_corpus.corpus_id, configuration_hash
    )
    discourse_corpus_id = typed_id(
        "discoursecorpus", discourse_run_id, phase4_hash
    )
    observations = tuple(
        sorted(
            (*baseline.observations, *provider.observations),
            key=lambda item: item.observation_id,
        )
    )
    by_utterance = defaultdict(list)
    for observation in observations:
        by_utterance[observation.utterance_id].append(observation)

    candidate_sets, summaries, acts = [], [], []
    for utterance in phase4_corpus.utterances:
        utterance_observations = tuple(
            by_utterance.get(utterance.utterance_id, ())
        )
        if not utterance_observations:
            continue
        groups = _group_observations(utterance_observations, policy)
        candidate_ids = tuple(
            typed_id(
                "discoursecandidate",
                phase4_corpus.corpus_id,
                utterance.utterance_id,
                group[0].act_family.value,
                group[0].act_type.value,
                tuple(item.observation_id for item in group),
            )
            for group in groups
        )
        scores = tuple(_score(group, policy) for group in groups)
        exclusions = {
            index: tuple(
                candidate_ids[peer]
                for peer in range(len(groups))
                if peer != index and _incompatible(groups[index], groups[peer])
            )
            for index in range(len(groups))
        }
        dispositions = [
            (
                CandidateDisposition.SELECTED
                if score >= policy.selection_threshold
                else CandidateDisposition.DEFERRED
            )
            for score in scores
        ]
        unresolved = False
        for left in range(len(groups)):
            for right in range(left + 1, len(groups)):
                if candidate_ids[right] not in exclusions[left]:
                    continue
                if min(scores[left], scores[right]) < policy.selection_threshold:
                    continue
                difference = abs(scores[left] - scores[right])
                if difference < policy.conflict_resolution_margin:
                    dispositions[left] = CandidateDisposition.UNRESOLVED
                    dispositions[right] = CandidateDisposition.UNRESOLVED
                    unresolved = True
                elif scores[left] > scores[right]:
                    dispositions[right] = CandidateDisposition.REJECTED
                else:
                    dispositions[left] = CandidateDisposition.REJECTED
        selected_indexes = sorted(
            (
                index
                for index, value in enumerate(dispositions)
                if value == CandidateDisposition.SELECTED
            ),
            key=lambda index: (-scores[index], candidate_ids[index]),
        )
        for index in selected_indexes[
            policy.maximum_selected_acts_per_utterance :
        ]:
            dispositions[index] = CandidateDisposition.DEFERRED
        selected_indexes = selected_indexes[
            : policy.maximum_selected_acts_per_utterance
        ]
        if not selected_indexes:
            unresolved = True

        candidate_set_id = typed_id(
            "discoursecandidates",
            discourse_corpus_id,
            utterance.utterance_id,
            candidate_ids,
        )
        candidates = []
        for index, group in enumerate(groups):
            span_ids = tuple(
                sorted(
                    {
                        span.span_id
                        for observation in group
                        for span in observation.evidence_spans
                    }
                )
            )
            target_ids = tuple(
                sorted(
                    {
                        target.proposal_id
                        for observation in group
                        for target in observation.proposed_targets
                    }
                )
            )
            rationale = [
                f"selection score {scores[index]:.3f}",
                (
                    "candidate meets the selection threshold"
                    if scores[index] >= policy.selection_threshold
                    else "candidate remains below the selection threshold"
                ),
            ]
            if dispositions[index] == CandidateDisposition.UNRESOLVED:
                rationale.append(
                    "a close mutually exclusive alternative remains unresolved"
                )
            elif dispositions[index] == CandidateDisposition.REJECTED:
                rationale.append(
                    "a materially stronger mutually exclusive candidate was selected"
                )
            candidates.append(
                DiscourseActCandidate(
                    candidate_id=candidate_ids[index],
                    observation_ids=tuple(
                        item.observation_id for item in group
                    ),
                    act_family=group[0].act_family,
                    act_type=group[0].act_type,
                    evidence_span_ids=span_ids,
                    target_proposal_ids=target_ids,
                    compatible_candidate_ids=tuple(
                        candidate_ids[peer]
                        for peer in range(len(groups))
                        if peer != index
                        and candidate_ids[peer] not in exclusions[index]
                    ),
                    excludes_candidate_ids=exclusions[index],
                    disposition=dispositions[index],
                    selection_confidence=ConfidenceMeasure(
                        value=scores[index],
                        origin=ConfidenceOrigin.DERIVED,
                        basis="uncalibrated evidence consolidation score",
                        calibrated=False,
                    ),
                    selection_rationale=tuple(rationale),
                )
            )
            deterministic_count = sum(
                item.analysis_method
                == DiscourseAnalysisMethod.DETERMINISTIC_RULE
                for item in group
            )
            provider_count = sum(
                item.analysis_method
                == DiscourseAnalysisMethod.PROVIDER_PROPOSAL
                for item in group
            )
            evidence_disposition = (
                CandidateEvidenceDisposition.CORROBORATED
                if deterministic_count and provider_count
                else (
                    CandidateEvidenceDisposition.DETERMINISTIC_ONLY
                    if deterministic_count
                    else CandidateEvidenceDisposition.PROVIDER_ONLY
                )
            )
            summaries.append(
                CandidateEvidenceSummary(
                    summary_id=typed_id(
                        "candidateevidence", candidate_ids[index]
                    ),
                    candidate_id=candidate_ids[index],
                    observation_ids=tuple(
                        item.observation_id for item in group
                    ),
                    disposition=evidence_disposition,
                    deterministic_observation_count=deterministic_count,
                    provider_observation_count=provider_count,
                    maximum_span_overlap=max(
                        (
                            _observation_overlap(a, b)
                            for position, a in enumerate(group)
                            for b in group[position + 1 :]
                        ),
                        default=1.0,
                    ),
                    selection_score=scores[index],
                    supporting_evidence=tuple(
                        dict.fromkeys(
                            feature
                            for item in group
                            for feature in item.confidence.source_features
                        )
                    ),
                    contrary_evidence=tuple(
                        dict.fromkeys(
                            evidence
                            for item in group
                            for evidence in item.contrary_evidence
                        )
                    ),
                    limitations=(
                        "Evidence provenance is retained; corroboration does "
                        "not make either source authoritative.",
                        "Span overlap is a mechanical grouping criterion.",
                    ),
                )
            )
        candidate_set = _seal(
            DiscourseActCandidateSet,
            {
                "candidate_set_id": candidate_set_id,
                "utterance_id": utterance.utterance_id,
                "candidates": tuple(candidates),
                "selection_policy_version": policy.policy_version,
                "unresolved": unresolved,
            },
        )
        candidate_sets.append(candidate_set)
        for index in selected_indexes:
            group = groups[index]
            best = max(
                group,
                key=lambda item: (
                    item.confidence.act_type.value
                    if item.confidence.act_type.value is not None
                    else -1.0
                ),
            )
            acts.append(
                _seal(
                    DiscourseAct,
                    {
                        "act_id": typed_id(
                            "discourseact",
                            discourse_corpus_id,
                            candidate_ids[index],
                        ),
                        "discourse_corpus_id": discourse_corpus_id,
                        "candidate_set_id": candidate_set_id,
                        "selected_candidate_id": candidate_ids[index],
                        "source_observation_ids": tuple(
                            item.observation_id for item in group
                        ),
                        "utterance_id": utterance.utterance_id,
                        "act_family": group[0].act_family,
                        "act_type": group[0].act_type,
                        "evidence_spans": tuple(
                            {
                                span.span_id: span
                                for item in group
                                for span in item.evidence_spans
                            }.values()
                        ),
                        "relation_targets": tuple(
                            {
                                target.proposal_id: target
                                for item in group
                                for target in item.proposed_targets
                            }.values()
                        ),
                        "confidence": _selected_confidence(
                            best.confidence, scores[index], len(group)
                        ),
                        "review_status": (
                            DiscourseReviewStatus.REVIEW_REQUIRED
                            if len(groups) > 1
                            or all(
                                item.analysis_method
                                == DiscourseAnalysisMethod.PROVIDER_PROPOSAL
                                for item in group
                            )
                            else DiscourseReviewStatus.UNREVIEWED
                        ),
                        "created_at": created_at,
                    },
                )
            )

    classified = {item.utterance_id for item in acts}
    unclassified = tuple(
        item.utterance_id
        for item in phase4_corpus.utterances
        if item.utterance_id not in classified
    )
    discourse_corpus = seal_discourse_corpus(
        DiscourseCorpus(
            corpus_id=discourse_corpus_id,
            run_id=discourse_run_id,
            source_corpus_id=phase4_corpus.source_corpus_id,
            source_id=phase4_corpus.source_id,
            phase4_utterance_corpus_id=phase4_corpus.corpus_id,
            phase4_utterance_corpus_sha256=phase4_hash,
            observations=observations,
            candidate_sets=tuple(candidate_sets),
            selected_acts=tuple(acts),
            unclassified_utterance_ids=unclassified,
            created_at=created_at,
            integrity_sha256="0" * 64,
        )
    )
    consolidation_run_id = typed_id(
        "discourseconsolidation",
        discourse_run_id,
        baseline.baseline_run_id,
        provider.provider_run_id,
    )
    run = _seal(
        DiscourseConsolidationRun,
        {
            "consolidation_run_id": consolidation_run_id,
            "discourse_run_id": discourse_run_id,
            "discourse_corpus_id": discourse_corpus_id,
            "phase4_utterance_corpus_id": phase4_corpus.corpus_id,
            "phase4_utterance_corpus_sha256": phase4_hash,
            "deterministic_baseline_run_id": baseline.baseline_run_id,
            "provider_run_id": provider.provider_run_id,
            "policy": policy,
            "configuration_hash": configuration_hash,
            "candidate_sets": tuple(candidate_sets),
            "evidence_summaries": tuple(summaries),
            "selected_act_ids": tuple(item.act_id for item in acts),
            "unresolved_candidate_set_ids": tuple(
                item.candidate_set_id
                for item in candidate_sets
                if item.unresolved
            ),
            "created_at": created_at,
            "complete": True,
        },
    )
    provenance_counts = Counter(item.disposition for item in summaries)
    selection_counts = Counter(
        candidate.disposition
        for item in candidate_sets
        for candidate in item.candidates
    )
    act_counts = Counter(item.utterance_id for item in acts)
    report = _seal(
        DiscourseConsolidationReport,
        {
            "report_id": typed_id(
                "discourseconsolidationreport", consolidation_run_id
            ),
            "consolidation_run_id": consolidation_run_id,
            "discourse_corpus_id": discourse_corpus_id,
            "generated_at": created_at,
            "observation_count": len(observations),
            "candidate_count": len(summaries),
            "corroborated_candidate_count": provenance_counts[
                CandidateEvidenceDisposition.CORROBORATED
            ],
            "deterministic_only_candidate_count": provenance_counts[
                CandidateEvidenceDisposition.DETERMINISTIC_ONLY
            ],
            "provider_only_candidate_count": provenance_counts[
                CandidateEvidenceDisposition.PROVIDER_ONLY
            ],
            "selected_candidate_count": selection_counts[
                CandidateDisposition.SELECTED
            ],
            "rejected_candidate_count": selection_counts[
                CandidateDisposition.REJECTED
            ],
            "deferred_candidate_count": (
                selection_counts[CandidateDisposition.DEFERRED]
                + selection_counts[CandidateDisposition.UNRESOLVED]
            ),
            "unresolved_candidate_set_count": sum(
                item.unresolved for item in candidate_sets
            ),
            "canonical_act_count": len(acts),
            "multi_label_utterance_count": sum(
                value > 1 for value in act_counts.values()
            ),
            "unclassified_utterance_count": len(unclassified),
            "provider_failure_count": len(provider.failures),
            "limitations": (
                "Selection scores are uncalibrated ranking aids.",
                "Provider proposals are evidence, never automatic authority.",
                "Close mutually exclusive alternatives remain unresolved.",
                "Compatible acts may be selected together for one utterance.",
            ),
            "status": (
                "warning"
                if provider.failures or run.unresolved_candidate_set_ids
                else "complete"
            ),
        },
    )
    return run, discourse_corpus, report


def build_discourse_consolidation(
    baseline: DeterministicDiscourseRun,
    baseline_report: DeterministicDiscourseReport,
    provider: ProviderDiscourseRun,
    provider_report: ProviderDiscourseReport,
    phase4_corpus: UtteranceCorpus,
    context: ContextWindowBundle,
    *,
    created_at: datetime,
    policy: DiscourseConsolidationPolicy | None = None,
):
    validate_deterministic_discourse(
        baseline, phase4_corpus, report=baseline_report
    )
    validate_provider_analysis(
        provider, provider_report, phase4_corpus, context
    )
    if (
        baseline.phase4_utterance_corpus_id != phase4_corpus.corpus_id
        or provider.phase4_utterance_corpus_id != phase4_corpus.corpus_id
    ):
        raise DiscourseConsolidationIntegrityError(
            "consolidation inputs use incompatible Phase 4 lineage"
        )
    result = _build_outputs(
        baseline,
        provider,
        phase4_corpus,
        created_at=created_at,
        policy=policy or DiscourseConsolidationPolicy(),
    )
    integrity = validate_discourse_corpus(
        result[1], phase4_corpus, checked_at=created_at
    )
    if not integrity.valid:
        raise DiscourseConsolidationIntegrityError(
            "consolidated discourse corpus failed foundation validation"
        )
    return result


def validate_discourse_consolidation(
    run,
    discourse_corpus,
    report,
    baseline,
    baseline_report,
    provider,
    provider_report,
    phase4_corpus,
    context,
) -> None:
    _verify_seal(run, "discourse consolidation run")
    _verify_seal(report, "discourse consolidation report")
    validate_discourse_corpus_seal(discourse_corpus)
    if (
        run.discourse_corpus_id != discourse_corpus.corpus_id
        or report.consolidation_run_id != run.consolidation_run_id
        or report.discourse_corpus_id != discourse_corpus.corpus_id
        or tuple(item.act_id for item in discourse_corpus.selected_acts)
        != run.selected_act_ids
        or discourse_corpus.candidate_sets != run.candidate_sets
    ):
        raise DiscourseConsolidationIntegrityError(
            "consolidation artifact inventory is stale"
        )
    validate_deterministic_discourse(
        baseline, phase4_corpus, report=baseline_report
    )
    validate_provider_analysis(
        provider, provider_report, phase4_corpus, context
    )
    expected = _build_outputs(
        baseline,
        provider,
        phase4_corpus,
        created_at=run.created_at,
        policy=run.policy,
    )
    if expected != (run, discourse_corpus, report):
        raise DiscourseConsolidationIntegrityError(
            "discourse consolidation does not replay"
        )


def persist_discourse_consolidation(
    run,
    discourse_corpus,
    report,
    baseline,
    baseline_report,
    provider,
    provider_report,
    phase4_corpus,
    context,
    destination: Path,
):
    validate_discourse_consolidation(
        run,
        discourse_corpus,
        report,
        baseline,
        baseline_report,
        provider,
        provider_report,
        phase4_corpus,
        context,
    )
    root = destination.expanduser().resolve()
    paths = (
        root / "discourse-consolidation-run.json",
        root / "discourse-corpus.json",
        root / "discourse-consolidation-report.json",
    )
    root.mkdir(parents=True, exist_ok=True)
    existing = tuple(path.exists() for path in paths)
    if any(existing) and not all(existing):
        raise DiscourseConsolidationIntegrityError(
            "persisted consolidation triple is incomplete"
        )
    if all(existing):
        stored = load_discourse_consolidation(root)
        if stored != (run, discourse_corpus, report):
            raise DiscourseConsolidationIntegrityError(
                "persisted consolidation conflicts"
            )
        return (*paths, True)
    for path, item in zip(paths, (run, discourse_corpus, report)):
        temporary = path.with_name(
            f"{path.name}.partial-{uuid.uuid4().hex}"
        )
        temporary.write_bytes(canonical_bytes(item))
        os.replace(temporary, path)
    return (*paths, False)


def load_discourse_consolidation(root: Path):
    resolved = root.expanduser().resolve(strict=True)
    run = load_contract(
        (resolved / "discourse-consolidation-run.json").read_bytes(),
        DiscourseConsolidationRun,
    )
    corpus = load_contract(
        (resolved / "discourse-corpus.json").read_bytes(),
        DiscourseCorpus,
    )
    report = load_contract(
        (resolved / "discourse-consolidation-report.json").read_bytes(),
        DiscourseConsolidationReport,
    )
    _verify_seal(run, "discourse consolidation run")
    validate_discourse_corpus_seal(corpus)
    _verify_seal(report, "discourse consolidation report")
    return run, corpus, report
