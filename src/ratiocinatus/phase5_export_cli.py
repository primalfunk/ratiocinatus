"""CLI operations for portable Phase 5 export, reload, and recovery evidence."""

from __future__ import annotations

from pathlib import Path

from .argument_relation_construction import load_argument_relations
from .discourse_consolidation import load_discourse_consolidation
from .discourse_review import (
    load_discourse_propagation,
    load_discourse_review_ledger,
    load_discourse_review_queue,
)
from .lexical_example_quotation_construction import (
    load_lexical_example_quotation,
)
from .phase5_evaluation import (
    load_phase5_evaluation,
    load_phase5_reference,
)
from .phase5_export import (
    Phase5PortableArtifactSet,
    export_phase5_corpus,
    load_phase5_export,
    reload_phase5_export,
    validate_phase5_export,
)
from .phase5_foundation import validate_discourse_corpus
from .phase5_recovery import load_phase5_recovery
from .procedural_state_construction import load_procedural_state
from .question_answer_construction import load_question_answers
from .utterance_segmentation import load_utterance_corpus


def add_phase5_export_parsers(actions) -> None:
    item = actions.add_parser("export")
    item.add_argument("consolidation_root", type=Path)
    item.add_argument("question_answer_root", type=Path)
    item.add_argument("argument_relation_root", type=Path)
    item.add_argument("lexical_structure_root", type=Path)
    item.add_argument("procedural_state_root", type=Path)
    item.add_argument("ledger_root", type=Path)
    item.add_argument("queue_root", type=Path)
    item.add_argument("propagation_root", type=Path)
    item.add_argument("evaluation_root", type=Path)
    item.add_argument("controlled_reference", type=Path)
    item.add_argument("utterance_corpus_root", type=Path)
    item.add_argument("schemas_root", type=Path)
    item.add_argument("destination", type=Path)
    item = actions.add_parser("export-validate")
    item.add_argument("export_root", type=Path)
    item = actions.add_parser("export-reload")
    item.add_argument("export_root", type=Path)
    item = actions.add_parser("recovery-inspect")
    item.add_argument("recovery_report", type=Path)


def run_phase5_export_command(args, emit, structured: bool) -> int | None:
    if args.action not in {
        "export",
        "export-validate",
        "export-reload",
        "recovery-inspect",
    }:
        return None
    if args.action == "export-validate":
        report = validate_phase5_export(args.export_root)
        emit(report, structured)
        return 0 if report.status == "valid" else 3
    if args.action == "export-reload":
        manifest, report = load_phase5_export(args.export_root)
        artifacts = reload_phase5_export(args.export_root)
        emit(
            {
                "manifest": manifest.model_dump(mode="json"),
                "validation": report.model_dump(mode="json"),
                "artifact_paths": tuple(sorted(artifacts)),
                "provider_execution_used": False,
            },
            structured,
        )
        return 0
    if args.action == "recovery-inspect":
        emit(load_phase5_recovery(args.recovery_report), structured)
        return 0
    consolidation, corpus, consolidation_report = (
        load_discourse_consolidation(args.consolidation_root)
    )
    question, question_report = load_question_answers(
        args.question_answer_root
    )
    argument, argument_report = load_argument_relations(
        args.argument_relation_root
    )
    lexical, lexical_report = load_lexical_example_quotation(
        args.lexical_structure_root
    )
    procedural, procedural_report = load_procedural_state(
        args.procedural_state_root
    )
    ledger = load_discourse_review_ledger(args.ledger_root)
    queue = load_discourse_review_queue(args.queue_root)
    propagation, propagation_report = load_discourse_propagation(
        args.propagation_root
    )
    evaluation, evaluation_report = load_phase5_evaluation(
        args.evaluation_root
    )
    reference = load_phase5_reference(args.controlled_reference)
    _, phase4, _ = load_utterance_corpus(args.utterance_corpus_root)
    integrity = validate_discourse_corpus(
        corpus, phase4, checked_at=corpus.created_at
    )
    artifacts = Phase5PortableArtifactSet(
        consolidation=consolidation,
        corpus=corpus,
        consolidation_report=consolidation_report,
        question_answers=question,
        question_answer_report=question_report,
        argument_relations=argument,
        argument_relation_report=argument_report,
        lexical_structures=lexical,
        lexical_structure_report=lexical_report,
        procedural_state=procedural,
        procedural_state_report=procedural_report,
        review_ledger=ledger,
        review_queue=queue,
        propagation=propagation,
        propagation_report=propagation_report,
        controlled_reference=reference,
        evaluation=evaluation,
        evaluation_report=evaluation_report,
        integrity_result=integrity,
    )
    destination = args.destination.expanduser().resolve()
    protected = tuple(
        value.expanduser().resolve(strict=True)
        for value in (
            args.consolidation_root,
            args.question_answer_root,
            args.argument_relation_root,
            args.lexical_structure_root,
            args.procedural_state_root,
            args.ledger_root,
            args.queue_root,
            args.propagation_root,
            args.evaluation_root,
            args.controlled_reference,
            args.utterance_corpus_root,
        )
    )
    if any(
        destination == root or root in destination.parents
        for root in protected
    ):
        raise ValueError("portable export must not modify source evidence")
    manifest, report, root, reused = export_phase5_corpus(
        artifacts,
        destination,
        args.schemas_root,
        created_at=corpus.created_at,
    )
    emit(
        {
            "manifest": manifest.model_dump(mode="json"),
            "validation": report.model_dump(mode="json"),
            "root": str(root),
            "reused": reused,
        },
        structured,
    )
    return 0
