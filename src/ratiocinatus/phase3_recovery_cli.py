"""Command-line inspection for Phase 3 recovery evidence."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .phase3_recovery import (
    load_recovery_report,
    plan_downstream_invalidation,
)
from .phase3_recovery_contracts import Phase3RecoveryStage


def add_phase3_recovery_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    parser = subparsers.add_parser("phase3-recovery")
    actions = parser.add_subparsers(dest="action", required=True)
    for action in ("inspect", "validate", "list-records"):
        item = actions.add_parser(action)
        item.add_argument("recovery_root", type=Path)
    item = actions.add_parser("plan")
    item.add_argument(
        "changed_stages",
        nargs="+",
        choices=tuple(stage.value for stage in Phase3RecoveryStage),
    )
    item.add_argument(
        "--reason",
        default="declared Phase 3 evidence or policy change",
    )


def run_phase3_recovery_command(
    args: argparse.Namespace,
    emit: Callable[[Any, bool], None],
    structured: bool,
) -> int | None:
    if args.command != "phase3-recovery":
        return None
    if args.action == "plan":
        plan = plan_downstream_invalidation(
            tuple(Phase3RecoveryStage(value) for value in args.changed_stages),
            reason=args.reason,
        )
        emit(plan, structured)
        return 0
    report = load_recovery_report(args.recovery_root)
    if args.action == "list-records":
        emit(report.records, structured)
    else:
        emit(report, structured)
    return 0 if report.status == "passed" else 5
