from __future__ import annotations

from pathlib import Path

import pytest

from ratiocinatus.context_window_contracts import (
    ContextExclusionKind,
    ContextWindowKind,
    ContextWindowPolicy,
)
from ratiocinatus.context_windows import (
    ContextWindowBudgetError,
    ContextWindowIntegrityError,
    build_context_windows,
    load_context_windows,
    persist_context_windows,
    validate_context_windows,
)

from test_phase3_clustering import HAS_FFMPEG
from test_phase3_speaker_transcript import NOW
from test_phase4_utterance_views import _build


def _context_build(tmp_path: Path, policy: ContextWindowPolicy | None = None):
    views, inputs = _build(tmp_path)
    bundle = build_context_windows(
        views, *inputs, policy=policy, created_at=NOW
    )
    return bundle, views, inputs


def test_context_policy_is_bounded_and_explicit() -> None:
    policy = ContextWindowPolicy()
    assert policy.maximum_utterance_count >= 1
    assert policy.maximum_token_estimate >= 1
    assert policy.maximum_source_duration_microseconds >= 1
    assert policy.speaker_balanced_selection
    assert policy.preserve_question_response
    assert policy.preserve_interruption_relations
    assert policy.preserve_quotation_sources
    assert policy.preserve_simultaneous_overlap
    assert policy.truncation_must_be_explicit


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_all_nine_windows_are_deterministic_bounded_and_source_traceable(
    tmp_path: Path,
) -> None:
    bundle, views, inputs = _context_build(tmp_path)
    repeated = build_context_windows(
        views, *inputs, created_at=NOW
    )
    assert repeated == bundle
    corpus = inputs[1]
    assert len(bundle.windows) == len(corpus.utterances) * len(
        ContextWindowKind
    )
    for target in corpus.utterances:
        target_windows = tuple(
            item
            for item in bundle.windows
            if item.target_utterance_id == target.utterance_id
        )
        assert {item.kind for item in target_windows} == set(ContextWindowKind)
        for window in target_windows:
            assert sum(
                member.utterance_id == target.utterance_id
                for member in window.members
            ) == 1
            assert window.token_estimate <= bundle.policy.maximum_token_estimate
            assert len(window.members) <= bundle.policy.maximum_utterance_count
            assert window.source_duration_microseconds <= (
                bundle.policy.maximum_source_duration_microseconds
            )
            assert window.source_intervals
            assert all(member.evidence_references for member in window.members)
    validate_context_windows(bundle, views, *inputs)


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_context_budget_truncation_and_structural_absence_are_disclosed(
    tmp_path: Path,
) -> None:
    policy = ContextWindowPolicy(
        maximum_utterance_count=2,
        maximum_token_estimate=1_200,
        maximum_source_duration_microseconds=120_000_000,
        preceding_utterance_count=100,
        following_utterance_count=100,
    )
    bundle, _, _ = _context_build(tmp_path, policy)
    assert any(item.truncated for item in bundle.windows)
    assert any(
        summary.kind == ContextExclusionKind.MAXIMUM_UTTERANCE_COUNT
        for item in bundle.windows
        for summary in item.exclusions
    )
    assert all(
        not item.complete_exchange_considered
        for item in bundle.windows
        if item.truncated
    )
    assert any(
        not item.structurally_available
        and any(
            summary.kind == ContextExclusionKind.STRUCTURE_UNAVAILABLE
            for summary in item.exclusions
        )
        for item in bundle.windows
        if item.kind
        in {
            ContextWindowKind.QUESTION_RESPONSE,
            ContextWindowKind.INTERRUPTION,
            ContextWindowKind.QUOTATION,
        }
    )


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_context_persistence_replays_and_rejects_tampering(
    tmp_path: Path,
) -> None:
    bundle, views, inputs = _context_build(tmp_path)
    first = persist_context_windows(
        bundle, views, *inputs, tmp_path / "contexts"
    )
    replay = persist_context_windows(
        bundle, views, *inputs, tmp_path / "contexts"
    )
    assert not first[3]
    assert replay[3]
    loaded = load_context_windows(first[2])
    assert loaded == first[:2]
    validate_context_windows(
        loaded[0], views, *inputs, report=loaded[1]
    )

    tampered = bundle.model_copy(
        update={"configuration_hash": "f" * 64}
    )
    with pytest.raises(ContextWindowIntegrityError, match="integrity is invalid"):
        validate_context_windows(tampered, views, *inputs)


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_context_refuses_a_target_that_cannot_fit_the_budget(
    tmp_path: Path,
) -> None:
    views, inputs = _build(tmp_path)
    with pytest.raises(ContextWindowBudgetError, match="exceeds"):
        build_context_windows(
            views,
            *inputs,
            policy=ContextWindowPolicy(
                maximum_token_estimate=1,
                maximum_source_duration_microseconds=120_000_000,
            ),
            created_at=NOW,
        )
