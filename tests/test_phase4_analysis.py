from __future__ import annotations

import json
from pathlib import Path

import pytest

from ratiocinatus.cli import main
from ratiocinatus.kernel import canonical_bytes, canonical_hash
from ratiocinatus.phase4_contracts import (
    DisfluencyKind,
    UtteranceCompletenessClassification,
)
from ratiocinatus.speaker_transcript import (
    build_speaker_labeled_transcript,
)
from ratiocinatus.transcript_assembly import validate_transcript_assembly
from ratiocinatus.transcript_contracts import (
    TranscriptArtifactDigest,
    TranscriptAssembly,
    TranscriptVersion,
)
from ratiocinatus.utterance_analysis import (
    UtteranceAnalysisIntegrityError,
    analyze_utterance_corpus,
    load_utterance_analysis,
    persist_utterance_analysis,
    validate_utterance_analysis,
)
from ratiocinatus.utterance_segmentation import (
    build_utterance_corpus,
    persist_utterance_corpus,
)

from test_phase3_clustering import HAS_FFMPEG
from test_phase3_speaker_transcript import NOW, _seal, _speaker_inputs
from test_phase4_segmentation import _with_words


def _with_surfaces(
    assembly: TranscriptAssembly, surfaces: tuple[str, ...]
) -> TranscriptAssembly:
    words = tuple(
        _seal(
            type(word),
            {
                **word.model_dump(exclude={"integrity_sha256"}),
                "surface_text": surfaces[index],
                "normalized_form": surfaces[index].casefold(),
            },
        )
        for index, word in enumerate(assembly.words)
    )
    version_payload = assembly.version.model_dump(
        exclude={"integrity_sha256", "words"}
    )
    version_payload["words"] = tuple(
        TranscriptArtifactDigest(
            artifact_id=item.word_id,
            content_sha256=canonical_hash(item),
        )
        for item in words
    )
    version = _seal(TranscriptVersion, version_payload)
    assembly_payload = assembly.model_dump(
        exclude={"integrity_sha256", "version", "words"}
    )
    assembly_payload["version"] = version
    assembly_payload["words"] = words
    result = _seal(TranscriptAssembly, assembly_payload)
    validate_transcript_assembly(result)
    return result


def _inputs(tmp_path: Path):
    values, transcript, identity_assembly = _speaker_inputs(tmp_path)
    diarization = values[1]
    transcript = _with_words(transcript)
    surfaces = tuple(
        "um" if index == 0 else word.surface_text
        for index, word in enumerate(transcript.words)
    )
    transcript = _with_surfaces(transcript, surfaces)
    speaker_view = build_speaker_labeled_transcript(
        transcript, diarization, identity_assembly, created_at=NOW
    )
    run, corpus = build_utterance_corpus(
        transcript, speaker_view, diarization, created_at=NOW
    )
    return values, transcript, speaker_view, run, corpus


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_analysis_is_deterministic_non_destructive_and_conservative(
    tmp_path: Path,
) -> None:
    _, transcript, _, run, corpus = _inputs(tmp_path)
    before = corpus.model_dump_json()
    analysis = analyze_utterance_corpus(
        run, corpus, transcript, created_at=NOW
    )
    repeated = analyze_utterance_corpus(
        run, corpus, transcript, created_at=NOW
    )

    assert repeated == analysis
    assert corpus.model_dump_json() == before
    assert len(analysis.completeness_assessments) == len(corpus.utterances)
    assert all(
        item.classification
        in set(UtteranceCompletenessClassification)
        for item in analysis.completeness_assessments
    )
    fillers = tuple(
        item
        for item in analysis.disfluency_spans
        if item.kind == DisfluencyKind.FILLER
    )
    assert fillers
    assert fillers[0].surface_text == "um"
    assert fillers[0].transcript_word_ids
    assert all(item.surface_text for item in analysis.disfluency_spans)


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_analysis_persistence_replays_and_rejects_tampering(
    tmp_path: Path,
) -> None:
    _, transcript, _, run, corpus = _inputs(tmp_path)
    analysis = analyze_utterance_corpus(
        run, corpus, transcript, created_at=NOW
    )
    first = persist_utterance_analysis(
        analysis, run, corpus, transcript, tmp_path / "analysis"
    )
    replay = persist_utterance_analysis(
        analysis, run, corpus, transcript, tmp_path / "analysis"
    )
    assert not first[3]
    assert replay[3]
    loaded = load_utterance_analysis(first[2])
    assert loaded == first[:2]
    validate_utterance_analysis(
        loaded[0], run, corpus, transcript, report=loaded[1]
    )

    tampered = analysis.model_copy(
        update={"configuration_hash": "f" * 64}
    )
    with pytest.raises(
        UtteranceAnalysisIntegrityError, match="integrity is invalid"
    ):
        validate_utterance_analysis(tampered, run, corpus, transcript)


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_analysis_cli_analyze_inspect_lists_validate_and_replay(
    tmp_path: Path, capsys,
) -> None:
    values, transcript, speaker_view, run, corpus = _inputs(tmp_path)
    assembly_root = tmp_path / "assembly"
    assembly_root.mkdir()
    (assembly_root / "assembly.json").write_bytes(canonical_bytes(transcript))
    corpus_root = persist_utterance_corpus(
        run,
        corpus,
        transcript,

        speaker_view,

        values[1],
        tmp_path / "corpus",
    )[3]
    command = [
        "--json",
        "utterance",
        "analyze",
        str(corpus_root),
        str(assembly_root),
        str(tmp_path / "analysis"),
    ]
    assert main(command) == 0
    first = json.loads(capsys.readouterr().out)
    assert not first["reused"]
    analysis_root = first["utterance_analysis_root"]
    assert main(command) == 0
    assert json.loads(capsys.readouterr().out)["reused"]
    for action in (
        "analysis-inspect",
        "list-incomplete",
        "list-disfluencies",
        "list-self-repairs",
    ):
        assert main(["--json", "utterance", action, analysis_root]) == 0
        assert json.loads(capsys.readouterr().out) is not None
    assert main(
        [
            "--json",
            "utterance",
            "analysis-validate",
            analysis_root,
            str(corpus_root),
            str(assembly_root),
        ]
    ) == 0
    assert json.loads(capsys.readouterr().out)["valid"]
