"""CLI operations for Phase 5 discourse evidence construction."""

from __future__ import annotations

import argparse
from pathlib import Path

from .context_windows import load_context_windows
from .discourse_consolidation import (
    build_discourse_consolidation,
    load_discourse_consolidation,
    persist_discourse_consolidation,
    validate_discourse_consolidation,
)
from .question_answer_construction import (
    build_question_answers,
    load_question_answers,
    persist_question_answers,
    validate_question_answers,
)
from .argument_relation_construction import (
    build_argument_relations,
    load_argument_relations,
    persist_argument_relations,
    validate_argument_relations,
)
from .lexical_example_quotation_construction import (
    build_lexical_example_quotation,
    load_lexical_example_quotation,
    persist_lexical_example_quotation,
    validate_lexical_example_quotation,
)
from .procedural_state_construction import (
    build_procedural_state,
    load_procedural_state,
    persist_procedural_state,
    validate_procedural_state,
)
from .discourse_provider_analysis import (
    load_provider_analysis,
    persist_provider_analysis,
    run_provider_analysis,
    validate_provider_analysis,
)
from .discourse_providers import DiscourseProviderRegistry
from .discourse_baseline import (
    build_deterministic_discourse,
    load_deterministic_discourse,
    persist_deterministic_discourse,
    validate_deterministic_discourse,
)
from .quotation_evidence import load_quotation_evidence
from .utterance_segmentation import load_utterance_corpus


def add_discourse_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    parser = subparsers.add_parser("discourse")
    actions = parser.add_subparsers(dest="action", required=True)
    from .phase5_review_cli import add_phase5_review_parsers

    add_phase5_review_parsers(actions)
    from .phase5_evaluation_cli import add_phase5_evaluation_parsers

    add_phase5_evaluation_parsers(actions)
    from .phase5_export_cli import add_phase5_export_parsers

    add_phase5_export_parsers(actions)
    build = actions.add_parser("baseline-build")
    build.add_argument("utterance_corpus_root", type=Path)
    build.add_argument("destination", type=Path)
    build.add_argument("--quotation-root", type=Path)
    validate = actions.add_parser("baseline-validate")
    validate.add_argument("baseline_root", type=Path)
    validate.add_argument("utterance_corpus_root", type=Path)
    validate.add_argument("--quotation-root", type=Path)
    provider_build = actions.add_parser("provider-build")
    provider_build.add_argument("utterance_corpus_root", type=Path)
    provider_build.add_argument("context_window_root", type=Path)
    provider_build.add_argument("destination", type=Path)
    provider_build.add_argument(
        "--provider", default="unconfigured.discourse"
    )
    provider_build.add_argument("--deterministic-seed", type=int)
    provider_validate = actions.add_parser("provider-validate")
    provider_validate.add_argument("provider_root", type=Path)
    provider_validate.add_argument("utterance_corpus_root", type=Path)
    provider_validate.add_argument("context_window_root", type=Path)
    for action in (
        "provider-inspect",
        "list-provider-observations",
        "list-provider-failures",
    ):
        item = actions.add_parser(action)
        item.add_argument("provider_root", type=Path)
    consolidate_build = actions.add_parser("consolidate-build")
    consolidate_build.add_argument("baseline_root", type=Path)
    consolidate_build.add_argument("provider_root", type=Path)
    consolidate_build.add_argument("utterance_corpus_root", type=Path)
    consolidate_build.add_argument("context_window_root", type=Path)
    consolidate_build.add_argument("destination", type=Path)
    consolidate_validate = actions.add_parser("consolidate-validate")
    consolidate_validate.add_argument("consolidation_root", type=Path)
    consolidate_validate.add_argument("baseline_root", type=Path)
    consolidate_validate.add_argument("provider_root", type=Path)
    consolidate_validate.add_argument("utterance_corpus_root", type=Path)
    consolidate_validate.add_argument("context_window_root", type=Path)
    for action in (
        "consolidate-inspect",
        "list-candidates",
        "list-canonical-acts",
        "list-ambiguous",
    ):
        item = actions.add_parser(action)
        item.add_argument("consolidation_root", type=Path)

    qa_build = actions.add_parser("question-answer-build")
    qa_build.add_argument("consolidation_root", type=Path)
    qa_build.add_argument("context_window_root", type=Path)
    qa_build.add_argument("destination", type=Path)
    qa_validate = actions.add_parser("question-answer-validate")
    qa_validate.add_argument("question_answer_root", type=Path)
    qa_validate.add_argument("consolidation_root", type=Path)
    qa_validate.add_argument("context_window_root", type=Path)
    for action in (
        "question-answer-inspect",
        "list-questions",
        "list-answer-relations",
        "list-unresolved-answers",
    ):
        item = actions.add_parser(action)
        item.add_argument("question_answer_root", type=Path)

    relation_build = actions.add_parser("argument-relations-build")
    relation_build.add_argument("consolidation_root", type=Path)
    relation_build.add_argument("context_window_root", type=Path)
    relation_build.add_argument("destination", type=Path)
    relation_validate = actions.add_parser("argument-relations-validate")
    relation_validate.add_argument("argument_relation_root", type=Path)
    relation_validate.add_argument("consolidation_root", type=Path)
    relation_validate.add_argument("context_window_root", type=Path)
    for action in (
        "argument-relations-inspect",
        "list-objections",
        "list-rebuttals",
        "list-concessions",
        "list-qualifications",
        "list-unresolved-relations",
    ):
        item = actions.add_parser(action)
        item.add_argument("argument_relation_root", type=Path)

    lexical_build = actions.add_parser("lexical-structures-build")
    lexical_build.add_argument("consolidation_root", type=Path)
    lexical_build.add_argument("context_window_root", type=Path)
    lexical_build.add_argument("destination", type=Path)
    lexical_build.add_argument("--quotation-root", type=Path)
    lexical_validate = actions.add_parser("lexical-structures-validate")
    lexical_validate.add_argument("lexical_structure_root", type=Path)
    lexical_validate.add_argument("consolidation_root", type=Path)
    lexical_validate.add_argument("context_window_root", type=Path)
    lexical_validate.add_argument("--quotation-root", type=Path)
    for action in (
        "lexical-structures-inspect",
        "list-definitions",
        "list-examples",
        "list-quotation-uses",
        "list-unresolved-lexical-structures",
    ):
        item = actions.add_parser(action)
        item.add_argument("lexical_structure_root", type=Path)

    procedural_build = actions.add_parser("procedural-state-build")
    procedural_build.add_argument("consolidation_root", type=Path)
    procedural_build.add_argument("utterance_corpus_root", type=Path)
    procedural_build.add_argument("destination", type=Path)
    procedural_validate = actions.add_parser("procedural-state-validate")
    procedural_validate.add_argument("procedural_state_root", type=Path)
    procedural_validate.add_argument("consolidation_root", type=Path)
    procedural_validate.add_argument("utterance_corpus_root", type=Path)
    for action in (
        "procedural-state-inspect",
        "list-procedural-events",
        "list-procedural-snapshots",
        "list-unresolved-procedural-events",
    ):
        item = actions.add_parser(action)
        item.add_argument("procedural_state_root", type=Path)

    for action in (
        "baseline-inspect",
        "list-observations",
        "list-unclassified",
    ):
        item = actions.add_parser(action)
        item.add_argument("baseline_root", type=Path)


def _run_provider_command(args, emit, structured: bool) -> int | None:
    provider_actions = {
        "provider-build",
        "provider-validate",
        "provider-inspect",
        "list-provider-observations",
        "list-provider-failures",
    }
    if args.action not in provider_actions:
        return None
    if args.action in {
        "provider-inspect",
        "list-provider-observations",
        "list-provider-failures",
    }:
        run, report = load_provider_analysis(args.provider_root)
        if args.action == "list-provider-observations":
            emit(run.observations, structured)
        elif args.action == "list-provider-failures":
            emit(run.failures, structured)
        else:
            emit(
                {
                    "run": run.model_dump(mode="json"),
                    "report": report.model_dump(mode="json"),
                },
                structured,
            )
        return 0
    _, corpus, _ = load_utterance_corpus(args.utterance_corpus_root)
    context, _ = load_context_windows(args.context_window_root)
    if args.action == "provider-validate":
        run, report = load_provider_analysis(args.provider_root)
        validate_provider_analysis(run, report, corpus, context)
        emit(
            {
                "valid": True,
                "provider_run_id": run.provider_run_id,
                "phase4_utterance_corpus_id": corpus.corpus_id,
            },
            structured,
        )
        return 0
    provider = DiscourseProviderRegistry.with_boundaries().get(args.provider)
    destination = args.destination.expanduser().resolve()
    protected = (
        args.utterance_corpus_root.expanduser().resolve(strict=True),
        args.context_window_root.expanduser().resolve(strict=True),
    )
    if any(
        destination == root or root in destination.parents
        for root in protected
    ):
        raise ValueError(
            "provider discourse output must not modify Phase 4 evidence"
        )
    run, report = run_provider_analysis(
        corpus,
        context,
        provider,
        created_at=corpus.created_at,
        deterministic_seed=args.deterministic_seed,
    )
    run_path, report_path, reused = persist_provider_analysis(
        run, report, corpus, context, destination
    )
    emit(
        {
            "run": run.model_dump(mode="json"),
            "report": report.model_dump(mode="json"),
            "run_path": str(run_path),
            "report_path": str(report_path),
            "reused": reused,
        },
        structured,
    )
    return 0


def _run_procedural_state_command(args, emit, structured: bool) -> int | None:
    actions = {
        "procedural-state-build",
        "procedural-state-validate",
        "procedural-state-inspect",
        "list-procedural-events",
        "list-procedural-snapshots",
        "list-unresolved-procedural-events",
    }
    if args.action not in actions:
        return None
    if args.action in {
        "procedural-state-inspect",
        "list-procedural-events",
        "list-procedural-snapshots",
        "list-unresolved-procedural-events",
    }:
        run, report = load_procedural_state(
            args.procedural_state_root
        )
        if args.action == "list-procedural-events":
            emit(run.events, structured)
        elif args.action == "list-procedural-snapshots":
            emit(run.snapshots, structured)
        elif args.action == "list-unresolved-procedural-events":
            emit(
                tuple(
                    item
                    for item in run.events
                    if item.event_id in (
                        run.snapshots[-1].unresolved_event_ids
                        if run.snapshots else ()
                    )
                ),
                structured,
            )
        else:
            emit(
                {
                    "run": run.model_dump(mode="json"),
                    "report": report.model_dump(mode="json"),
                },
                structured,
            )
        return 0
    _, corpus, _ = load_discourse_consolidation(
        args.consolidation_root
    )
    _, phase4_corpus, _ = load_utterance_corpus(
        args.utterance_corpus_root
    )
    if args.action == "procedural-state-validate":
        run, report = load_procedural_state(
            args.procedural_state_root
        )
        validate_procedural_state(
            run, report, corpus, phase4_corpus
        )
        emit(
            {
                "valid": True,
                "procedural_state_run_id": (
                    run.procedural_state_run_id
                ),
                "discourse_corpus_id": corpus.corpus_id,
            },
            structured,
        )
        return 0
    destination = args.destination.expanduser().resolve()
    protected = (
        args.consolidation_root.expanduser().resolve(strict=True),
        args.utterance_corpus_root.expanduser().resolve(strict=True),
    )
    if any(
        destination == root or root in destination.parents
        for root in protected
    ):
        raise ValueError(
            "procedural-state output must not modify source evidence"
        )
    run, report = build_procedural_state(
        corpus, phase4_corpus, created_at=corpus.created_at
    )
    run_path, report_path, reused = persist_procedural_state(
        run, report, corpus, phase4_corpus, destination
    )
    emit(
        {
            "run": run.model_dump(mode="json"),
            "report": report.model_dump(mode="json"),
            "run_path": str(run_path),
            "report_path": str(report_path),
            "reused": reused,
        },
        structured,
    )
    return 0

def _run_lexical_structure_command(args, emit, structured: bool) -> int | None:
    actions = {
        "lexical-structures-build",
        "lexical-structures-validate",
        "lexical-structures-inspect",
        "list-definitions",
        "list-examples",
        "list-quotation-uses",
        "list-unresolved-lexical-structures",
    }
    if args.action not in actions:
        return None
    if args.action in {
        "lexical-structures-inspect",
        "list-definitions",
        "list-examples",
        "list-quotation-uses",
        "list-unresolved-lexical-structures",
    }:
        run, report = load_lexical_example_quotation(
            args.lexical_structure_root
        )
        if args.action == "list-definitions":
            emit(run.definitions, structured)
        elif args.action == "list-examples":
            emit(run.examples, structured)
        elif args.action == "list-quotation-uses":
            emit(run.quotation_uses, structured)
        elif args.action == "list-unresolved-lexical-structures":
            emit(run.unresolved_source_act_ids, structured)
        else:
            emit(
                {
                    "run": run.model_dump(mode="json"),
                    "report": report.model_dump(mode="json"),
                },
                structured,
            )
        return 0
    _, corpus, _ = load_discourse_consolidation(
        args.consolidation_root
    )
    context, _ = load_context_windows(args.context_window_root)
    quotation = (
        load_quotation_evidence(args.quotation_root)[0]
        if args.quotation_root is not None
        else None
    )
    if args.action == "lexical-structures-validate":
        run, report = load_lexical_example_quotation(
            args.lexical_structure_root
        )
        validate_lexical_example_quotation(
            run, report, corpus, context, quotation_evidence=quotation
        )
        emit(
            {
                "valid": True,
                "construction_run_id": run.construction_run_id,
                "discourse_corpus_id": corpus.corpus_id,
            },
            structured,
        )
        return 0
    destination = args.destination.expanduser().resolve()
    protected = [
        args.consolidation_root.expanduser().resolve(strict=True),
        args.context_window_root.expanduser().resolve(strict=True),
    ]
    if args.quotation_root is not None:
        protected.append(
            args.quotation_root.expanduser().resolve(strict=True)
        )
    if any(
        destination == root or root in destination.parents
        for root in protected
    ):
        raise ValueError(
            "lexical-structure output must not modify source evidence"
        )
    run, report = build_lexical_example_quotation(
        corpus, context, created_at=corpus.created_at,
        quotation_evidence=quotation,
    )
    run_path, report_path, reused = (
        persist_lexical_example_quotation(
            run, report, corpus, context, destination,
            quotation_evidence=quotation,
        )
    )
    emit(
        {
            "run": run.model_dump(mode="json"),
            "report": report.model_dump(mode="json"),
            "run_path": str(run_path),
            "report_path": str(report_path),
            "reused": reused,
        },
        structured,
    )
    return 0

def _run_argument_relation_command(args, emit, structured: bool) -> int | None:
    actions = {
        "argument-relations-build",
        "argument-relations-validate",
        "argument-relations-inspect",
        "list-objections",
        "list-rebuttals",
        "list-concessions",
        "list-qualifications",
        "list-unresolved-relations",
    }
    if args.action not in actions:
        return None
    if args.action in {
        "argument-relations-inspect",
        "list-objections",
        "list-rebuttals",
        "list-concessions",
        "list-qualifications",
        "list-unresolved-relations",
    }:
        run, report = load_argument_relations(
            args.argument_relation_root
        )
        if args.action == "list-objections":
            emit(
                tuple(
                    item for item in run.challenge_rebuttal_relations
                    if item.source_family.value
                    == "objection_and_challenge"
                ),
                structured,
            )
        elif args.action == "list-rebuttals":
            emit(
                tuple(
                    item for item in run.challenge_rebuttal_relations
                    if item.source_family.value == "rebuttal"
                ),
                structured,
            )
        elif args.action == "list-concessions":
            emit(run.concessions, structured)
        elif args.action == "list-qualifications":
            emit(run.qualifications, structured)
        elif args.action == "list-unresolved-relations":
            emit(run.unresolved_source_act_ids, structured)
        else:
            emit(
                {
                    "run": run.model_dump(mode="json"),
                    "report": report.model_dump(mode="json"),
                },
                structured,
            )
        return 0
    _, corpus, _ = load_discourse_consolidation(
        args.consolidation_root
    )
    context, _ = load_context_windows(args.context_window_root)
    if args.action == "argument-relations-validate":
        run, report = load_argument_relations(
            args.argument_relation_root
        )
        validate_argument_relations(run, report, corpus, context)
        emit(
            {
                "valid": True,
                "argument_relation_run_id": (
                    run.argument_relation_run_id
                ),
                "discourse_corpus_id": corpus.corpus_id,
            },
            structured,
        )
        return 0
    destination = args.destination.expanduser().resolve()
    protected = (
        args.consolidation_root.expanduser().resolve(strict=True),
        args.context_window_root.expanduser().resolve(strict=True),
    )
    if any(
        destination == root or root in destination.parents
        for root in protected
    ):
        raise ValueError(
            "argument-relation output must not modify source evidence"
        )
    run, report = build_argument_relations(
        corpus, context, created_at=corpus.created_at
    )
    run_path, report_path, reused = persist_argument_relations(
        run, report, corpus, context, destination
    )
    emit(
        {
            "run": run.model_dump(mode="json"),
            "report": report.model_dump(mode="json"),
            "run_path": str(run_path),
            "report_path": str(report_path),
            "reused": reused,
        },
        structured,
    )
    return 0

def _run_question_answer_command(args, emit, structured: bool) -> int | None:
    actions = {
        "question-answer-build",
        "question-answer-validate",
        "question-answer-inspect",
        "list-questions",
        "list-answer-relations",
        "list-unresolved-answers",
    }
    if args.action not in actions:
        return None
    if args.action in {
        "question-answer-inspect",
        "list-questions",
        "list-answer-relations",
        "list-unresolved-answers",
    }:
        run, report = load_question_answers(args.question_answer_root)
        if args.action == "list-questions":
            emit(run.questions, structured)
        elif args.action == "list-answer-relations":
            emit(run.answer_relations, structured)
        elif args.action == "list-unresolved-answers":
            emit(
                tuple(
                    item
                    for item in run.answer_relations
                    if item.target_status.value in {
                        "multiple_candidate_targets", "unresolved"
                    }
                ),
                structured,
            )
        else:
            emit(
                {
                    "run": run.model_dump(mode="json"),
                    "report": report.model_dump(mode="json"),
                },
                structured,
            )
        return 0
    _, corpus, _ = load_discourse_consolidation(
        args.consolidation_root
    )
    context, _ = load_context_windows(args.context_window_root)
    if args.action == "question-answer-validate":
        run, report = load_question_answers(args.question_answer_root)
        validate_question_answers(run, report, corpus, context)
        emit(
            {
                "valid": True,
                "question_answer_run_id": run.question_answer_run_id,
                "discourse_corpus_id": corpus.corpus_id,
            },
            structured,
        )
        return 0
    destination = args.destination.expanduser().resolve()
    protected = (
        args.consolidation_root.expanduser().resolve(strict=True),
        args.context_window_root.expanduser().resolve(strict=True),
    )
    if any(
        destination == root or root in destination.parents
        for root in protected
    ):
        raise ValueError(
            "question-answer output must not modify source evidence"
        )
    run, report = build_question_answers(
        corpus, context, created_at=corpus.created_at
    )
    run_path, report_path, reused = persist_question_answers(
        run, report, corpus, context, destination
    )
    emit(
        {
            "run": run.model_dump(mode="json"),
            "report": report.model_dump(mode="json"),
            "run_path": str(run_path),
            "report_path": str(report_path),
            "reused": reused,
        },
        structured,
    )
    return 0

def _run_consolidation_command(args, emit, structured: bool) -> int | None:
    actions = {
        "consolidate-build",
        "consolidate-validate",
        "consolidate-inspect",
        "list-candidates",
        "list-canonical-acts",
        "list-ambiguous",
    }
    if args.action not in actions:
        return None
    if args.action in {
        "consolidate-inspect",
        "list-candidates",
        "list-canonical-acts",
        "list-ambiguous",
    }:
        run, corpus, report = load_discourse_consolidation(
            args.consolidation_root
        )
        if args.action == "list-candidates":
            emit(run.candidate_sets, structured)
        elif args.action == "list-canonical-acts":
            emit(corpus.selected_acts, structured)
        elif args.action == "list-ambiguous":
            emit(
                tuple(
                    item for item in run.candidate_sets if item.unresolved
                ),
                structured,
            )
        else:
            emit(
                {
                    "run": run.model_dump(mode="json"),
                    "corpus": corpus.model_dump(mode="json"),
                    "report": report.model_dump(mode="json"),
                },
                structured,
            )
        return 0
    baseline, baseline_report = load_deterministic_discourse(
        args.baseline_root
    )
    provider, provider_report = load_provider_analysis(args.provider_root)
    _, phase4_corpus, _ = load_utterance_corpus(
        args.utterance_corpus_root
    )
    context, _ = load_context_windows(args.context_window_root)
    if args.action == "consolidate-validate":
        run, corpus, report = load_discourse_consolidation(
            args.consolidation_root
        )
        validate_discourse_consolidation(
            run, corpus, report, baseline, baseline_report, provider,
            provider_report, phase4_corpus, context,
        )
        emit(
            {
                "valid": True,
                "consolidation_run_id": run.consolidation_run_id,
                "discourse_corpus_id": corpus.corpus_id,
            },
            structured,
        )
        return 0
    destination = args.destination.expanduser().resolve()
    protected = (
        args.baseline_root.expanduser().resolve(strict=True),
        args.provider_root.expanduser().resolve(strict=True),
        args.utterance_corpus_root.expanduser().resolve(strict=True),
        args.context_window_root.expanduser().resolve(strict=True),
    )
    if any(
        destination == root or root in destination.parents
        for root in protected
    ):
        raise ValueError(
            "consolidation output must not modify source evidence"
        )
    run, corpus, report = build_discourse_consolidation(
        baseline, baseline_report, provider, provider_report, phase4_corpus,
        context, created_at=phase4_corpus.created_at,
    )
    run_path, corpus_path, report_path, reused = (
        persist_discourse_consolidation(
            run, corpus, report, baseline, baseline_report, provider,
            provider_report, phase4_corpus, context, destination,
        )
    )
    emit(
        {
            "run": run.model_dump(mode="json"),
            "corpus": corpus.model_dump(mode="json"),
            "report": report.model_dump(mode="json"),
            "run_path": str(run_path),
            "corpus_path": str(corpus_path),
            "report_path": str(report_path),
            "reused": reused,
        },
        structured,
    )
    return 0

def run_discourse_command(args, emit, structured: bool) -> int | None:
    if args.command != "discourse":
        return None
    from .phase5_export_cli import run_phase5_export_command

    export_result = run_phase5_export_command(args, emit, structured)
    if export_result is not None:
        return export_result
    from .phase5_evaluation_cli import run_phase5_evaluation_command

    evaluation_result = run_phase5_evaluation_command(args, emit, structured)
    if evaluation_result is not None:
        return evaluation_result
    from .phase5_review_cli import run_phase5_review_command

    review_result = run_phase5_review_command(args, emit, structured)
    if review_result is not None:
        return review_result
    procedural_state_result = _run_procedural_state_command(
        args, emit, structured
    )
    if procedural_state_result is not None:
        return procedural_state_result
    lexical_structure_result = _run_lexical_structure_command(
        args, emit, structured
    )
    if lexical_structure_result is not None:
        return lexical_structure_result
    argument_relation_result = _run_argument_relation_command(
        args, emit, structured
    )
    if argument_relation_result is not None:
        return argument_relation_result
    question_answer_result = _run_question_answer_command(
        args, emit, structured
    )
    if question_answer_result is not None:
        return question_answer_result
    consolidation_result = _run_consolidation_command(
        args, emit, structured
    )
    if consolidation_result is not None:
        return consolidation_result
    provider_result = _run_provider_command(args, emit, structured)
    if provider_result is not None:
        return provider_result
    if args.action in {
        "baseline-inspect",
        "list-observations",
        "list-unclassified",
    }:
        run, report = load_deterministic_discourse(args.baseline_root)
        if args.action == "list-observations":
            emit(run.observations, structured)
        elif args.action == "list-unclassified":
            emit(run.unclassified_utterance_ids, structured)
        else:
            emit(
                {
                    "run": run.model_dump(mode="json"),
                    "report": report.model_dump(mode="json"),
                },
                structured,
            )
        return 0

    _, corpus, _ = load_utterance_corpus(args.utterance_corpus_root)
    quotation = (
        load_quotation_evidence(args.quotation_root)[0]
        if args.quotation_root is not None
        else None
    )
    if args.action == "baseline-validate":
        run, report = load_deterministic_discourse(args.baseline_root)
        validate_deterministic_discourse(
            run, corpus, quotation_evidence=quotation, report=report
        )
        emit(
            {
                "valid": True,
                "baseline_run_id": run.baseline_run_id,
                "phase4_utterance_corpus_id": corpus.corpus_id,
            },
            structured,
        )
        return 0

    destination = args.destination.expanduser().resolve()
    protected = [
        args.utterance_corpus_root.expanduser().resolve(strict=True)
    ]
    if args.quotation_root is not None:
        protected.append(
            args.quotation_root.expanduser().resolve(strict=True)
        )
    if any(
        destination == root or root in destination.parents
        for root in protected
    ):
        raise ValueError(
            "discourse output must not modify Phase 4 evidence"
        )
    run, report = build_deterministic_discourse(
        corpus,
        created_at=corpus.created_at,
        quotation_evidence=quotation,
    )
    run_path, report_path, reused = persist_deterministic_discourse(
        run,
        report,
        corpus,
        destination,
        quotation_evidence=quotation,
    )
    emit(
        {
            "run": run.model_dump(mode="json"),
            "report": report.model_dump(mode="json"),
            "run_path": str(run_path),
            "report_path": str(report_path),
            "reused": reused,
        },
        structured,
    )
    return 0
