"""Build bounded challenge, rebuttal, concession, and qualification records."""

from __future__ import annotations

import os
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from .context_window_contracts import ContextWindowBundle, ContextWindowKind
from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase2_contracts import ConfidenceMeasure, ConfidenceOrigin
from .phase5_argument_relation_contracts import (
    ArgumentRelationPolicy,
    ArgumentRelationReport,
    ArgumentRelationRun,
    ChallengeDimension,
    ChallengeRebuttalRelation,
    ConcessionStructure,
    QualificationDimension,
    QualificationStructure,
    RebuttalMethod,
)
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


class ArgumentRelationIntegrityError(RuntimeError):
    """Argument-relation artifacts are corrupt, stale, or incompatible."""


_CHALLENGE_DIMENSIONS = {
    DiscourseActType.EVIDENCE_CHALLENGE: ChallengeDimension.EVIDENCE,
    DiscourseActType.DEFINITION_CHALLENGE: ChallengeDimension.DEFINITION,
    DiscourseActType.PROCEDURAL_OBJECTION: ChallengeDimension.PROCEDURE,
    DiscourseActType.PREMISE_CHALLENGE: ChallengeDimension.PREMISE,
    DiscourseActType.RELEVANCE_CHALLENGE: ChallengeDimension.RELEVANCE,
    DiscourseActType.GENERALIZED_CHALLENGE: ChallengeDimension.GENERAL,
    DiscourseActType.COUNTEREXAMPLE_PROPOSAL: ChallengeDimension.CONTENT,
    DiscourseActType.OBJECTION: ChallengeDimension.CONTENT,
    DiscourseActType.CHALLENGE: ChallengeDimension.CONTENT,
    DiscourseActType.DISAGREEMENT: ChallengeDimension.CONTENT,
}
_REBUTTAL_METHODS = {
    DiscourseActType.DIRECT_REBUTTAL: RebuttalMethod.DIRECT,
    DiscourseActType.REBUTTAL_BY_DENIAL: RebuttalMethod.DENIAL,
    DiscourseActType.REBUTTAL_BY_COUNTEREVIDENCE:
        RebuttalMethod.COUNTEREVIDENCE,
    DiscourseActType.REBUTTAL_BY_COUNTEREXAMPLE:
        RebuttalMethod.COUNTEREXAMPLE,
    DiscourseActType.REBUTTAL_BY_ALTERNATIVE_EXPLANATION:
        RebuttalMethod.ALTERNATIVE_EXPLANATION,
    DiscourseActType.REBUTTAL_BY_QUALIFICATION:
        RebuttalMethod.QUALIFICATION,
    DiscourseActType.REBUTTAL_BY_SCOPE_CORRECTION:
        RebuttalMethod.SCOPE_CORRECTION,
    DiscourseActType.REBUTTAL_BY_CAUSAL_CHALLENGE:
        RebuttalMethod.CAUSAL_CHALLENGE,
    DiscourseActType.UNRESOLVED_TARGET_REBUTTAL:
        RebuttalMethod.UNRESOLVED,
}
_QUALIFICATION_DIMENSIONS = {
    DiscourseActType.SCOPE_QUALIFICATION: QualificationDimension.SCOPE,
    DiscourseActType.TEMPORAL_QUALIFICATION:
        QualificationDimension.TEMPORAL,
    DiscourseActType.CONDITIONAL_QUALIFICATION:
        QualificationDimension.CONDITIONAL,
    DiscourseActType.PROBABILISTIC_QUALIFICATION:
        QualificationDimension.PROBABILISTIC,
    DiscourseActType.EXCEPTION: QualificationDimension.EXCEPTION,
    DiscourseActType.LIMITATION: QualificationDimension.LIMITATION,
    DiscourseActType.HEDGING: QualificationDimension.HEDGING,
    DiscourseActType.PRECISION_CORRECTION:
        QualificationDimension.PRECISION,
    DiscourseActType.CATEGORY_RESTRICTION:
        QualificationDimension.CATEGORY,
    DiscourseActType.THRESHOLD_QUALIFICATION:
        QualificationDimension.THRESHOLD,
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
        raise ArgumentRelationIntegrityError(f"{label} integrity is invalid")


def _window(bundle, utterance_id):
    return next(
        (
            item
            for item in bundle.windows
            if item.target_utterance_id == utterance_id
            and item.kind == ContextWindowKind.BOUNDED_TEMPORAL
        ),
        None,
    )


def _explicit_targets(act, acts):
    by_id = {item.act_id: item for item in acts}
    by_utterance = defaultdict(list)
    for item in acts:
        by_utterance[item.utterance_id].append(item)
    targets, alternatives = [], []
    status = None
    for proposal in act.relation_targets:
        resolved = []
        identifiers = (
            *((proposal.target_id,) if proposal.target_id else ()),
            *proposal.alternative_target_ids,
        )
        for identifier in identifiers:
            if proposal.target_type == DiscourseTargetType.DISCOURSE_ACT:
                if identifier in by_id:
                    resolved.append(by_id[identifier])
            elif proposal.target_type == DiscourseTargetType.UTTERANCE:
                resolved.extend(by_utterance.get(identifier, ()))
        if not resolved:
            continue
        if proposal.target_status in {
            DiscourseTargetStatus.IDENTIFIED,
            DiscourseTargetStatus.PROBABLE,
        }:
            targets.extend(resolved)
            status = proposal.target_status
        else:
            alternatives.extend(resolved)
            status = DiscourseTargetStatus.MULTIPLE_CANDIDATES
    return (
        tuple(dict.fromkeys(item.act_id for item in targets)),
        tuple(
            item
            for item in dict.fromkeys(
                candidate.act_id for candidate in alternatives
            )
            if item not in {target.act_id for target in targets}
        ),
        status,
    )


def _candidate_targets(act, acts, bundle, *, same_utterance):
    explicit_targets, explicit_alternatives, explicit_status = (
        _explicit_targets(act, acts)
    )
    window = _window(bundle, act.utterance_id)
    window_id = window.context_window_id if window else None
    if explicit_status is not None:
        return (
            explicit_targets,
            explicit_alternatives,
            explicit_status,
            window_id,
            "explicit normalized relation target",
        )
    if same_utterance:
        local = tuple(
            item.act_id
            for item in acts
            if item.utterance_id == act.utterance_id
            and item.act_id != act.act_id
            and item.act_family != DiscourseActFamily.QUALIFICATION
        )
        if len(local) == 1:
            return (
                local,
                (),
                DiscourseTargetStatus.PROBABLE,
                window_id,
                "single compatible act in the qualifying utterance",
            )
        if len(local) > 1:
            return (
                (),
                local,
                DiscourseTargetStatus.MULTIPLE_CANDIDATES,
                window_id,
                "multiple compatible acts in the qualifying utterance",
            )
    if window is None:
        return (
            (),
            (),
            DiscourseTargetStatus.UNRESOLVED,
            None,
            "bounded temporal context is unavailable",
        )
    positions = {
        item.utterance_id: item.order_position for item in window.members
    }
    source_position = positions.get(act.utterance_id)
    prior_positions = [
        position
        for utterance_id, position in positions.items()
        if source_position is not None
        and position < source_position
        and any(item.utterance_id == utterance_id for item in acts)
    ]
    if not prior_positions:
        return (
            (),
            (),
            DiscourseTargetStatus.UNRESOLVED,
            window_id,
            "no prior canonical act in bounded temporal context",
        )
    nearest = max(prior_positions)
    candidates = tuple(
        item.act_id
        for item in acts
        if positions.get(item.utterance_id) == nearest
        and item.act_id != act.act_id
    )
    if len(candidates) == 1:
        return (
            candidates,
            (),
            DiscourseTargetStatus.PROBABLE,
            window_id,
            "single canonical act in nearest prior utterance",
        )
    return (
        (),
        candidates,
        DiscourseTargetStatus.MULTIPLE_CANDIDATES,
        window_id,
        "multiple canonical acts in nearest prior utterance",
    )


def _confidence(status):
    if status == DiscourseTargetStatus.IDENTIFIED:
        value, basis = 0.9, "uncalibrated explicit target strength"
    elif status == DiscourseTargetStatus.PROBABLE:
        value, basis = 0.7, "uncalibrated bounded target strength"
    elif status == DiscourseTargetStatus.MULTIPLE_CANDIDATES:
        value, basis = 0.5, "uncalibrated ambiguous target set"
    else:
        return ConfidenceMeasure(
            value=None,
            origin=ConfidenceOrigin.UNAVAILABLE,
            basis="no relation target is selected",
            calibrated=False,
        )
    return ConfidenceMeasure(
        value=value,
        origin=ConfidenceOrigin.DERIVED,
        basis=basis,
        calibrated=False,
    )


def _span_ids(act_ids, by_id):
    return tuple(
        dict.fromkeys(
            span.span_id
            for act_id in act_ids
            for span in by_id[act_id].evidence_spans
        )
    )


def _text(act):
    return tuple(
        dict.fromkeys(span.exact_displayed_text for span in act.evidence_spans)
    )


def _distance(source, target_ids, by_id):
    if not target_ids:
        return None
    source_start = min(
        item.source_interval.start_microseconds
        for item in source.evidence_spans
    )
    target_end = max(
        span.source_interval.start_microseconds
        + span.source_interval.duration_microseconds
        for target_id in target_ids
        for span in by_id[target_id].evidence_spans
    )
    return source_start - target_end


def _retained_disagreement(act, qualifications):
    if act.act_type != DiscourseActType.PARTIAL_CONCESSION:
        return ()
    return tuple(
        dict.fromkeys(
            text
            for item in qualifications
            for text in _text(item)
        )
    )


def build_argument_relations(
    corpus: DiscourseCorpus,
    context: ContextWindowBundle,
    *,
    created_at: datetime,
    policy: ArgumentRelationPolicy | None = None,
):
    validate_discourse_corpus_seal(corpus)
    if context.utterance_corpus_id != corpus.phase4_utterance_corpus_id:
        raise ArgumentRelationIntegrityError(
            "context bundle uses incompatible Phase 4 lineage"
        )
    policy = policy or ArgumentRelationPolicy()
    acts = corpus.selected_acts
    by_id = {item.act_id: item for item in acts}
    qualifications_by_utterance = defaultdict(list)
    for item in acts:
        if item.act_family == DiscourseActFamily.QUALIFICATION:
            qualifications_by_utterance[item.utterance_id].append(item)
    relations = []
    concessions = []
    qualifications = []
    for act in acts:
        if act.act_family in {
            DiscourseActFamily.OBJECTION,
            DiscourseActFamily.REBUTTAL,
        }:
            targets, alternatives, status, window_id, basis = (
                _candidate_targets(
                    act, acts, context, same_utterance=False
                )
            )
            if (
                act.act_type
                == DiscourseActType.UNRESOLVED_TARGET_REBUTTAL
            ):
                alternatives = targets or alternatives
                targets = ()
                status = DiscourseTargetStatus.UNRESOLVED
                basis = "rebuttal type explicitly preserves unresolved target"
            target_inventory = targets or alternatives
            relations.append(
                _seal(
                    ChallengeRebuttalRelation,
                    {
                        "relation_id": typed_id(
                            "challengerelation",
                            corpus.corpus_id,
                            act.act_id,
                            targets,
                            alternatives,
                        ),
                        "discourse_corpus_id": corpus.corpus_id,
                        "source_act_id": act.act_id,
                        "source_utterance_id": act.utterance_id,
                        "source_family": act.act_family,
                        "source_act_type": act.act_type,
                        "challenge_dimension": (
                            _CHALLENGE_DIMENSIONS.get(
                                act.act_type,
                                ChallengeDimension.UNRESOLVED,
                            )
                            if act.act_family
                            == DiscourseActFamily.OBJECTION
                            else None
                        ),
                        "rebuttal_method": (
                            _REBUTTAL_METHODS.get(
                                act.act_type, RebuttalMethod.UNRESOLVED
                            )
                            if act.act_family
                            == DiscourseActFamily.REBUTTAL
                            else None
                        ),
                        "target_status": status,
                        "target_act_ids": targets,
                        "target_utterance_ids": tuple(
                            dict.fromkeys(
                                by_id[item].utterance_id
                                for item in target_inventory
                            )
                        ),
                        "alternative_target_act_ids": alternatives,
                        "challenged_span_ids": _span_ids(
                            target_inventory, by_id
                        ),
                        "supporting_evidence_span_ids": tuple(
                            item.span_id for item in act.evidence_spans
                        ),
                        "qualification_act_ids": tuple(
                            item.act_id
                            for item in qualifications_by_utterance[
                                act.utterance_id
                            ]
                        ),
                        "context_window_id": window_id,
                        "temporal_distance_microseconds": _distance(
                            act, target_inventory, by_id
                        ),
                        "confidence": _confidence(status),
                        "review_status": (
                            act.review_status
                            if status == DiscourseTargetStatus.IDENTIFIED
                            else DiscourseReviewStatus.REVIEW_REQUIRED
                        ),
                        "unresolved_issues": (
                            (basis,)
                            if status
                            in {
                                DiscourseTargetStatus.MULTIPLE_CANDIDATES,
                                DiscourseTargetStatus.UNRESOLVED,
                            }
                            else ()
                        ),
                        "created_at": created_at,
                    },
                )
            )
        elif act.act_family == DiscourseActFamily.CONCESSION:
            targets, alternatives, status, window_id, _ = (
                _candidate_targets(
                    act, acts, context, same_utterance=False
                )
            )
            modifiers = tuple(
                qualifications_by_utterance[act.utterance_id]
            )
            concessions.append(
                _seal(
                    ConcessionStructure,
                    {
                        "concession_id": typed_id(
                            "concession", corpus.corpus_id, act.act_id
                        ),
                        "discourse_corpus_id": corpus.corpus_id,
                        "conceding_act_id": act.act_id,
                        "utterance_id": act.utterance_id,
                        "concession_type": act.act_type,
                        "target_status": status,
                        "target_act_ids": targets,
                        "alternative_target_act_ids": alternatives,
                        "conceded_content": _text(act),
                        "retained_disagreement": _retained_disagreement(
                            act, modifiers
                        ),
                        "qualification_act_ids": tuple(
                            item.act_id for item in modifiers
                        ),
                        "scope_span_ids": tuple(
                            item.span_id for item in act.evidence_spans
                        ),
                        "condition_text": tuple(
                            text
                            for item in modifiers
                            if item.act_type
                            == DiscourseActType.CONDITIONAL_QUALIFICATION
                            for text in _text(item)
                        ),
                        "exception_text": tuple(
                            text
                            for item in modifiers
                            if item.act_type == DiscourseActType.EXCEPTION
                            for text in _text(item)
                        ),
                        "context_window_id": window_id,
                        "confidence": _confidence(status),
                        "review_status": (
                            act.review_status
                            if status == DiscourseTargetStatus.IDENTIFIED
                            else DiscourseReviewStatus.REVIEW_REQUIRED
                        ),
                        "created_at": created_at,
                    },
                )
            )
        elif act.act_family == DiscourseActFamily.QUALIFICATION:
            targets, alternatives, status, window_id, _ = (
                _candidate_targets(
                    act, acts, context, same_utterance=True
                )
            )
            inventory = targets or alternatives
            qualifications.append(
                _seal(
                    QualificationStructure,
                    {
                        "qualification_id": typed_id(
                            "qualification", corpus.corpus_id, act.act_id
                        ),
                        "discourse_corpus_id": corpus.corpus_id,
                        "qualifying_act_id": act.act_id,
                        "utterance_id": act.utterance_id,
                        "qualification_type": act.act_type,
                        "dimension": _QUALIFICATION_DIMENSIONS.get(
                            act.act_type,
                            QualificationDimension.UNRESOLVED,
                        ),
                        "target_status": status,
                        "target_act_ids": targets,
                        "alternative_target_act_ids": alternatives,
                        "target_span_ids": _span_ids(inventory, by_id),
                        "scope_text": _text(act),
                        "condition_text": (
                            _text(act)
                            if act.act_type
                            == DiscourseActType.CONDITIONAL_QUALIFICATION
                            else ()
                        ),
                        "exception_text": (
                            _text(act)
                            if act.act_type == DiscourseActType.EXCEPTION
                            else ()
                        ),
                        "context_window_id": window_id,
                        "confidence": _confidence(status),
                        "review_status": (
                            act.review_status
                            if status == DiscourseTargetStatus.IDENTIFIED
                            else DiscourseReviewStatus.REVIEW_REQUIRED
                        ),
                        "created_at": created_at,
                    },
                )
            )
    children = (*relations, *concessions, *qualifications)
    unresolved = tuple(
        (
            item.source_act_id
            if isinstance(item, ChallengeRebuttalRelation)
            else (
                item.conceding_act_id
                if isinstance(item, ConcessionStructure)
                else item.qualifying_act_id
            )
        )
        for item in children
        if item.target_status
        in {
            DiscourseTargetStatus.MULTIPLE_CANDIDATES,
            DiscourseTargetStatus.UNRESOLVED,
        }
    )
    configuration_hash = canonical_hash(
        {
            "operation": "discourse.argument_relation_construction",
            "discourse_corpus_sha256": canonical_hash(corpus),
            "context_bundle_sha256": canonical_hash(context),
            "policy": policy.model_dump(mode="json"),
        }
    )
    run_id = typed_id(
        "argumentrelationrun", corpus.corpus_id, configuration_hash
    )
    run = _seal(
        ArgumentRelationRun,
        {
            "argument_relation_run_id": run_id,
            "discourse_corpus_id": corpus.corpus_id,
            "discourse_corpus_sha256": canonical_hash(corpus),
            "context_bundle_id": context.context_bundle_id,
            "context_bundle_sha256": canonical_hash(context),
            "policy": policy,
            "configuration_hash": configuration_hash,
            "challenge_rebuttal_relations": tuple(relations),
            "concessions": tuple(concessions),
            "qualifications": tuple(qualifications),
            "unresolved_source_act_ids": unresolved,
            "created_at": created_at,
            "complete": True,
        },
    )
    statuses = Counter(item.target_status for item in children)
    report = _seal(
        ArgumentRelationReport,
        {
            "report_id": typed_id("argumentrelationreport", run_id),
            "argument_relation_run_id": run_id,
            "generated_at": created_at,
            "objection_relation_count": sum(
                item.source_family == DiscourseActFamily.OBJECTION
                for item in relations
            ),
            "rebuttal_relation_count": sum(
                item.source_family == DiscourseActFamily.REBUTTAL
                for item in relations
            ),
            "concession_count": len(concessions),
            "qualification_count": len(qualifications),
            "identified_target_count": statuses[
                DiscourseTargetStatus.IDENTIFIED
            ],
            "probable_target_count": statuses[
                DiscourseTargetStatus.PROBABLE
            ],
            "ambiguous_target_count": statuses[
                DiscourseTargetStatus.MULTIPLE_CANDIDATES
            ],
            "unresolved_target_count": statuses[
                DiscourseTargetStatus.UNRESOLVED
            ],
            "retained_disagreement_count": sum(
                bool(item.retained_disagreement) for item in concessions
            ),
            "qualified_concession_count": sum(
                bool(item.qualification_act_ids) for item in concessions
            ),
            "limitations": (
                "Temporal proximity creates a reviewable target candidate, "
                "not semantic proof of a relation.",
                "A rebuttal classification does not establish success.",
                "Conceded content and qualification scope remain exact "
                "source-span projections.",
                "No factual adjudication or intent inference is performed.",
            ),
            "status": "warning" if unresolved else "complete",
        },
    )
    return run, report


def validate_argument_relations(run, report, corpus, context):
    _verify_seal(run, "argument relation run")
    _verify_seal(report, "argument relation report")
    if (
        run.discourse_corpus_id != corpus.corpus_id
        or run.discourse_corpus_sha256 != canonical_hash(corpus)
        or run.context_bundle_id != context.context_bundle_id
        or run.context_bundle_sha256 != canonical_hash(context)
        or report.argument_relation_run_id != run.argument_relation_run_id
    ):
        raise ArgumentRelationIntegrityError(
            "argument relation source lineage or report is stale"
        )
    expected = build_argument_relations(
        corpus, context, created_at=run.created_at, policy=run.policy
    )
    if expected != (run, report):
        raise ArgumentRelationIntegrityError(
            "argument relation construction does not replay"
        )


def persist_argument_relations(
    run, report, corpus, context, destination: Path
):
    validate_argument_relations(run, report, corpus, context)
    root = destination.expanduser().resolve()
    paths = (
        root / "argument-relation-run.json",
        root / "argument-relation-report.json",
    )
    root.mkdir(parents=True, exist_ok=True)
    existing = tuple(path.exists() for path in paths)
    if any(existing) and not all(existing):
        raise ArgumentRelationIntegrityError(
            "persisted argument relation pair is incomplete"
        )
    if all(existing):
        stored = load_argument_relations(root)
        if stored != (run, report):
            raise ArgumentRelationIntegrityError(
                "persisted argument relation artifacts conflict"
            )
        return (*paths, True)
    for path, item in zip(paths, (run, report)):
        temporary = path.with_name(
            f"{path.name}.partial-{uuid.uuid4().hex}"
        )
        temporary.write_bytes(canonical_bytes(item))
        os.replace(temporary, path)
    return (*paths, False)


def load_argument_relations(root: Path):
    resolved = root.expanduser().resolve(strict=True)
    run = load_contract(
        (resolved / "argument-relation-run.json").read_bytes(),
        ArgumentRelationRun,
    )
    report = load_contract(
        (resolved / "argument-relation-report.json").read_bytes(),
        ArgumentRelationReport,
    )
    _verify_seal(run, "argument relation run")
    _verify_seal(report, "argument relation report")
    return run, report
