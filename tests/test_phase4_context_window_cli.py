from __future__ import annotations

import json
from pathlib import Path

import pytest

from ratiocinatus.cli import main
from ratiocinatus.quotation_evidence import persist_quotation_evidence
from ratiocinatus.turn_repair import persist_turn_repair_run
from ratiocinatus.utterance_analysis import persist_utterance_analysis
from ratiocinatus.utterance_relations import persist_utterance_relations
from ratiocinatus.utterance_segmentation import persist_utterance_corpus
from ratiocinatus.utterance_view_contracts import SpeakerAttributedViewKind
from ratiocinatus.utterance_views import (
    build_speaker_attributed_views,
    persist_speaker_attributed_views,
)
from ratiocinatus.context_window_contracts import ContextWindowKind

from test_phase3_clustering import HAS_FFMPEG
from test_phase3_speaker_transcript import NOW
from test_phase4_quotation import _quotation_inputs
from test_phase4_utterance_views import _view_inputs


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_context_cli_build_show_inspect_list_validate_and_replay(
    tmp_path: Path, capsys,
) -> None:
    values, transcript, speaker_view, _, _ = _quotation_inputs(tmp_path)
    inputs = _view_inputs(tmp_path)
    utterance_run, corpus, analysis, relations, repair, quotation = inputs
    diarization = values[1]
    corpus_root = persist_utterance_corpus(
        utterance_run,
        corpus,
        transcript,
        speaker_view,
        diarization,
        tmp_path / "corpus",
    )[3]
    analysis_root = persist_utterance_analysis(
        analysis, utterance_run, corpus, transcript, tmp_path / "analysis"
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
    view_bundle = build_speaker_attributed_views(
        *inputs, generated_at=NOW
    )
    view_root = persist_speaker_attributed_views(
        view_bundle, *inputs, tmp_path / "views"
    )[2]
    sources = [
        str(view_root),
        str(corpus_root),
        str(analysis_root),
        str(relation_root),
        str(repair_root),
        str(quotation_root),
    ]
    command = [
        "--json",
        "utterance",
        "context-build",
        *sources,
        str(tmp_path / "contexts"),
        "--maximum-utterances",
        "2",
    ]
    assert main(command) == 0
    first = json.loads(capsys.readouterr().out)
    assert not first["reused"]
    context_root = first["context_window_root"]
    assert first["report"]["window_count"] == len(corpus.utterances) * 9
    assert main(command) == 0
    assert json.loads(capsys.readouterr().out)["reused"]

    for action in (
        "context-inspect",
        "context-list",
        "list-truncated-context",
    ):
        assert main(["--json", "utterance", action, context_root]) == 0
        assert json.loads(capsys.readouterr().out) is not None
    target = corpus.utterances[0].utterance_id
    assert main(
        [
            "--json",
            "utterance",
            "context-show",
            context_root,
            target,
            ContextWindowKind.PRECEDING.value,
        ]
    ) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["target_utterance_id"] == target
    assert main(
        [
            "--json",
            "utterance",
            "context-validate",
            context_root,
            *sources,
        ]
    ) == 0
    assert json.loads(capsys.readouterr().out)["valid"]
