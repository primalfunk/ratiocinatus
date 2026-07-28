from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from ratiocinatus.turn_repair import (
    TurnRepairIntegrityError,
    build_turn_repair_run,
    decide_turn_repair,
    load_turn_repair_run,
    persist_turn_repair_run,
    validate_turn_repair_run,
)
from ratiocinatus.turn_repair_contracts import (
    TurnRepairActionKind,
    TurnRepairDecisionDisposition,
)

from test_phase3_clustering import HAS_FFMPEG
from test_phase3_speaker_transcript import NOW
from test_phase4_analysis import _inputs


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_turn_repair_detection_is_deterministic_and_non_destructive(
    tmp_path: Path,
) -> None:
    values, transcript, speaker_view, utterance_run, corpus = _inputs(
        tmp_path
    )
    diarization = values[1]
    before_transcript = transcript.model_dump_json()
    before_diarization = diarization.model_dump_json()
    before_corpus = corpus.model_dump_json()

    repair = build_turn_repair_run(
        utterance_run,
        corpus,
        transcript,
        speaker_view,
        diarization,
        created_at=NOW,
    )
    repeated = build_turn_repair_run(
        utterance_run,
        corpus,
        transcript,
        speaker_view,
        diarization,
        created_at=NOW,
    )

    assert repeated == repair
    assert repair.conflicts
    assert len(repair.proposals) == len(repair.conflicts)
    assert all(item.contrary_evidence for item in repair.proposals)
    assert all(
        item.proposed_change.preserves_all_source_intervals
        for item in repair.proposals
    )
    assert all(
        item.proposed_change.action
        != TurnRepairActionKind.REASSIGN_TRANSCRIPT_WORDS
        for item in repair.proposals
    )
    assert transcript.model_dump_json() == before_transcript
    assert diarization.model_dump_json() == before_diarization
    assert corpus.model_dump_json() == before_corpus


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_accepted_repair_creates_derived_successor_and_preserves_source(
    tmp_path: Path,
) -> None:
    values, transcript, speaker_view, utterance_run, corpus = _inputs(
        tmp_path
    )
    diarization = values[1]
    repair = build_turn_repair_run(
        utterance_run,
        corpus,
        transcript,
        speaker_view,
        diarization,
        created_at=NOW,
    )
    source_hashes = (
        transcript.integrity_sha256,
        diarization.integrity_sha256,
        corpus.integrity_sha256,
    )
    proposal = repair.proposals[0]
    reviewed = decide_turn_repair(
        repair,
        proposal.proposal_id,
        TurnRepairDecisionDisposition.ACCEPTED,
        author="fixture-reviewer",
        rationale="Accept the bounded successor projection for testing.",
        evidence_references=proposal.affected_artifact_ids,
        decided_at=NOW + timedelta(seconds=1),
    )

    assert reviewed.predecessor_repair_run_id == repair.repair_run_id
    assert len(reviewed.decisions) == 1
    assert len(reviewed.successors) == 1
    successor = reviewed.successors[0]
    assert successor.projected_change == proposal.proposed_change
    assert successor.predecessor_artifacts_preserved
    assert (
        transcript.integrity_sha256,
        diarization.integrity_sha256,
        corpus.integrity_sha256,
    ) == source_hashes
    validate_turn_repair_run(
        reviewed,
        utterance_run,
        corpus,
        transcript,
        speaker_view,
        diarization,
    )


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_turn_repair_persistence_replays_and_rejects_tampering(
    tmp_path: Path,
) -> None:
    values, transcript, speaker_view, utterance_run, corpus = _inputs(
        tmp_path
    )
    diarization = values[1]
    repair = build_turn_repair_run(
        utterance_run,
        corpus,
        transcript,
        speaker_view,
        diarization,
        created_at=NOW,
    )
    first = persist_turn_repair_run(
        repair,
        utterance_run,
        corpus,
        transcript,
        speaker_view,
        diarization,
        tmp_path / "repair",
    )
    replay = persist_turn_repair_run(
        repair,
        utterance_run,
        corpus,
        transcript,
        speaker_view,
        diarization,
        tmp_path / "repair",
    )
    assert not first[3]
    assert replay[3]
    loaded = load_turn_repair_run(first[2])
    assert loaded == first[:2]

    tampered = repair.model_copy(
        update={"configuration_hash": "f" * 64}
    )
    with pytest.raises(
        TurnRepairIntegrityError, match="integrity is invalid"
    ):
        validate_turn_repair_run(
            tampered,
            utterance_run,
            corpus,
            transcript,
            speaker_view,
            diarization,
        )
