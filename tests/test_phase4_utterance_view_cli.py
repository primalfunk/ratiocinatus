from __future__ import annotations

import json
from pathlib import Path

import pytest

from ratiocinatus.cli import main
from ratiocinatus.quotation_evidence import (
    build_quotation_evidence,
    persist_quotation_evidence,
)
from ratiocinatus.turn_repair import (
    build_turn_repair_run,
    persist_turn_repair_run,
)
from ratiocinatus.utterance_analysis import (
    analyze_utterance_corpus,
    persist_utterance_analysis,
)
from ratiocinatus.utterance_relations import (
    build_utterance_relations,
    persist_utterance_relations,
)
from ratiocinatus.utterance_segmentation import persist_utterance_corpus
from ratiocinatus.utterance_view_contracts import SpeakerAttributedViewKind

from test_phase3_clustering import HAS_FFMPEG
from test_phase3_speaker_transcript import NOW
from test_phase4_quotation import _quotation_inputs


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_view_cli_build_render_inspect_list_validate_and_replay(
    tmp_path: Path, capsys,
) -> None:
    values, transcript, speaker_view, utterance_run, corpus = (
        _quotation_inputs(tmp_path)
    )
    diarization = values[1]
    analysis = analyze_utterance_corpus(
        utterance_run, corpus, transcript, created_at=NOW
    )
    relations = build_utterance_relations(
        utterance_run, corpus, analysis, diarization, created_at=NOW
    )
    repair = build_turn_repair_run(
        utterance_run,
        corpus,
        transcript,
        speaker_view,
        diarization,
        created_at=NOW,
    )
    quotation = build_quotation_evidence(
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
    relation_root = persist_utterance_relations(
        relations,
        utterance_run,
        corpus,
        analysis,
        diarization,
        tmp_path / "relations",
    )[2]
    repair_root = persist_turn_repair_run(
        repair,
        utterance_run,
        corpus,
        transcript,
        speaker_view,
        diarization,
        tmp_path / "repair",
    )[2]
    quotation_root = persist_quotation_evidence(
        quotation,
        utterance_run,
        corpus,
        transcript,
        tmp_path / "quotation",
    )[2]
    sources = [
        str(corpus_root),
        str(analysis_root),
        str(relation_root),
        str(repair_root),
        str(quotation_root),
    ]
    command = [
        "--json",
        "utterance",
        "view-build",
        *sources,
        str(tmp_path / "views"),
    ]
    assert main(command) == 0
    first = json.loads(capsys.readouterr().out)
    assert not first["reused"]
    assert len(first["bundle"]["views"]) == 6
    view_root = first["utterance_view_root"]
    assert main(command) == 0
    assert json.loads(capsys.readouterr().out)["reused"]

    for action in ("view-inspect", "view-list"):
        assert main(["--json", "utterance", action, view_root]) == 0
        assert json.loads(capsys.readouterr().out) is not None
    assert main(
        [
            "--json",
            "utterance",
            "view-render",
            view_root,
            SpeakerAttributedViewKind.UNKNOWN_PRESERVING.value,
        ]
    ) == 0
    assert json.loads(capsys.readouterr().out)["kind"] == (
        SpeakerAttributedViewKind.UNKNOWN_PRESERVING.value
    )
    assert main(
        [
            "--json",
            "utterance",
            "view-validate",
            view_root,
            *sources,
        ]
    ) == 0
    assert json.loads(capsys.readouterr().out)["valid"]
