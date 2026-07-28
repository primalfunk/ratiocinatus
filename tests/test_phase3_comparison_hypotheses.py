from __future__ import annotations

from pathlib import Path

import pytest

from ratiocinatus.comparison_hypotheses import (
    add_comparison_identity_hypothesis,
)
from ratiocinatus.identity import (
    IdentityFoundationIntegrityError,
    persist_identity_foundation,
)
from ratiocinatus.phase3_contracts import (
    IdentityHypothesisDisposition,
    IdentityHypothesisSource,
)
from ratiocinatus.reference_comparison import compare_reference_voice

from test_phase3_clustering import HAS_FFMPEG
from test_phase3_reference_comparison import (
    NOW,
    _policy,
    _setup,
    _uncalibrated,
)


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_positive_comparison_creates_bounded_acoustic_hypothesis(
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
    comparisons, comparison = compare_reference_voice(
        clustering,
        diarization,
        foundation,
        enrollments,
        target=target,
        reference_id=reference.reference_id,
        score=0.90,
        threshold_policy=_policy(),
        calibration=_uncalibrated(),
        comparison_provider="controlled.hypothesis.comparison/1",
        comparison_method="controlled cosine-like score",
        supporting_evidence_references=("fixture:hypothesis:score",),
        created_at=NOW,
    )
    successor, hypothesis = add_comparison_identity_hypothesis(
        foundation,
        clustering,
        diarization,
        enrollments,
        comparisons,
        comparison_id=comparison.comparison_id,
        created_at=NOW,
    )
    assert successor.predecessor_foundation_id == foundation.foundation_id
    assert successor.identities == foundation.identities
    assert successor.hypotheses[:-1] == foundation.hypotheses
    assert hypothesis.source == (
        IdentityHypothesisSource.REFERENCE_VOICE_COMPARISON
    )
    assert hypothesis.disposition == IdentityHypothesisDisposition.SUPPORTED
    assert hypothesis.target_artifact_id == target.target_artifact_id
    assert hypothesis.proposed_identity_id == reference.identity_id
    assert hypothesis.acoustic_support.value == pytest.approx(0.90)
    assert not hypothesis.acoustic_support.calibrated
    assert hypothesis.contextual_support.value is None
    assert hypothesis.documentary_support.value is None
    assert hypothesis.manual_assertion_support.value is None
    assert comparison.comparison_id in (
        hypothesis.supporting_evidence_references
    )
    assert "binding" in hypothesis.creation_process.casefold()

    stored = persist_identity_foundation(
        successor,
        clustering,
        diarization,
        tmp_path / "identity",
        predecessor=foundation,
    )
    assert not stored[-1]
    assert stored[1].hypothesis_count == 1
    cached = persist_identity_foundation(
        successor,
        clustering,
        diarization,
        tmp_path / "identity",
        predecessor=foundation,
    )
    assert cached[-1]


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_weak_support_remains_proposed_and_calibration_is_preserved(
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
    comparisons, comparison = compare_reference_voice(
        clustering,
        diarization,
        foundation,
        enrollments,
        target=target,
        reference_id=reference.reference_id,
        score=0.70,
        threshold_policy=_policy(),
        calibration=_uncalibrated(),
        comparison_provider="controlled.hypothesis.comparison/1",
        comparison_method="controlled cosine-like score",
        created_at=NOW,
    )
    _, hypothesis = add_comparison_identity_hypothesis(
        foundation,
        clustering,
        diarization,
        enrollments,
        comparisons,
        comparison_id=comparison.comparison_id,
        created_at=NOW,
    )
    assert hypothesis.disposition == IdentityHypothesisDisposition.PROPOSED
    assert hypothesis.acoustic_support.value == pytest.approx(0.70)
    assert "not a probability" in hypothesis.acoustic_support.basis


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
@pytest.mark.parametrize("score", [0.50, 0.30, 0.10])
def test_nonpositive_comparisons_cannot_be_mislabeled_as_support(
    tmp_path: Path,
    score: float,
) -> None:
    (
        clustering,
        diarization,
        foundation,
        enrollments,
        reference,
        target,
    ) = _setup(tmp_path)
    comparisons, comparison = compare_reference_voice(
        clustering,
        diarization,
        foundation,
        enrollments,
        target=target,
        reference_id=reference.reference_id,
        score=score,
        threshold_policy=_policy(),
        calibration=_uncalibrated(),
        comparison_provider="controlled.hypothesis.comparison/1",
        comparison_method="controlled cosine-like score",
        created_at=NOW,
    )
    with pytest.raises(
        IdentityFoundationIntegrityError,
        match="only positive valid comparison",
    ):
        add_comparison_identity_hypothesis(
            foundation,
            clustering,
            diarization,
            enrollments,
            comparisons,
            comparison_id=comparison.comparison_id,
            created_at=NOW,
        )
