"""CLI operations for initial Phase 4 utterance corpora."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from .utterance_analysis import (
    analyze_utterance_corpus,
    load_utterance_analysis,
    persist_utterance_analysis,
    validate_utterance_analysis,
)
from .utterance_relations import (
    build_utterance_relations,
    load_utterance_relations,
    persist_utterance_relations,
    validate_utterance_relations,
)
from .turn_repair import (
    build_turn_repair_run,
    decide_turn_repair,
    load_turn_repair_run,
    persist_turn_repair_run,
    validate_turn_repair_run,
)
from .turn_repair_contracts import TurnRepairDecisionDisposition
from .quotation_evidence import (
    build_quotation_evidence,
    load_quotation_evidence,
    persist_quotation_evidence,
    validate_quotation_evidence,
)
from .utterance_view_contracts import SpeakerAttributedViewKind
from .utterance_views import (
    build_speaker_attributed_views,
    load_speaker_attributed_views,
    persist_speaker_attributed_views,
    validate_speaker_attributed_views,
)
from .context_window_contracts import ContextWindowKind, ContextWindowPolicy
from .context_windows import (
    build_context_windows,
    load_context_windows,
    persist_context_windows,
    validate_context_windows,
)
from .phase4_propagation import (
    Phase4ArtifactSet,
    build_phase4_propagation,
    load_phase4_propagation,
    persist_phase4_propagation,
    validate_phase4_propagation,
)
from .phase4_review import (
    append_review_action,
    build_review_queue,
    create_review_ledger,
    load_review_ledger,
    load_review_queue,
    persist_review_ledger,
    persist_review_queue,
    validate_review_ledger,
)
from .phase4_review_contracts import (
    ReviewActionKind,
    ReviewerCertainty,
)

from .kernel import load_contract
from .phase3_contracts import DiarizationRun
from .speaker_transcript import load_speaker_labeled_transcript
from .transcript_contracts import TranscriptAssembly
from .utterance_segmentation import (
    build_utterance_corpus,
    load_utterance_corpus,
    persist_utterance_corpus,
    validate_utterance_corpus,
)
from .phase4_contracts import UtteranceSegmentationPolicy


def add_utterance_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("utterance")
    actions = parser.add_subparsers(dest="action", required=True)
    build = actions.add_parser("build")
    build.add_argument("assembly_root", type=Path)
    build.add_argument("speaker_transcript_root", type=Path)
    build.add_argument("diarization_root", type=Path)
    build.add_argument("destination", type=Path)
    build.add_argument(
        "--maximum-gap-microseconds", type=int, default=750_000
    )
    validate = actions.add_parser("validate")
    validate.add_argument("utterance_corpus_root", type=Path)
    validate.add_argument("assembly_root", type=Path)
    validate.add_argument("speaker_transcript_root", type=Path)
    validate.add_argument("diarization_root", type=Path)
    for action in ("inspect", "list"):
        item = actions.add_parser(action)
        item.add_argument("utterance_corpus_root", type=Path)
    analyze = actions.add_parser("analyze")
    analyze.add_argument("utterance_corpus_root", type=Path)
    analyze.add_argument("assembly_root", type=Path)
    analyze.add_argument("destination", type=Path)
    analysis_validate = actions.add_parser("analysis-validate")
    analysis_validate.add_argument("utterance_analysis_root", type=Path)
    analysis_validate.add_argument("utterance_corpus_root", type=Path)
    analysis_validate.add_argument("assembly_root", type=Path)
    for action in (
        "analysis-inspect",
        "list-incomplete",
        "list-disfluencies",
        "list-self-repairs",
    ):
        item = actions.add_parser(action)
        item.add_argument("utterance_analysis_root", type=Path)
    relate = actions.add_parser("relate")
    relate.add_argument("utterance_corpus_root", type=Path)
    relate.add_argument("utterance_analysis_root", type=Path)
    relate.add_argument("diarization_root", type=Path)
    relate.add_argument("destination", type=Path)
    relation_validate = actions.add_parser("relations-validate")
    relation_validate.add_argument("utterance_relation_root", type=Path)
    relation_validate.add_argument("utterance_corpus_root", type=Path)
    relation_validate.add_argument("utterance_analysis_root", type=Path)
    relation_validate.add_argument("diarization_root", type=Path)
    for action in (
        "relations-inspect",
        "list-interruptions",
        "list-continuations",
        "list-overlaps",
        "list-adjacencies",
    ):
        item = actions.add_parser(action)
        item.add_argument("utterance_relation_root", type=Path)
    repair_build = actions.add_parser("repair-build")
    repair_build.add_argument("utterance_corpus_root", type=Path)
    repair_build.add_argument("assembly_root", type=Path)
    repair_build.add_argument("speaker_transcript_root", type=Path)
    repair_build.add_argument("diarization_root", type=Path)
    repair_build.add_argument("destination", type=Path)
    repair_validate = actions.add_parser("repair-validate")
    repair_validate.add_argument("turn_repair_root", type=Path)
    repair_validate.add_argument("utterance_corpus_root", type=Path)
    repair_validate.add_argument("assembly_root", type=Path)
    repair_validate.add_argument("speaker_transcript_root", type=Path)
    repair_validate.add_argument("diarization_root", type=Path)
    repair_decide = actions.add_parser("repair-decide")
    repair_decide.add_argument("turn_repair_root", type=Path)
    repair_decide.add_argument("utterance_corpus_root", type=Path)
    repair_decide.add_argument("assembly_root", type=Path)
    repair_decide.add_argument("speaker_transcript_root", type=Path)
    repair_decide.add_argument("diarization_root", type=Path)
    repair_decide.add_argument("destination", type=Path)
    repair_decide.add_argument("proposal_id")
    repair_decide.add_argument(
        "disposition", choices=("accepted", "rejected", "deferred")
    )
    repair_decide.add_argument("--author", required=True)
    repair_decide.add_argument("--rationale", required=True)
    repair_decide.add_argument("--decided-at", required=True)
    repair_decide.add_argument(
        "--evidence-reference", action="append", required=True
    )
    for action in (
        "repair-inspect",
        "list-turn-conflicts",
        "list-turn-proposals",
        "list-turn-successors",
    ):
        item = actions.add_parser(action)
        item.add_argument("turn_repair_root", type=Path)
    quotation_build = actions.add_parser("quotation-build")
    quotation_build.add_argument("utterance_corpus_root", type=Path)
    quotation_build.add_argument("assembly_root", type=Path)
    quotation_build.add_argument("destination", type=Path)
    quotation_validate = actions.add_parser("quotation-validate")
    quotation_validate.add_argument("quotation_root", type=Path)
    quotation_validate.add_argument("utterance_corpus_root", type=Path)
    quotation_validate.add_argument("assembly_root", type=Path)
    for action in (
        "quotation-inspect",
        "list-quotations",
        "list-embedded-sources",
    ):
        item = actions.add_parser(action)
        item.add_argument("quotation_root", type=Path)
    view_build = actions.add_parser("view-build")
    for name in (
        "utterance_corpus_root",
        "utterance_analysis_root",
        "utterance_relation_root",
        "turn_repair_root",
        "quotation_root",
        "destination",
    ):
        view_build.add_argument(name, type=Path)
    view_validate = actions.add_parser("view-validate")
    for name in (
        "view_root",
        "utterance_corpus_root",
        "utterance_analysis_root",
        "utterance_relation_root",
        "turn_repair_root",
        "quotation_root",
    ):
        view_validate.add_argument(name, type=Path)
    for action in ("view-inspect", "view-list"):
        item = actions.add_parser(action)
        item.add_argument("view_root", type=Path)
    view_render = actions.add_parser("view-render")
    view_render.add_argument("view_root", type=Path)
    view_render.add_argument(
        "kind", choices=tuple(item.value for item in SpeakerAttributedViewKind)
    )
    context_build = actions.add_parser("context-build")
    for name in (
        "view_root",
        "utterance_corpus_root",
        "utterance_analysis_root",
        "utterance_relation_root",
        "turn_repair_root",
        "quotation_root",
        "destination",
    ):
        context_build.add_argument(name, type=Path)
    context_build.add_argument("--maximum-utterances", type=int, default=12)
    context_build.add_argument("--maximum-tokens", type=int, default=1_200)
    context_build.add_argument(
        "--maximum-source-microseconds", type=int, default=120_000_000
    )
    context_validate = actions.add_parser("context-validate")
    for name in (
        "context_root",
        "view_root",
        "utterance_corpus_root",
        "utterance_analysis_root",
        "utterance_relation_root",
        "turn_repair_root",
        "quotation_root",
    ):
        context_validate.add_argument(name, type=Path)
    for action in ("context-inspect", "context-list", "list-truncated-context"):
        item = actions.add_parser(action)
        item.add_argument("context_root", type=Path)
    context_show = actions.add_parser("context-show")
    context_show.add_argument("context_root", type=Path)
    context_show.add_argument("target_utterance_id")
    context_show.add_argument(
        "kind", choices=tuple(item.value for item in ContextWindowKind)
    )
    propagation_build = actions.add_parser("propagation-build")
    for prefix in ("predecessor", "successor"):
        for suffix in (
            "corpus_root",
            "analysis_root",
            "relation_root",
            "repair_root",
            "quotation_root",
            "view_root",
            "context_root",
        ):
            propagation_build.add_argument(f"{prefix}_{suffix}", type=Path)
    propagation_build.add_argument("destination", type=Path)
    propagation_validate = actions.add_parser("propagation-validate")
    propagation_validate.add_argument("propagation_root", type=Path)
    for prefix in ("predecessor", "successor"):
        for suffix in (
            "corpus_root",
            "analysis_root",
            "relation_root",
            "repair_root",
            "quotation_root",
            "view_root",
            "context_root",
        ):
            propagation_validate.add_argument(f"{prefix}_{suffix}", type=Path)
    for action in ("propagation-inspect", "list-propagation-impacts"):
        item = actions.add_parser(action)
        item.add_argument("propagation_root", type=Path)
    review_create = actions.add_parser("review-create")
    review_create.add_argument("utterance_corpus_root", type=Path)
    review_create.add_argument("view_root", type=Path)
    review_create.add_argument("destination", type=Path)
    review_append = actions.add_parser("review-append")
    review_append.add_argument("review_root", type=Path)
    review_append.add_argument("utterance_corpus_root", type=Path)
    review_append.add_argument("view_root", type=Path)
    review_append.add_argument("destination", type=Path)
    review_append.add_argument("review_action", choices=tuple(item.value for item in ReviewActionKind))
    review_append.add_argument("--target-utterance", action="append", required=True)
    review_append.add_argument("--target-artifact", action="append", required=True)
    review_append.add_argument("--prior-state", action="append", required=True)
    review_append.add_argument("--proposed-state", action="append", required=True)
    review_append.add_argument("--author", required=True)
    review_append.add_argument("--reviewed-at", required=True)
    review_append.add_argument("--rationale", required=True)
    review_append.add_argument("--evidence-reference", action="append", required=True)
    review_append.add_argument(
        "--certainty", choices=tuple(item.value for item in ReviewerCertainty), required=True
    )
    for action in ("review-inspect", "list-review-actions"):
        item = actions.add_parser(action)
        item.add_argument("review_root", type=Path)
    review_queue = actions.add_parser("review-queue")
    review_queue.add_argument("review_root", type=Path)
    for suffix in (
        "corpus_root",
        "analysis_root",
        "relation_root",
        "repair_root",
        "quotation_root",
        "view_root",
        "context_root",
    ):
        review_queue.add_argument(f"current_{suffix}", type=Path)
    review_queue.add_argument("destination", type=Path)
    review_queue.add_argument("--propagation-root", type=Path)
    for action in ("review-queue-inspect", "list-review-queue"):
        item = actions.add_parser(action)
        item.add_argument("review_queue_root", type=Path)
def _lineage(
    assembly_root: Path, speaker_root: Path, diarization_root: Path
):
    assembly_root = assembly_root.expanduser().resolve(strict=True)
    assembly = load_contract(
        (assembly_root / "assembly.json").read_bytes(), TranscriptAssembly
    )
    speaker_view, _ = load_speaker_labeled_transcript(speaker_root)
    diarization_root = diarization_root.expanduser().resolve(strict=True)
    diarization = load_contract(
        (diarization_root / "run.json").read_bytes(), DiarizationRun
    )
    return assembly, speaker_view, diarization

def _phase4_artifact_set(args, prefix: str) -> Phase4ArtifactSet:
    corpus_root = getattr(args, f"{prefix}_corpus_root")
    utterance_run, corpus, _ = load_utterance_corpus(corpus_root)
    analysis, _ = load_utterance_analysis(
        getattr(args, f"{prefix}_analysis_root")
    )
    relations, _ = load_utterance_relations(
        getattr(args, f"{prefix}_relation_root")
    )
    repair, _ = load_turn_repair_run(getattr(args, f"{prefix}_repair_root"))
    quotation, _ = load_quotation_evidence(
        getattr(args, f"{prefix}_quotation_root")
    )
    views, _ = load_speaker_attributed_views(
        getattr(args, f"{prefix}_view_root")
    )
    contexts, _ = load_context_windows(
        getattr(args, f"{prefix}_context_root")
    )
    return Phase4ArtifactSet(
        utterance_run,
        corpus,
        analysis,
        relations,
        repair,
        quotation,
        views,
        contexts,
    )


def _state_entries(values: list[str]) -> dict[str, str]:
    result = {}
    for value in values:
        if "=" not in value:
            raise ValueError("review state entries must use KEY=VALUE")
        key, item = value.split("=", 1)
        if not key or key in result:
            raise ValueError("review state keys must be non-empty and unique")
        result[key] = item
    return result

def run_utterance_command(args, emit, structured: bool) -> int | None:
    if args.command != "utterance":
        return None
    if args.action in {"review-queue-inspect", "list-review-queue"}:
        report = load_review_queue(args.review_queue_root)
        emit(
            report.items if args.action == "list-review-queue" else report,
            structured,
        )
        return 0
    if args.action == "review-queue":
        ledger = load_review_ledger(args.review_root)
        artifacts = _phase4_artifact_set(args, "current")
        propagation = None
        if args.propagation_root is not None:
            propagation, _ = load_phase4_propagation(args.propagation_root)
        report = build_review_queue(
            ledger, artifacts, propagation=propagation
        )
        destination = args.destination.expanduser().resolve()
        protected = tuple(
            getattr(args, f"current_{suffix}").expanduser().resolve(strict=True)
            for suffix in (
                "corpus_root",
                "analysis_root",
                "relation_root",
                "repair_root",
                "quotation_root",
                "view_root",
                "context_root",
            )
        ) + (args.review_root.expanduser().resolve(strict=True),)
        if any(
            destination == root or root in destination.parents
            for root in protected
        ):
            raise ValueError("review queue output must not modify evidence")
        persisted = persist_review_queue(report, destination)
        emit(
            {
                "report": persisted[0].model_dump(mode="json"),
                "review_queue_root": str(persisted[1]),
                "reused": persisted[2],
            },
            structured,
        )
        return 0
    if args.action in {"propagation-inspect", "list-propagation-impacts"}:
        run, report = load_phase4_propagation(args.propagation_root)
        if args.action == "list-propagation-impacts":
            emit(run.impacts, structured)
        else:
            emit(
                {
                    "propagation": run.model_dump(mode="json"),
                    "report": report.model_dump(mode="json"),
                },
                structured,
            )
        return 0
    if args.action in {"propagation-build", "propagation-validate"}:
        predecessor = _phase4_artifact_set(args, "predecessor")
        successor = _phase4_artifact_set(args, "successor")
        if args.action == "propagation-validate":
            run, report = load_phase4_propagation(args.propagation_root)
            validate_phase4_propagation(
                run, predecessor, successor, report=report
            )
            emit(
                {
                    "valid": True,
                    "propagation_run_id": run.propagation_run_id,
                },
                structured,
            )
            return 0
        destination = args.destination.expanduser().resolve()
        roots = tuple(
            getattr(args, f"{prefix}_{suffix}").expanduser().resolve(strict=True)
            for prefix in ("predecessor", "successor")
            for suffix in (
                "corpus_root",
                "analysis_root",
                "relation_root",
                "repair_root",
                "quotation_root",
                "view_root",
                "context_root",
            )
        )
        if any(
            destination == root or root in destination.parents for root in roots
        ):
            raise ValueError(
                "propagation output must not modify predecessor or successor evidence"
            )
        run = build_phase4_propagation(predecessor, successor)
        persisted = persist_phase4_propagation(
            run, predecessor, successor, destination
        )
        emit(
            {
                "propagation": persisted[0].model_dump(mode="json"),
                "report": persisted[1].model_dump(mode="json"),
                "propagation_root": str(persisted[2]),
                "reused": persisted[3],
            },
            structured,
        )
        return 0
    if args.action in {"review-inspect", "list-review-actions"}:
        ledger = load_review_ledger(args.review_root)
        emit(
            ledger.actions if args.action == "list-review-actions" else ledger,
            structured,
        )
        return 0
    if args.action in {"review-create", "review-append"}:
        utterance_run, corpus, _ = load_utterance_corpus(
            args.utterance_corpus_root
        )
        views, _ = load_speaker_attributed_views(args.view_root)
        if args.action == "review-create":
            ledger = create_review_ledger(corpus, views)
        else:
            ledger = load_review_ledger(args.review_root)
            validate_review_ledger(ledger, corpus, views)
            ledger = append_review_action(
                ledger,
                corpus,
                views,
                ReviewActionKind(args.review_action),
                tuple(args.target_utterance),
                target_artifact_ids=tuple(args.target_artifact),
                prior_state=_state_entries(args.prior_state),
                proposed_state=_state_entries(args.proposed_state),
                author=args.author,
                reviewed_at=datetime.fromisoformat(args.reviewed_at),
                rationale=args.rationale,
                evidence_references=tuple(args.evidence_reference),
                reviewer_certainty=ReviewerCertainty(args.certainty),
            )
        destination = args.destination.expanduser().resolve()
        protected = (
            args.utterance_corpus_root.expanduser().resolve(strict=True),
            args.view_root.expanduser().resolve(strict=True),
        )
        if any(
            destination == root or root in destination.parents
            for root in protected
        ):
            raise ValueError("review output must not modify machine evidence")
        persisted = persist_review_ledger(ledger, corpus, views, destination)
        emit(
            {
                "ledger": persisted[0].model_dump(mode="json"),
                "review_root": str(persisted[1]),
                "reused": persisted[2],
            },
            structured,
        )
        return 0
    if args.action in {
        "context-inspect",
        "context-list",
        "context-show",
        "list-truncated-context",
    }:
        bundle, report = load_context_windows(args.context_root)
        if args.action == "context-list":
            emit(bundle.windows, structured)
        elif args.action == "list-truncated-context":
            emit(tuple(item for item in bundle.windows if item.truncated), structured)
        elif args.action == "context-show":
            window = next(
                item
                for item in bundle.windows
                if item.target_utterance_id == args.target_utterance_id
                and item.kind.value == args.kind
            )
            emit(window, structured)
        else:
            emit(
                {
                    "bundle": bundle.model_dump(mode="json"),
                    "report": report.model_dump(mode="json"),
                },
                structured,
            )
        return 0
    if args.action in {"context-build", "context-validate"}:
        view_bundle, _ = load_speaker_attributed_views(args.view_root)
        utterance_run, corpus, _ = load_utterance_corpus(
            args.utterance_corpus_root
        )
        analysis, _ = load_utterance_analysis(args.utterance_analysis_root)
        relations, _ = load_utterance_relations(args.utterance_relation_root)
        repair, _ = load_turn_repair_run(args.turn_repair_root)
        quotation, _ = load_quotation_evidence(args.quotation_root)
        sources = (
            utterance_run,
            corpus,
            analysis,
            relations,
            repair,
            quotation,
        )
        if args.action == "context-validate":
            bundle, report = load_context_windows(args.context_root)
            validate_context_windows(
                bundle, view_bundle, *sources, report=report
            )
            emit(
                {
                    "valid": True,
                    "context_bundle_id": bundle.context_bundle_id,
                    "utterance_corpus_id": corpus.corpus_id,
                },
                structured,
            )
            return 0
        destination = args.destination.expanduser().resolve()
        protected = tuple(
            getattr(args, name).expanduser().resolve(strict=True)
            for name in (
                "view_root",
                "utterance_corpus_root",
                "utterance_analysis_root",
                "utterance_relation_root",
                "turn_repair_root",
                "quotation_root",
            )
        )
        if any(
            destination == root or root in destination.parents
            for root in protected
        ):
            raise ValueError(
                "context-window output must not modify source evidence"
            )
        policy = ContextWindowPolicy(
            maximum_utterance_count=args.maximum_utterances,
            maximum_token_estimate=args.maximum_tokens,
            maximum_source_duration_microseconds=(
                args.maximum_source_microseconds
            ),
        )
        bundle = build_context_windows(
            view_bundle, *sources, policy=policy
        )
        persisted = persist_context_windows(
            bundle, view_bundle, *sources, destination
        )
        emit(
            {
                "bundle": persisted[0].model_dump(mode="json"),
                "report": persisted[1].model_dump(mode="json"),
                "context_window_root": str(persisted[2]),
                "reused": persisted[3],
            },
            structured,
        )
        return 0
    if args.action in {"view-inspect", "view-list", "view-render"}:
        bundle, report = load_speaker_attributed_views(args.view_root)
        if args.action == "view-list":
            emit(bundle.views, structured)
        elif args.action == "view-render":
            view = next(
                item for item in bundle.views if item.kind.value == args.kind
            )
            emit(view if structured else view.rendered_text, structured)
        else:
            emit(
                {
                    "bundle": bundle.model_dump(mode="json"),
                    "report": report.model_dump(mode="json"),
                },
                structured,
            )
        return 0
    if args.action in {"view-build", "view-validate"}:
        utterance_run, corpus, _ = load_utterance_corpus(
            args.utterance_corpus_root
        )
        analysis, _ = load_utterance_analysis(args.utterance_analysis_root)
        relations, _ = load_utterance_relations(
            args.utterance_relation_root
        )
        repair, _ = load_turn_repair_run(args.turn_repair_root)
        quotation, _ = load_quotation_evidence(args.quotation_root)
        sources = (
            utterance_run,
            corpus,
            analysis,
            relations,
            repair,
            quotation,
        )
        if args.action == "view-validate":
            bundle, report = load_speaker_attributed_views(args.view_root)
            validate_speaker_attributed_views(
                bundle, *sources, report=report
            )
            emit(
                {
                    "valid": True,
                    "bundle_id": bundle.bundle_id,
                    "utterance_corpus_id": corpus.corpus_id,
                },
                structured,
            )
            return 0
        destination = args.destination.expanduser().resolve()
        protected = tuple(
            getattr(args, name).expanduser().resolve(strict=True)
            for name in (
                "utterance_corpus_root",
                "utterance_analysis_root",
                "utterance_relation_root",
                "turn_repair_root",
                "quotation_root",
            )
        )
        if any(
            destination == root or root in destination.parents
            for root in protected
        ):
            raise ValueError(
                "transcript-view output must not modify source evidence"
            )
        bundle = build_speaker_attributed_views(*sources)
        persisted = persist_speaker_attributed_views(
            bundle, *sources, destination
        )
        emit(
            {
                "bundle": persisted[0].model_dump(mode="json"),
                "report": persisted[1].model_dump(mode="json"),
                "utterance_view_root": str(persisted[2]),
                "reused": persisted[3],
            },
            structured,
        )
        return 0
    if args.action in {
        "quotation-inspect",
        "list-quotations",
        "list-embedded-sources",
    }:
        quotation, report = load_quotation_evidence(args.quotation_root)
        if args.action == "list-quotations":
            emit(quotation.quotations, structured)
        elif args.action == "list-embedded-sources":
            emit(quotation.embedded_sources, structured)
        else:
            emit(
                {
                    "quotation": quotation.model_dump(mode="json"),
                    "report": report.model_dump(mode="json"),
                },
                structured,
            )
        return 0
    if args.action in {"quotation-build", "quotation-validate"}:
        utterance_run, corpus, _ = load_utterance_corpus(
            args.utterance_corpus_root
        )
        assembly_root = args.assembly_root.expanduser().resolve(strict=True)
        assembly = load_contract(
            (assembly_root / "assembly.json").read_bytes(), TranscriptAssembly
        )
        if args.action == "quotation-validate":
            quotation, report = load_quotation_evidence(
                args.quotation_root
            )
            validate_quotation_evidence(
                quotation,
                utterance_run,
                corpus,
                assembly,
                report=report,
            )
            emit(
                {
                    "valid": True,
                    "quotation_run_id": quotation.quotation_run_id,
                    "utterance_corpus_id": corpus.corpus_id,
                },
                structured,
            )
            return 0
        destination = args.destination.expanduser().resolve()
        protected = (
            args.utterance_corpus_root.expanduser().resolve(strict=True),
            assembly_root,
        )
        if any(
            destination == root or root in destination.parents
            for root in protected
        ):
            raise ValueError(
                "quotation output must not modify source evidence"
            )
        quotation = build_quotation_evidence(
            utterance_run, corpus, assembly
        )
        persisted = persist_quotation_evidence(
            quotation, utterance_run, corpus, assembly, destination
        )
        emit(
            {
                "quotation": persisted[0].model_dump(mode="json"),
                "report": persisted[1].model_dump(mode="json"),
                "quotation_root": str(persisted[2]),
                "reused": persisted[3],
            },
            structured,
        )
        return 0
    if args.action in {
        "repair-inspect",
        "list-turn-conflicts",
        "list-turn-proposals",
        "list-turn-successors",
    }:
        repair, report = load_turn_repair_run(args.turn_repair_root)
        if args.action == "list-turn-conflicts":
            emit(repair.conflicts, structured)
        elif args.action == "list-turn-proposals":
            emit(repair.proposals, structured)
        elif args.action == "list-turn-successors":
            emit(repair.successors, structured)
        else:
            emit(
                {
                    "repair": repair.model_dump(mode="json"),
                    "report": report.model_dump(mode="json"),
                },
                structured,
            )
        return 0
    if args.action in {"repair-build", "repair-validate", "repair-decide"}:
        utterance_run, corpus, _ = load_utterance_corpus(
            args.utterance_corpus_root
        )
        assembly, speaker_view, diarization = _lineage(
            args.assembly_root,
            args.speaker_transcript_root,
            args.diarization_root,
        )
        if args.action == "repair-validate":
            repair, report = load_turn_repair_run(args.turn_repair_root)
            validate_turn_repair_run(
                repair,
                utterance_run,
                corpus,
                assembly,
                speaker_view,
                diarization,
                report=report,
            )
            emit(
                {
                    "valid": True,
                    "repair_run_id": repair.repair_run_id,
                    "utterance_corpus_id": corpus.corpus_id,
                },
                structured,
            )
            return 0
        if args.action == "repair-decide":
            repair, _ = load_turn_repair_run(args.turn_repair_root)
            validate_turn_repair_run(
                repair,
                utterance_run,
                corpus,
                assembly,
                speaker_view,
                diarization,
            )
            repair = decide_turn_repair(
                repair,
                args.proposal_id,
                TurnRepairDecisionDisposition(args.disposition),
                author=args.author,
                rationale=args.rationale,
                evidence_references=tuple(args.evidence_reference),
                decided_at=datetime.fromisoformat(args.decided_at),
            )
        else:
            repair = build_turn_repair_run(
                utterance_run, corpus, assembly, speaker_view, diarization
            )
        destination = args.destination.expanduser().resolve()
        protected = (
            args.utterance_corpus_root.expanduser().resolve(strict=True),
            args.assembly_root.expanduser().resolve(strict=True),
            args.speaker_transcript_root.expanduser().resolve(strict=True),
            args.diarization_root.expanduser().resolve(strict=True),
        )
        if any(
            destination == root or root in destination.parents
            for root in protected
        ):
            raise ValueError("turn-repair output must not modify source evidence")
        persisted = persist_turn_repair_run(
            repair,
            utterance_run,
            corpus,
            assembly,
            speaker_view,
            diarization,
            destination,
        )
        emit(
            {
                "repair": persisted[0].model_dump(mode="json"),
                "report": persisted[1].model_dump(mode="json"),
                "turn_repair_root": str(persisted[2]),
                "reused": persisted[3],
            },
            structured,
        )
        return 0
    if args.action in {
        "relations-inspect",
        "list-interruptions",
        "list-continuations",
        "list-overlaps",
        "list-adjacencies",
    }:
        relations, report = load_utterance_relations(
            args.utterance_relation_root
        )
        if args.action == "list-interruptions":
            emit(relations.interruptions, structured)
        elif args.action == "list-continuations":
            emit(relations.continuations, structured)
        elif args.action == "list-overlaps":
            emit(relations.overlaps, structured)
        elif args.action == "list-adjacencies":
            emit(relations.adjacencies, structured)
        else:
            emit(
                {
                    "relations": relations.model_dump(mode="json"),
                    "report": report.model_dump(mode="json"),
                },
                structured,
            )
        return 0
    if args.action in {"relate", "relations-validate"}:
        utterance_run, corpus, _ = load_utterance_corpus(
            args.utterance_corpus_root
        )
        analysis, _ = load_utterance_analysis(
            args.utterance_analysis_root
        )
        diarization_root = args.diarization_root.expanduser().resolve(
            strict=True
        )
        diarization = load_contract(
            (diarization_root / "run.json").read_bytes(), DiarizationRun
        )
        if args.action == "relations-validate":
            relations, report = load_utterance_relations(
                args.utterance_relation_root
            )
            validate_utterance_relations(
                relations,
                utterance_run,
                corpus,
                analysis,
                diarization,
                report=report,
            )
            emit(
                {
                    "valid": True,
                    "relation_run_id": relations.relation_run_id,
                    "utterance_corpus_id": corpus.corpus_id,
                },
                structured,
            )
            return 0
        destination = args.destination.expanduser().resolve()
        protected = (
            args.utterance_corpus_root.expanduser().resolve(strict=True),
            args.utterance_analysis_root.expanduser().resolve(strict=True),
            diarization_root,
        )
        if any(
            destination == root or root in destination.parents
            for root in protected
        ):
            raise ValueError(
                "relation output must not modify source evidence"
            )
        relations = build_utterance_relations(
            utterance_run, corpus, analysis, diarization
        )
        persisted = persist_utterance_relations(
            relations,
            utterance_run,
            corpus,
            analysis,
            diarization,
            destination,
        )
        emit(
            {
                "relations": persisted[0].model_dump(mode="json"),
                "report": persisted[1].model_dump(mode="json"),
                "utterance_relation_root": str(persisted[2]),
                "reused": persisted[3],
            },
            structured,
        )
        return 0
    if args.action in {
        "analysis-inspect",
        "list-incomplete",
        "list-disfluencies",
        "list-self-repairs",
    }:
        analysis, report = load_utterance_analysis(
            args.utterance_analysis_root
        )
        if args.action == "list-incomplete":
            emit(
                tuple(
                    item
                    for item in analysis.completeness_assessments
                    if item.classification.value != "complete"
                ),
                structured,
            )
        elif args.action == "list-disfluencies":
            emit(analysis.disfluency_spans, structured)
        elif args.action == "list-self-repairs":
            emit(analysis.self_repairs, structured)
        else:
            emit(
                {
                    "analysis": analysis.model_dump(mode="json"),
                    "report": report.model_dump(mode="json"),
                },
                structured,
            )
        return 0
    if args.action in {"analyze", "analysis-validate"}:
        utterance_run, corpus, _ = load_utterance_corpus(
            args.utterance_corpus_root
        )
        assembly_root = args.assembly_root.expanduser().resolve(strict=True)
        assembly = load_contract(
            (assembly_root / "assembly.json").read_bytes(),
            TranscriptAssembly,
        )
        if args.action == "analysis-validate":
            analysis, report = load_utterance_analysis(
                args.utterance_analysis_root
            )
            validate_utterance_analysis(
                analysis, utterance_run, corpus, assembly, report=report
            )
            emit(
                {
                    "valid": True,
                    "analysis_id": analysis.analysis_id,
                    "utterance_corpus_id": corpus.corpus_id,
                },
                structured,
            )
            return 0
        destination = args.destination.expanduser().resolve()
        protected = (
            args.utterance_corpus_root.expanduser().resolve(strict=True),
            assembly_root,
        )
        if any(
            destination == root or root in destination.parents
            for root in protected
        ):
            raise ValueError(
                "analysis output must not modify transcript or utterance evidence"
            )
        analysis = analyze_utterance_corpus(
            utterance_run, corpus, assembly
        )
        persisted = persist_utterance_analysis(
            analysis, utterance_run, corpus, assembly, destination
        )
        emit(
            {
                "analysis": persisted[0].model_dump(mode="json"),
                "report": persisted[1].model_dump(mode="json"),
                "utterance_analysis_root": str(persisted[2]),
                "reused": persisted[3],
            },
            structured,
        )
        return 0
    if args.action in {"inspect", "list"}:
        run, corpus, report = load_utterance_corpus(
            args.utterance_corpus_root
        )
        if args.action == "list":
            emit(corpus.utterances, structured)
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
    assembly, speaker_view, diarization = _lineage(
        args.assembly_root, args.speaker_transcript_root,
        args.diarization_root,
    )
    if args.action == "validate":
        run, corpus, report = load_utterance_corpus(
            args.utterance_corpus_root
        )
        result = validate_utterance_corpus(
            run, corpus, assembly, speaker_view, diarization, report=report
        )
        emit(result, structured)
        return 0
    destination = args.destination.expanduser().resolve()
    protected = (
        args.assembly_root.expanduser().resolve(strict=True),
        args.speaker_transcript_root.expanduser().resolve(strict=True),
        args.diarization_root.expanduser().resolve(strict=True),
    )
    if any(
        destination == root or root in destination.parents
        for root in protected
    ):
        raise ValueError(
            "utterance output must not modify Phase 2 or Phase 3 evidence"
        )
    policy = UtteranceSegmentationPolicy(
        maximum_gap_microseconds=args.maximum_gap_microseconds
    )
    run, corpus = build_utterance_corpus(
        assembly, speaker_view, diarization, policy=policy
    )
    persisted = persist_utterance_corpus(
        run, corpus, assembly, speaker_view, diarization, destination
    )
    emit(
        {
            "run": persisted[0].model_dump(mode="json"),
            "corpus": persisted[1].model_dump(mode="json"),
            "report": persisted[2].model_dump(mode="json"),
            "utterance_corpus_root": str(persisted[3]),
            "reused": persisted[4],
        },
        structured,
    )
    return 0
