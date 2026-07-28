"""CLI surface for Phase 5 append-only review and correction propagation."""

from __future__ import annotations

from datetime import timezone
from pathlib import Path

from .discourse_consolidation import load_discourse_consolidation
from .discourse_review import (
    append_discourse_review_action,
    build_discourse_propagation,
    build_discourse_review_queue,
    create_discourse_review_ledger,
    load_discourse_propagation,
    load_discourse_review_ledger,
    load_discourse_review_queue,
    persist_discourse_propagation,
    persist_discourse_review_ledger,
    persist_discourse_review_queue,
    validate_discourse_propagation,
    validate_discourse_review_ledger,
)
from .phase5_contracts import DiscourseReviewStatus
from .phase5_review_contracts import DiscourseReviewActionKind
from .utterance_segmentation import load_utterance_corpus


def add_phase5_review_parsers(actions) -> None:
    item = actions.add_parser("review-init")
    item.add_argument("consolidation_root", type=Path)
    item.add_argument("destination", type=Path)
    item = actions.add_parser("review-append")
    item.add_argument("consolidation_root", type=Path)
    item.add_argument("ledger_root", type=Path)
    item.add_argument("destination", type=Path)
    item.add_argument(
        "review_action",
        choices=tuple(value.value for value in DiscourseReviewActionKind),
    )
    item.add_argument("target_artifact_id", nargs="+")
    item.add_argument("--author", required=True)
    item.add_argument("--rationale", required=True)
    item.add_argument("--certainty", type=float, required=True)
    item.add_argument(
        "--resulting-status",
        choices=tuple(value.value for value in DiscourseReviewStatus),
        required=True,
    )
    item.add_argument("--evidence", action="append", required=True)
    item.add_argument("--prior", action="append", required=True)
    item.add_argument("--proposed", action="append", required=True)
    item = actions.add_parser("review-inspect")
    item.add_argument("ledger_root", type=Path)
    item = actions.add_parser("review-queue-build")
    item.add_argument("consolidation_root", type=Path)
    item.add_argument("utterance_corpus_root", type=Path)
    item.add_argument("ledger_root", type=Path)
    item.add_argument("destination", type=Path)
    item.add_argument("--propagation-root", type=Path)
    item = actions.add_parser("review-queue-inspect")
    item.add_argument("queue_root", type=Path)
    item = actions.add_parser("propagation-build")
    item.add_argument("predecessor_utterance_corpus_root", type=Path)
    item.add_argument("successor_utterance_corpus_root", type=Path)
    item.add_argument("consolidation_root", type=Path)
    item.add_argument("destination", type=Path)
    item.add_argument(
        "--identity-context-utterance", action="append", default=[]
    )
    item = actions.add_parser("propagation-validate")
    item.add_argument("propagation_root", type=Path)
    item.add_argument("predecessor_utterance_corpus_root", type=Path)
    item.add_argument("successor_utterance_corpus_root", type=Path)
    item.add_argument("consolidation_root", type=Path)
    item = actions.add_parser("propagation-inspect")
    item.add_argument("propagation_root", type=Path)


def _pairs(values: list[str]) -> dict[str, str]:
    result = {}
    for value in values:
        if "=" not in value:
            raise ValueError("review state entries must use key=value")
        key, content = value.split("=", 1)
        if not key:
            raise ValueError("review state entry key cannot be empty")
        result[key] = content
    return result


def _protected(destination: Path, *sources: Path) -> None:
    target = destination.expanduser().resolve()
    roots = tuple(item.expanduser().resolve(strict=True) for item in sources)
    if any(target == root or root in target.parents for root in roots):
        raise ValueError("review output must not modify source evidence")


def run_phase5_review_command(args, emit, structured: bool) -> int | None:
    actions = {
        "review-init",
        "review-append",
        "review-inspect",
        "review-queue-build",
        "review-queue-inspect",
        "propagation-build",
        "propagation-validate",
        "propagation-inspect",
    }
    if args.action not in actions:
        return None
    if args.action == "review-inspect":
        emit(load_discourse_review_ledger(args.ledger_root), structured)
        return 0
    if args.action == "review-queue-inspect":
        emit(load_discourse_review_queue(args.queue_root), structured)
        return 0
    if args.action == "propagation-inspect":
        run, report = load_discourse_propagation(args.propagation_root)
        emit(
            {
                "run": run.model_dump(mode="json"),
                "report": report.model_dump(mode="json"),
            },
            structured,
        )
        return 0
    _, corpus, _ = load_discourse_consolidation(args.consolidation_root)
    if args.action == "review-init":
        _protected(args.destination, args.consolidation_root)
        ledger = create_discourse_review_ledger(corpus)
        ledger, root, reused = persist_discourse_review_ledger(
            ledger, corpus, args.destination
        )
        emit(
            {
                "ledger": ledger.model_dump(mode="json"),
                "root": str(root),
                "reused": reused,
            },
            structured,
        )
        return 0
    if args.action == "review-append":
        _protected(
            args.destination, args.consolidation_root, args.ledger_root
        )
        ledger = load_discourse_review_ledger(args.ledger_root)
        reviewed_at = corpus.created_at.astimezone(timezone.utc)
        successor = append_discourse_review_action(
            ledger,
            corpus,
            DiscourseReviewActionKind(args.review_action),
            tuple(args.target_artifact_id),
            prior_state=_pairs(args.prior),
            proposed_state=_pairs(args.proposed),
            author=args.author,
            reviewed_at=reviewed_at,
            rationale=args.rationale,
            evidence_references=tuple(args.evidence),
            certainty=args.certainty,
            resulting_review_status=DiscourseReviewStatus(
                args.resulting_status
            ),
        )
        successor, root, reused = persist_discourse_review_ledger(
            successor, corpus, args.destination
        )
        emit(
            {
                "ledger": successor.model_dump(mode="json"),
                "root": str(root),
                "reused": reused,
            },
            structured,
        )
        return 0
    if args.action == "review-queue-build":
        _protected(
            args.destination,
            args.consolidation_root,
            args.utterance_corpus_root,
            args.ledger_root,
        )
        _, phase4, _ = load_utterance_corpus(args.utterance_corpus_root)
        ledger = load_discourse_review_ledger(args.ledger_root)
        propagation = (
            load_discourse_propagation(args.propagation_root)[0]
            if args.propagation_root
            else None
        )
        queue = build_discourse_review_queue(
            corpus, phase4, ledger, propagation=propagation
        )
        queue, root, reused = persist_discourse_review_queue(
            queue, args.destination
        )
        emit(
            {
                "queue": queue.model_dump(mode="json"),
                "root": str(root),
                "reused": reused,
            },
            structured,
        )
        return 0
    _, predecessor, _ = load_utterance_corpus(
        args.predecessor_utterance_corpus_root
    )
    _, successor, _ = load_utterance_corpus(
        args.successor_utterance_corpus_root
    )
    if args.action == "propagation-validate":
        run, report = load_discourse_propagation(args.propagation_root)
        validate_discourse_propagation(
            run, report, predecessor, successor, corpus
        )
        emit(
            {"valid": True, "propagation_run_id": run.propagation_run_id},
            structured,
        )
        return 0
    _protected(
        args.destination,
        args.predecessor_utterance_corpus_root,
        args.successor_utterance_corpus_root,
        args.consolidation_root,
    )
    run, report = build_discourse_propagation(
        predecessor,
        successor,
        corpus,
        created_at=successor.created_at,
        identity_specific_context_utterance_ids=tuple(
            args.identity_context_utterance
        ),
    )
    run, report, root, reused = persist_discourse_propagation(
        run,
        report,
        predecessor,
        successor,
        corpus,
        args.destination,
    )
    emit(
        {
            "run": run.model_dump(mode="json"),
            "report": report.model_dump(mode="json"),
            "root": str(root),
            "reused": reused,
        },
        structured,
    )
    return 0
