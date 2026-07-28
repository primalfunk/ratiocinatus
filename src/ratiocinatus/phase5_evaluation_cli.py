"""CLI operations for controlled Phase 5 discourse evaluation."""

from __future__ import annotations

from pathlib import Path

from .discourse_consolidation import load_discourse_consolidation
from .phase5_evaluation import (
    evaluate_phase5,
    load_phase5_evaluation,
    load_phase5_reference,
    persist_phase5_evaluation,
    validate_phase5_evaluation,
)
from .utterance_segmentation import load_utterance_corpus


def add_phase5_evaluation_parsers(actions) -> None:
    item = actions.add_parser("evaluate")
    item.add_argument("consolidation_root", type=Path)
    item.add_argument("utterance_corpus_root", type=Path)
    item.add_argument("reference", type=Path)
    item.add_argument("destination", type=Path)
    item = actions.add_parser("evaluation-validate")
    item.add_argument("evaluation_root", type=Path)
    item.add_argument("consolidation_root", type=Path)
    item.add_argument("utterance_corpus_root", type=Path)
    item.add_argument("reference", type=Path)
    item = actions.add_parser("evaluation-inspect")
    item.add_argument("evaluation_root", type=Path)


def run_phase5_evaluation_command(args, emit, structured: bool) -> int | None:
    if args.action not in {
        "evaluate",
        "evaluation-validate",
        "evaluation-inspect",
    }:
        return None
    if args.action == "evaluation-inspect":
        evaluation, report = load_phase5_evaluation(args.evaluation_root)
        emit(
            {
                "evaluation": evaluation.model_dump(mode="json"),
                "report": report.model_dump(mode="json"),
            },
            structured,
        )
        return 0
    _, corpus, _ = load_discourse_consolidation(args.consolidation_root)
    _, phase4, _ = load_utterance_corpus(args.utterance_corpus_root)
    reference = load_phase5_reference(args.reference)
    if args.action == "evaluation-validate":
        evaluation, report = load_phase5_evaluation(args.evaluation_root)
        validate_phase5_evaluation(
            evaluation, report, corpus, phase4, reference
        )
        emit(
            {"valid": True, "evaluation_id": evaluation.evaluation_id},
            structured,
        )
        return 0
    destination = args.destination.expanduser().resolve()
    protected = (
        args.consolidation_root.expanduser().resolve(strict=True),
        args.utterance_corpus_root.expanduser().resolve(strict=True),
        args.reference.expanduser().resolve(strict=True),
    )
    if any(
        destination == root or root in destination.parents
        for root in protected
    ):
        raise ValueError("evaluation output must not modify source evidence")
    evaluation, report = evaluate_phase5(
        corpus, phase4, reference, generated_at=corpus.created_at
    )
    evaluation, report, root, reused = persist_phase5_evaluation(
        evaluation,
        report,
        corpus,
        phase4,
        reference,
        destination,
    )
    emit(
        {
            "evaluation": evaluation.model_dump(mode="json"),
            "report": report.model_dump(mode="json"),
            "root": str(root),
            "reused": reused,
        },
        structured,
    )
    return 0
