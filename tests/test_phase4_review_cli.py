from __future__ import annotations

import json
from pathlib import Path

import pytest

from ratiocinatus import utterance_cli
from ratiocinatus.cli import main

from test_phase3_clustering import HAS_FFMPEG
from test_phase3_speaker_transcript import NOW
from test_phase4_propagation_review import _artifact_set


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_review_cli_creates_appends_inspects_and_lists(
    tmp_path: Path, capsys, monkeypatch,
) -> None:
    artifacts = _artifact_set(tmp_path)
    corpus_root = tmp_path / "corpus-root"
    view_root = tmp_path / "view-root"
    corpus_root.mkdir()
    view_root.mkdir()
    monkeypatch.setattr(
        utterance_cli,
        "load_utterance_corpus",
        lambda _: (
            artifacts.utterance_run,
            artifacts.corpus,
            None,
        ),
    )
    monkeypatch.setattr(
        utterance_cli,
        "load_speaker_attributed_views",
        lambda _: (artifacts.transcript_views, None),
    )
    destination = tmp_path / "reviews"
    assert main(
        [
            "--json",
            "utterance",
            "review-create",
            str(corpus_root),
            str(view_root),
            str(destination),
        ]
    ) == 0
    created = json.loads(capsys.readouterr().out)
    review_root = created["review_root"]
    assert created["ledger"]["ledger_version"] == 0

    target = artifacts.corpus.utterances[0]
    assert main(
        [
            "--json",
            "utterance",
            "review-append",
            review_root,
            str(corpus_root),
            str(view_root),
            str(destination),
            "approve_utterance",
            "--target-utterance",
            target.utterance_id,
            "--target-artifact",
            target.utterance_id,
            "--prior-state",
            f"review_status={target.review_status.value}",
            "--proposed-state",
            "review_status=approved",
            "--author",
            "reviewer@example.test",
            "--reviewed-at",
            NOW.isoformat(),
            "--rationale",
            "Controlled source evidence supports approval.",
            "--evidence-reference",
            target.utterance_id,
            "--certainty",
            "high",
        ]
    ) == 0
    appended = json.loads(capsys.readouterr().out)
    assert appended["ledger"]["ledger_version"] == 1
    successor_root = appended["review_root"]
    for action in ("review-inspect", "list-review-actions"):
        assert main(
            ["--json", "utterance", action, successor_root]
        ) == 0
        assert json.loads(capsys.readouterr().out) is not None
