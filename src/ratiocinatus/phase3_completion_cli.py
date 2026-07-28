"""CLI operations for Phase 3 integrity and completion reporting."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .phase3_completion import (
    assemble_completion_report,
    load_completion_report,
    persist_completion_report,
)


def add_phase3_completion_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    parser = subparsers.add_parser("phase3-report")
    actions = parser.add_subparsers(dest="action", required=True)
    build = actions.add_parser("build")
    build.add_argument("reports_root", type=Path)
    build.add_argument("--repository-branch", required=True)
    build.add_argument("--starting-head", required=True)
    build.add_argument("--final-head", required=True)
    build.add_argument("--phase-changes-committed", action="store_true")
    build.add_argument("--test-count", type=int, required=True)
    build.add_argument("--schema-count", type=int, required=True)
    for action in ("inspect", "validate", "list-gates", "list-evidence"):
        item = actions.add_parser(action)
        item.add_argument("reports_root", type=Path)


def run_phase3_completion_command(
    args: argparse.Namespace,
    emit: Callable[[Any, bool], None],
    structured: bool,
) -> int | None:
    if args.command != "phase3-report":
        return None
    if args.action == "build":
        existing = None
        if (
            args.reports_root.expanduser().resolve()
            / "phase-3-completion.json"
        ).is_file():
            existing = load_completion_report(args.reports_root)
        report = assemble_completion_report(
            args.reports_root,
            repository_branch=args.repository_branch,
            starting_repository_head=args.starting_head,
            final_repository_head=args.final_head,
            phase_changes_committed_at_audit=args.phase_changes_committed,
            current_test_count=args.test_count,
            current_schema_count=args.schema_count,
            generated_at=(
                existing.generated_at if existing is not None else None
            ),
            predecessor_report_id=(
                existing.predecessor_report_id
                if existing is not None
                else None
            ),
        )
        if existing is not None and report.report_id != existing.report_id:
            report = assemble_completion_report(
                args.reports_root,
                repository_branch=args.repository_branch,
                starting_repository_head=args.starting_head,
                final_repository_head=args.final_head,
                phase_changes_committed_at_audit=args.phase_changes_committed,
                current_test_count=args.test_count,
                current_schema_count=args.schema_count,
                generated_at=existing.generated_at,
                predecessor_report_id=existing.report_id,
            )
        machine, human = persist_completion_report(
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
        return 0 if report.status != "blocked" else 5
    report = load_completion_report(args.reports_root)
    if args.action == "list-gates":
        emit(report.gates, structured)
    elif args.action == "list-evidence":
        emit(report.evidence, structured)
    else:
        emit(report, structured)
    return 0 if report.status != "blocked" else 5
