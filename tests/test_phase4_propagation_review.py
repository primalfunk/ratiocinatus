from __future__ import annotations

from pathlib import Path

import pytest

from ratiocinatus.context_windows import build_context_windows
from ratiocinatus.phase4_propagation import (
    Phase4ArtifactSet,
    Phase4PropagationIntegrityError,
    build_phase4_propagation,
    load_phase4_propagation,
    persist_phase4_propagation,
    rebuild_phase4_artifact_set,
    validate_phase4_propagation,
)
from ratiocinatus.phase4_review import (
    Phase4ReviewIntegrityError,
    append_review_action,
    build_review_queue,
    create_review_ledger,
    load_review_ledger,
    persist_review_ledger,
)
from ratiocinatus.phase4_review_contracts import (
    Phase4ChangeKind,
    ReviewActionKind,
    ReviewQueueKind,
    ReviewerCertainty,
    UtteranceMappingDisposition,
)
from ratiocinatus.quotation_evidence import build_quotation_evidence
from ratiocinatus.speaker_transcript import build_speaker_labeled_transcript
from ratiocinatus.turn_repair import build_turn_repair_run
from ratiocinatus.utterance_analysis import analyze_utterance_corpus
from ratiocinatus.utterance_relations import build_utterance_relations
from ratiocinatus.utterance_segmentation import build_utterance_corpus
from ratiocinatus.utterance_views import build_speaker_attributed_views

from test_phase3_clustering import HAS_FFMPEG
from test_phase3_speaker_transcript import NOW, _speaker_inputs
from test_phase4_analysis import _with_surfaces
from test_phase4_segmentation import _with_words


def _artifact_set(
    tmp_path: Path,
    *,
    first_surface: str = 'Alice said "hello there".',
) -> Phase4ArtifactSet:
    tmp_path.mkdir(parents=True, exist_ok=True)
    values, transcript, identity_assembly = _speaker_inputs(tmp_path)
    diarization = values[1]
    transcript = _with_words(transcript)
    controlled = (
        first_surface,
        "[remote] Good evening.",
        '"quotation marks alone"',
    )
    transcript = _with_surfaces(
        transcript,
        tuple(
            controlled[index]
            if index < len(controlled)
            else word.surface_text
            for index, word in enumerate(transcript.words)
        ),
    )
    speaker_view = build_speaker_labeled_transcript(
        transcript, diarization, identity_assembly, created_at=NOW
    )
    return rebuild_phase4_artifact_set(
        transcript,
        speaker_view,
        diarization,
        created_at=NOW,
    )


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_identical_phase4_chains_preserve_all_predecessor_evidence(
    tmp_path: Path,
) -> None:
    artifacts = _artifact_set(tmp_path)
    run = build_phase4_propagation(
        artifacts, artifacts, created_at=NOW
    )
    repeated = build_phase4_propagation(
        artifacts, artifacts, created_at=NOW
    )
    assert repeated == run
    assert not run.changed_predecessor_utterance_ids
    assert set(run.unaffected_predecessor_utterance_ids) == {
        item.utterance_id for item in artifacts.corpus.utterances
    }
    assert all(
        item.disposition == UtteranceMappingDisposition.UNCHANGED_EQUIVALENT
        and item.predecessor_identifier_preserved
        and item.predecessor_evidence_preserved
        for item in run.impacts
    )
    validate_phase4_propagation(run, artifacts, artifacts)


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_text_correction_selectively_invalidates_and_rebuilds_dependencies(
    tmp_path: Path,
) -> None:
    predecessor = _artifact_set(tmp_path)
    successor = _artifact_set(
        tmp_path, first_surface='Alice said "hello again".'
    )
    run = build_phase4_propagation(
        predecessor, successor, created_at=NOW
    )
    assert run.changed_predecessor_utterance_ids
    assert run.unaffected_predecessor_utterance_ids
    changed = tuple(item for item in run.impacts if item.affected)
    assert any(
        Phase4ChangeKind.TEXT_ONLY in item.change_kinds for item in changed
    )
    assert run.successor_transcript_view_bundle_id == (
        successor.transcript_views.bundle_id
    )
    assert run.successor_context_bundle_id == (
        successor.context_windows.context_bundle_id
    )
    assert all(item.predecessor_evidence_preserved for item in run.impacts)


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_propagation_persistence_replays_and_rejects_tampering(
    tmp_path: Path,
) -> None:
    artifacts = _artifact_set(tmp_path)
    run = build_phase4_propagation(
        artifacts, artifacts, created_at=NOW
    )
    first = persist_phase4_propagation(
        run, artifacts, artifacts, tmp_path / "propagation"
    )
    replay = persist_phase4_propagation(
        run, artifacts, artifacts, tmp_path / "propagation"
    )
    assert not first[3]
    assert replay[3]
    loaded = load_phase4_propagation(first[2])
    assert loaded == first[:2]
    tampered = run.model_copy(
        update={"configuration_hash": "f" * 64}
    )
    with pytest.raises(
        Phase4PropagationIntegrityError, match="integrity is invalid"
    ):
        validate_phase4_propagation(tampered, artifacts, artifacts)


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_manual_review_is_append_only_and_machine_evidence_is_preserved(
    tmp_path: Path,
) -> None:
    artifacts = _artifact_set(tmp_path)
    target = artifacts.corpus.utterances[0]
    initial = create_review_ledger(
        artifacts.corpus, artifacts.transcript_views, created_at=NOW
    )
    approved = append_review_action(
        initial,
        artifacts.corpus,
        artifacts.transcript_views,
        ReviewActionKind.APPROVE_UTTERANCE,
        (target.utterance_id,),
        target_artifact_ids=(target.utterance_id,),
        prior_state={"review_status": target.review_status.value},
        proposed_state={"review_status": "approved"},
        author="reviewer@example.test",
        reviewed_at=NOW,
        rationale="Controlled evidence supports the machine boundary.",
        evidence_references=(target.utterance_id,),
        reviewer_certainty=ReviewerCertainty.HIGH,
    )
    deferred = append_review_action(
        approved,
        artifacts.corpus,
        artifacts.transcript_views,
        ReviewActionKind.DEFER_DECISION,
        (target.utterance_id,),
        target_artifact_ids=(target.utterance_id,),
        prior_state={"decision": "approved"},
        proposed_state={"decision": "deferred"},
        author="reviewer@example.test",
        reviewed_at=NOW,
        rationale="Retain both actions while awaiting another source.",
        evidence_references=(target.utterance_id,),
        reviewer_certainty=ReviewerCertainty.LOW,
    )
    assert deferred.actions[:1] == approved.actions
    assert all(item.machine_proposal_preserved for item in deferred.actions)
    assert deferred.predecessor_review_ledger_id == approved.review_ledger_id
    persisted = persist_review_ledger(
        deferred,
        artifacts.corpus,
        artifacts.transcript_views,
        tmp_path / "reviews",
    )
    assert load_review_ledger(persisted[1]) == deferred

    with pytest.raises(Phase4ReviewIntegrityError, match="unknown utterance"):
        append_review_action(
            deferred,
            artifacts.corpus,
            artifacts.transcript_views,
            ReviewActionKind.APPROVE_UTTERANCE,
            ("utterance_" + "f" * 32,),
            target_artifact_ids=(target.utterance_id,),
            prior_state={"review_status": "unknown"},
            proposed_state={"review_status": "approved"},
            author="reviewer@example.test",
            reviewed_at=NOW,
            rationale="Invalid controlled target.",
            evidence_references=(target.utterance_id,),
            reviewer_certainty=ReviewerCertainty.HIGH,
        )


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_review_queues_package_context_media_and_competing_actions(
    tmp_path: Path,
) -> None:
    artifacts = _artifact_set(tmp_path)
    ledger = create_review_ledger(
        artifacts.corpus, artifacts.transcript_views, created_at=NOW
    )
    propagation = build_phase4_propagation(
        artifacts, artifacts, created_at=NOW
    )
    report = build_review_queue(
        ledger, artifacts, propagation=propagation, generated_at=NOW
    )
    assert report.items
    assert all(
        item.source_intervals
        and item.media_reference
        and item.extraction_command
        and item.local_context_window_ids
        and item.speaker_evidence_references
        and item.proposed_actions
        and item.competing_alternatives
        for item in report.items
    )
    assert {
        ReviewQueueKind.LOW_CONFIDENCE_SEGMENTATION,
        ReviewQueueKind.PROBABLE_SELF_REPAIR,
    }.intersection(item.kind for item in report.items)
