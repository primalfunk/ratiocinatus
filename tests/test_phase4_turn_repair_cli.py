from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from ratiocinatus.cli import main
from ratiocinatus.kernel import canonical_bytes
from ratiocinatus.speaker_transcript import (
    build_speaker_labeled_transcript,
    persist_speaker_labeled_transcript,
)
from ratiocinatus.utterance_segmentation import (
    build_utterance_corpus,
    persist_utterance_corpus,
)

from test_phase3_clustering import HAS_FFMPEG
from test_phase3_speaker_transcript import NOW, _speaker_inputs
from test_phase4_analysis import _with_surfaces
from test_phase4_segmentation import _with_words


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_turn_repair_cli_build_decide_inspect_validate_and_replay(
    tmp_path: Path, capsys,
) -> None:
    values, transcript, identity_assembly = _speaker_inputs(tmp_path)
    diarization = values[1]
    transcript = _with_words(transcript)
    transcript = _with_surfaces(
        transcript,
        tuple(item.surface_text for item in transcript.words),
    )
    speaker_view = build_speaker_labeled_transcript(
        transcript, diarization, identity_assembly, created_at=NOW
    )
    utterance_run, corpus = build_utterance_corpus(
        transcript, speaker_view, diarization, created_at=NOW
    )
    assembly_root = tmp_path / "assembly"
    assembly_root.mkdir()
    (assembly_root / "assembly.json").write_bytes(canonical_bytes(transcript))
    speaker_root = persist_speaker_labeled_transcript(
        speaker_view,
        transcript,
        diarization,
        identity_assembly,
        tmp_path / "speaker",
    )[2]
    corpus_root = persist_utterance_corpus(
        utterance_run,
        corpus,
        transcript,
        speaker_view,
        diarization,
        tmp_path / "corpus",
    )[3]
    command = [
        "--json",
        "utterance",
        "repair-build",
        str(corpus_root),
        str(assembly_root),
        str(speaker_root),
        str(values[11]),
        str(tmp_path / "repair"),
    ]
    assert main(command) == 0
    first = json.loads(capsys.readouterr().out)
    assert not first["reused"]
    repair_root = first["turn_repair_root"]
    proposal = first["repair"]["proposals"][0]
    assert main(command) == 0
    assert json.loads(capsys.readouterr().out)["reused"]
    for action in (
        "repair-inspect",
        "list-turn-conflicts",
        "list-turn-proposals",
        "list-turn-successors",
    ):
        assert main(["--json", "utterance", action, repair_root]) == 0
        assert json.loads(capsys.readouterr().out) is not None
    assert main(
        [
            "--json",
            "utterance",
            "repair-validate",
            repair_root,
            str(corpus_root),
            str(assembly_root),
            str(speaker_root),
            str(values[11]),
        ]
    ) == 0
    assert json.loads(capsys.readouterr().out)["valid"]

    decide = [
        "--json",
        "utterance",
        "repair-decide",
        repair_root,
        str(corpus_root),
        str(assembly_root),
        str(speaker_root),
        str(values[11]),
        str(tmp_path / "reviewed"),
        proposal["proposal_id"],
        "accepted",
        "--author",
        "fixture-reviewer",
        "--rationale",
        "Accept bounded successor projection.",
        "--decided-at",
        (NOW + timedelta(seconds=1)).isoformat(),
        "--evidence-reference",
        proposal["affected_artifact_ids"][0],
    ]
    assert main(decide) == 0
    reviewed = json.loads(capsys.readouterr().out)
    assert reviewed["report"]["accepted_count"] == 1
    assert reviewed["report"]["successor_count"] == 1
