"""CLI operations for Phase 5 long-recording and completion evidence."""

from __future__ import annotations

import argparse
from pathlib import Path

from .kernel import canonical_bytes
from .phase5_completion import (
    QUALIFICATIONS,
    assemble_phase5_completion,
    load_phase5_completion,
    make_completion_evidence,
    persist_phase5_completion,
)
from .phase5_completion_contracts import Phase5EvidenceClass
from .phase5_export import Phase5PortableArtifactSet, reload_phase5_export
from .phase5_long_recording import (
    load_phase5_long_recording,
    persist_phase5_long_recording,
    qualify_phase5_long_recording,
    validate_phase5_long_recording,
)
from .phase5_recovery import load_phase5_recovery


def add_phase5_completion_parsers(subparsers) -> None:
    long_parser = subparsers.add_parser("phase5-long")
    actions = long_parser.add_subparsers(dest="action", required=True)
    item = actions.add_parser("build")
    item.add_argument("output", type=Path)
    item.add_argument("--duration-microseconds", type=int, default=7_201_000_000)
    item.add_argument("--chunk-microseconds", type=int, default=60_000_000)
    for action in ("inspect", "validate"):
        item = actions.add_parser(action)
        item.add_argument("path", type=Path)
    report = subparsers.add_parser("phase5-report")
    actions = report.add_subparsers(dest="action", required=True)
    item = actions.add_parser("build")
    item.add_argument("export_root", type=Path)
    item.add_argument("recovery_report", type=Path)
    item.add_argument("long_recording", type=Path)
    item.add_argument("reports_root", type=Path)
    item.add_argument("--repository-branch", required=True)
    item.add_argument("--starting-head", required=True)
    item.add_argument("--final-head", required=True)
    item.add_argument("--phase-changes-committed", action="store_true")
    item.add_argument("--test-count", type=int, required=True)
    item.add_argument("--schema-count", type=int, required=True)
    for action in ("inspect", "validate", "list-gates", "list-evidence"):
        item = actions.add_parser(action)
        item.add_argument("reports_root", type=Path)


def _artifact_set(export_root):
    values = reload_phase5_export(export_root)
    by_name = {
        Path(path).stem.replace("-", "_"): value
        for path, value in values.items()
    }
    return Phase5PortableArtifactSet(**by_name)


def _evidence(artifacts, recovery, long_recording, tests, schemas):
    sources = {
        "foundation": artifacts.corpus,
        "baseline": artifacts.consolidation,
        "provider": artifacts.consolidation,
        "consolidation": artifacts.consolidation_report,
        "question_answer": artifacts.question_answers,
        "argument": artifacts.argument_relations,
        "lexical": artifacts.lexical_structures,
        "procedural": artifacts.procedural_state,
        "review": artifacts.review_ledger,
        "evaluation": artifacts.evaluation,
        "recovery": recovery,
        "export": artifacts.integrity_result,
        "long": long_recording,
        "regression": {
            "full_regression_test_count": tests,
            "runtime_schema_count": schemas,
            "boundary": "no adjudication or participant judgment",
        },
    }
    classes = {
        "foundation": Phase5EvidenceClass.DETERMINISTIC_RULES,
        "baseline": Phase5EvidenceClass.DETERMINISTIC_RULES,
        "provider": Phase5EvidenceClass.PROVIDER_PROPOSALS,
        "review": Phase5EvidenceClass.HUMAN_REVIEW,
        "evaluation": Phase5EvidenceClass.MEASURED_EVALUATION,
        "recovery": Phase5EvidenceClass.INTEGRITY_VALIDATION,
        "export": Phase5EvidenceClass.INTEGRITY_VALIDATION,
        "long": Phase5EvidenceClass.SYNTHETIC_MECHANICS,
        "regression": Phase5EvidenceClass.INTEGRITY_VALIDATION,
    }
    return tuple(
        make_completion_evidence(
            QUALIFICATIONS[key],
            f"derived:{key}",
            canonical_bytes(value),
            classes.get(
                key, Phase5EvidenceClass.SELECTED_MACHINE_ANALYSIS
            ),
        )
        for key, value in sources.items()
    )


def run_phase5_completion_command(args, emit, structured: bool):
    if args.command == "phase5-long":
        if args.action == "build":
            item = qualify_phase5_long_recording(
                generated_at=__import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ),
                duration_microseconds=args.duration_microseconds,
                chunk_duration_microseconds=args.chunk_microseconds,
            )
            path = persist_phase5_long_recording(item, args.output)
            emit({"qualification": item.model_dump(mode="json"), "path": str(path)}, structured)
            return 0
        item = load_phase5_long_recording(args.path)
        if args.action == "validate":
            validate_phase5_long_recording(item)
            emit({"valid": True, "qualification_id": item.qualification_id}, structured)
        else:
            emit(item, structured)
        return 0
    if args.command != "phase5-report":
        return None
    if args.action == "build":
        artifacts = _artifact_set(args.export_root)
        recovery = load_phase5_recovery(args.recovery_report)
        long_recording = load_phase5_long_recording(args.long_recording)
        evidence = _evidence(
            artifacts,
            recovery,
            long_recording,
            args.test_count,
            args.schema_count,
        )
        report = assemble_phase5_completion(
            artifacts,
            recovery,
            long_recording,
            evidence,
            repository_branch=args.repository_branch,
            starting_repository_head=args.starting_head,
            final_repository_head=args.final_head,
            phase_changes_committed_at_audit=args.phase_changes_committed,
            current_test_count=args.test_count,
            current_schema_count=args.schema_count,
            generated_at=long_recording.generated_at,
        )
        machine, human = persist_phase5_completion(
            report, args.reports_root
        )
        emit(
            {
                "report": report.model_dump(mode="json"),
                "machine": str(machine),
                "human": str(human),
            },
            structured,
        )
        return 0
    report = load_phase5_completion(args.reports_root)
    if args.action == "list-gates":
        emit(report.gates, structured)
    elif args.action == "list-evidence":
        emit(report.evidence, structured)
    else:
        emit(report, structured)
    return 0
