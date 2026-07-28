from __future__ import annotations

import json
from pathlib import Path

import pytest

from ratiocinatus.cli import main
from ratiocinatus.kernel import canonical_bytes
from ratiocinatus.utterance_segmentation import persist_utterance_corpus

from test_phase3_clustering import HAS_FFMPEG
from test_phase4_quotation import _quotation_inputs


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_quotation_cli_build_inspect_lists_validate_and_replay(
    tmp_path: Path, capsys,
) -> None:
    values, transcript, speaker_view, utterance_run, corpus = (
        _quotation_inputs(tmp_path)
    )
    assembly_root = tmp_path / "assembly"
    assembly_root.mkdir()
    (assembly_root / "assembly.json").write_bytes(canonical_bytes(transcript))
    corpus_root = persist_utterance_corpus(
        utterance_run,
        corpus,
        transcript,
        speaker_view,
        values[1],
        tmp_path / "corpus",
    )[3]
    command = [
        "--json",
        "utterance",
        "quotation-build",
        str(corpus_root),
        str(assembly_root),
        str(tmp_path / "quotation"),
    ]
    assert main(command) == 0
    first = json.loads(capsys.readouterr().out)
    assert not first["reused"]
    quotation_root = first["quotation_root"]
    assert first["report"]["quotation_count"] == 1
    assert first["report"]["embedded_source_count"] == 1
    assert main(command) == 0
    assert json.loads(capsys.readouterr().out)["reused"]
    for action in (
        "quotation-inspect",
        "list-quotations",
        "list-embedded-sources",
    ):
        assert main(["--json", "utterance", action, quotation_root]) == 0
        assert json.loads(capsys.readouterr().out) is not None
    assert main(
        [
            "--json",
            "utterance",
            "quotation-validate",
            quotation_root,
            str(corpus_root),
            str(assembly_root),
        ]
    ) == 0
    assert json.loads(capsys.readouterr().out)["valid"]
