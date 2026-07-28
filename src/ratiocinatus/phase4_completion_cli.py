"""CLI operations for Phase 4 integrity and completion reporting."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .phase4_completion import (
    assemble_phase4_completion,
    load_phase4_completion,
    persist_phase4_completion,
)


def add_phase4_completion_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    parser = subparsers.add_parser("phase4-report")
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


def run_phase4_completion_command(
    args: argparse.Namespace,
    emit: Callable[[Any, bool], None],
    structured: bool,
) -> int | None:
    if args.command != "phase4-report":
        return None
    if args.action == "build":
        report = assemble_phase4_completion(
            args.reports_root,
            repository_branch=args.repository_branch,
            starting_repository_head=args.starting_head,
            final_repository_head=args.final_head,
            phase_changes_committed_at_audit=args.phase_changes_committed,
            current_test_count=args.test_count,
            current_schema_count=args.schema_count,
        )
        machine, human = persist_phase4_completion(
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
    report = load_phase4_completion(args.reports_root)
    if args.action == "list-gates":
        emit(report.gates, structured)
    elif args.action == "list-evidence":
        emit(report.evidence, structured)
    else:
        emit(report, structured)
    return 0 if report.status != "blocked" else 5
