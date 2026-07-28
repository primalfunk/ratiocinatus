"""CLI integration for comparison-backed identity hypotheses."""

from __future__ import annotations

from pathlib import Path

from .clustering_contracts import ClusteringRun
from .comparison_hypotheses import add_comparison_identity_hypothesis
from .identity import (
    load_identity_foundation,
    persist_identity_foundation,
)
from .kernel import load_contract
from .phase3_contracts import DiarizationRun
from .reference_comparison_validation import load_reference_comparison
from .reference_enrollment_operations import load_reference_enrollment

ACTION = "identity-propose-from-comparison"


def add_comparison_hypothesis_parser(diasub) -> None:
    parser = diasub.add_parser(ACTION)
    parser.add_argument("foundation_root", type=Path)
    parser.add_argument("clustering_root", type=Path)
    parser.add_argument("diarization_root", type=Path)
    parser.add_argument("enrollment_root", type=Path)
    parser.add_argument("comparison_root", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--comparison", required=True)


def run_comparison_hypothesis_command(args, emit, structured: bool):
    if args.action != ACTION:
        return None
    foundation, _ = load_identity_foundation(args.foundation_root)
    clustering_root = args.clustering_root.expanduser().resolve(strict=True)
    diarization_root = args.diarization_root.expanduser().resolve(strict=True)
    clustering = load_contract(
        (clustering_root / "clustering.json").read_bytes(),
        ClusteringRun,
    )
    diarization = load_contract(
        (diarization_root / "run.json").read_bytes(),
        DiarizationRun,
    )
    enrollments, _ = load_reference_enrollment(args.enrollment_root)
    comparisons, _ = load_reference_comparison(args.comparison_root)
    successor, hypothesis = add_comparison_identity_hypothesis(
        foundation,
        clustering,
        diarization,
        enrollments,
        comparisons,
        comparison_id=args.comparison,
    )
    persisted = persist_identity_foundation(
        successor,
        clustering,
        diarization,
        args.destination,
        predecessor=foundation,
    )
    emit(
        {
            "hypothesis": hypothesis.model_dump(mode="json"),
            "foundation": persisted[0].model_dump(mode="json"),
            "report": persisted[1].model_dump(mode="json"),
            "foundation_root": str(persisted[2]),
            "reused": persisted[3],
        },
        structured,
    )
    return 0
