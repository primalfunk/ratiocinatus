"""CLI operations for controlled temporal diarization evaluation."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .diarization import (
    validate_diarization_response,
    validate_diarization_run,
)
from .diarization_evaluation import (
    evaluate_diarization_artifacts,
    evaluation_report_markdown,
    load_diarization_evaluation,
    validate_diarization_evaluation,
)
from .diarization_evaluation_contracts import DiarizationScoringPolicy
from .kernel import load_contract
from .phase3_contracts import (
    DiarizationProviderResponse,
    DiarizationRequest,
    DiarizationRun,
)


def add_diarization_evaluation_parsers(
    subparsers: argparse._SubParsersAction,
) -> None:
    parser = subparsers.add_parser("evaluate-diarization")
    parser.add_argument("diarization_root", type=Path)
    parser.add_argument("reference", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--collar-microseconds", type=int, default=250_000)
    parser.add_argument(
        "--boundary-tolerance-microseconds", type=int, default=500_000
    )
    for action in (
        "inspect-diarization-evaluation",
        "validate-diarization-evaluation",
        "list-diarization-strata",
    ):
        parser = subparsers.add_parser(action)
        parser.add_argument("evaluation_root", type=Path)
        if action == "validate-diarization-evaluation":
            parser.add_argument("diarization_root", type=Path)


def run_diarization_evaluation_command(
    args: argparse.Namespace,
    emit: Callable[[Any, bool], None],
    structured: bool,
) -> int | None:
    actions = {
        "evaluate-diarization",
        "inspect-diarization-evaluation",
        "validate-diarization-evaluation",
        "list-diarization-strata",
    }
    if args.command != "diarization" or args.action not in actions:
        return None
    if args.action == "evaluate-diarization":
        policy = DiarizationScoringPolicy(
            collar_microseconds=args.collar_microseconds,
            boundary_tolerance_microseconds=(
                args.boundary_tolerance_microseconds
            ),
        )
        evaluation, report, root, reused = evaluate_diarization_artifacts(
            args.diarization_root,
            args.reference,
            args.destination,
            policy=policy,
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
    evaluation, report = load_diarization_evaluation(args.evaluation_root)
    if args.action == "inspect-diarization-evaluation":
        emit(
            {
                "evaluation": evaluation.model_dump(mode="json"),
                "report": report.model_dump(mode="json"),
            },
            structured,
        )
        return 0
    if args.action == "list-diarization-strata":
        emit(evaluation.strata, structured)
        return 0
    diarization_root = args.diarization_root.expanduser().resolve(strict=True)
    request = load_contract(
        (diarization_root / "request.json").read_bytes(), DiarizationRequest
    )
    response = load_contract(
        (diarization_root / "response.json").read_bytes(),
        DiarizationProviderResponse,
    )
    diarization = load_contract(
        (diarization_root / "run.json").read_bytes(), DiarizationRun
    )
    validate_diarization_response(response, request, diarization_root)
    validate_diarization_run(diarization)
    validate_diarization_evaluation(
        evaluation, diarization, response, report
    )
    markdown = (
        args.evaluation_root.expanduser().resolve(strict=True) / "report.md"
    )
    if markdown.read_bytes() != evaluation_report_markdown(report).encode(
        "utf-8"
    ):
        from .diarization_evaluation import (
            DiarizationEvaluationIntegrityError,
        )

        raise DiarizationEvaluationIntegrityError(
            "temporal diarization human report is invalid"
        )
    emit(report, structured)
    return 0 if report.status != "blocked" else 5
