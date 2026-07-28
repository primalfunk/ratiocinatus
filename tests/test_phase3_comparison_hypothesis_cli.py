from __future__ import annotations

from pathlib import Path

import pytest

from ratiocinatus.cli import EXIT_SUCCESS, main
from ratiocinatus.identity import persist_identity_foundation
from ratiocinatus.reference_comparison import compare_reference_voice
from ratiocinatus.reference_comparison_validation import (
    persist_reference_comparison,
)
from ratiocinatus.reference_enrollment_operations import (
    persist_reference_enrollment,
)

from test_phase3_clustering import HAS_FFMPEG
from test_phase3_reference_comparison import (
    NOW,
    _policy,
    _setup,
    _uncalibrated,
)


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_comparison_backed_hypothesis_cli_is_append_only(
    tmp_path: Path,
) -> None:
    (
        clustering,
        diarization,
        foundation,
        enrollments,
        reference,
        target,
    ) = _setup(tmp_path)
    clustering_root = tmp_path / "clustering-root"
    diarization_root = tmp_path / "diarization-root"
    clustering_root.mkdir()
    diarization_root.mkdir()
    (clustering_root / "clustering.json").write_text(
        clustering.model_dump_json(), encoding="utf-8"
    )
    (diarization_root / "run.json").write_text(
        diarization.model_dump_json(), encoding="utf-8"
    )
    foundation_root = persist_identity_foundation(
        foundation,
        clustering,
        diarization,
        tmp_path / "identity",
    )[2]
    enrollment_root = persist_reference_enrollment(
        enrollments,
        foundation,
        tmp_path / "enrollments",
    )[2]
    comparison_run, comparison = compare_reference_voice(
        clustering,
        diarization,
        foundation,
        enrollments,
        target=target,
        reference_id=reference.reference_id,
        score=0.90,
        threshold_policy=_policy(),
        calibration=_uncalibrated(),
        comparison_provider="controlled.cli.hypothesis/1",
        comparison_method="controlled cosine-like score",
        created_at=NOW,
    )
    comparison_root = persist_reference_comparison(
        comparison_run,
        clustering,
        diarization,
        foundation,
        enrollments,
        tmp_path / "comparisons",
    )[2]
    destination = tmp_path / "successor"
    assert main(
        [
            "--json",
            "diarization",
            "identity-propose-from-comparison",
            str(foundation_root),
            str(clustering_root),
            str(diarization_root),
            str(enrollment_root),
            str(comparison_root),
            str(destination),
            "--comparison",
            comparison.comparison_id,
        ]
    ) == EXIT_SUCCESS
    successor_root = next(
        (destination / "identity-foundations").iterdir()
    )
    assert main(
        [
            "--json",
            "diarization",
            "identity-list-hypotheses",
            str(successor_root),
        ]
    ) == EXIT_SUCCESS
