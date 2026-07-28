"""Phase 5 discourse-provider capability operations."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from .discourse_providers import DiscourseProviderRegistry


def add_discourse_provider_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    parser = subparsers.add_parser("discourse-provider")
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("list")
    inspect = actions.add_parser("inspect")
    inspect.add_argument("provider_id")


def run_discourse_provider_command(
    args: argparse.Namespace,
    emit: Callable[[Any, bool], None],
    structured: bool,
) -> int | None:
    if args.command != "discourse-provider":
        return None
    registry = DiscourseProviderRegistry.with_boundaries()
    if args.action == "list":
        emit(registry.list(), structured)
    else:
        emit(registry.get(args.provider_id).capabilities, structured)
    return 0
