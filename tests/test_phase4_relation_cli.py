from __future__ import annotations

import json
from pathlib import Path

import pytest

from ratiocinatus.cli import main
from ratiocinatus.utterance_analysis import (
    analyze_utterance_corpus,
    persist_utterance_analysis,
)
from ratiocinatus.utterance_segmentation import persist_utterance_corpus

from test_phase3_clustering import HAS_FFMPEG
from test_phase3_speaker_transcript import NOW
from test_phase4_analysis import _inputs


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_relation_cli_build_inspect_lists_validate_and_replay(
    tmp_path: Path, capsys,
) -> None:
    values, transcript, speaker_view, utterance_run, corpus = _inputs(
        tmp_path
    )
    diarization = values[1]
    analysis = analyze_utterance_corpus(
        utterance_run, corpus, transcript, created_at=NOW
    )
    corpus_root = persist_utterance_corpus(
        utterance_run,
        corpus,
        transcript,
        speaker_view,
        diarization,
        tmp_path / "corpus",
    )[3]
    analysis_root = persist_utterance_analysis(
        analysis,
        utterance_run,
        corpus,
        transcript,
        tmp_path / "analysis",
    )[2]
    command = [
        "--json",
        "utterance",
        "relate",
        str(corpus_root),
        str(analysis_root),
        str(values[11]),
        str(tmp_path / "relations"),
    ]
    assert main(command) == 0
    first = json.loads(capsys.readouterr().out)
    assert not first["reused"]
    relation_root = first["utterance_relation_root"]
    assert main(command) == 0
    assert json.loads(capsys.readouterr().out)["reused"]
    for action in (
        "relations-inspect",
        "list-interruptions",
        "list-continuations",
        "list-overlaps",
        "list-adjacencies",
    ):
        assert main(["--json", "utterance", action, relation_root]) == 0
        assert json.loads(capsys.readouterr().out) is not None
    assert main(
        [
            "--json",
            "utterance",
            "relations-validate",
            relation_root,
            str(corpus_root),
            str(analysis_root),
            str(values[11]),
        ]
    ) == 0
    assert json.loads(capsys.readouterr().out)["valid"]
