from __future__ import annotations

import json
from pathlib import Path

import pytest

from ratiocinatus.cli import main
from ratiocinatus.kernel import canonical_bytes, canonical_hash
from ratiocinatus.phase2_contracts import TimestampOrigin
from ratiocinatus.phase4_contracts import (
    UtteranceAttributionStatus,
    UtteranceReviewStatus,
    UtteranceSegmentationPolicy,
)
from ratiocinatus.speaker_transcript import (
    build_speaker_labeled_transcript,
    persist_speaker_labeled_transcript,
)
from ratiocinatus.transcript_assembly import validate_transcript_assembly
from ratiocinatus.transcript_contracts import (
    TranscriptArtifactDigest,
    TranscriptAssembly,
    TranscriptVersion,
    TranscriptWord,
)
from ratiocinatus.utterance_segmentation import (
    UtteranceSegmentationIntegrityError,
    build_utterance_corpus,
    load_utterance_corpus,
    persist_utterance_corpus,
    validate_utterance_corpus,
)

from test_phase3_clustering import HAS_FFMPEG
from test_phase3_speaker_transcript import (
    NOW,
    _confidence,
    _seal,
    _speaker_inputs,
)


def _with_words(assembly: TranscriptAssembly) -> TranscriptAssembly:
    words = []
    for ordinal, segment in enumerate(assembly.segments):
        payload = {
            "word_id": "txword_" + f"{ordinal + 1:x}" * 32,
            "segment_id": segment.segment_id,
            "corpus_id": segment.corpus_id,
            "source_interval": segment.source_interval,
            "normalized_audio_interval": segment.normalized_audio_interval,
            "surface_text": segment.proposed_text,
            "normalized_form": segment.normalized_text,
            "sequence_position": ordinal,
            "recognition_confidence": _confidence(),
            "timing_confidence": _confidence(),
            "timestamp_origin": TimestampOrigin.ESTIMATED,
            "provider_word_id": f"phase4-word-{ordinal}",
            "provider_observation_id": segment.provider_observation_id,
            "provider_candidate_id": segment.selected_candidate_id,
            "created_at": NOW,
        }
        words.append(_seal(TranscriptWord, payload))
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
    assembly_payload["words"] = tuple(words)
    result = _seal(TranscriptAssembly, assembly_payload)
    validate_transcript_assembly(result)
    return result


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_initial_segmentation_is_stable_source_addressed_and_unknown_safe(
    tmp_path: Path,
) -> None:
    values, transcript, identity_assembly = _speaker_inputs(tmp_path)
    diarization = values[1]
    transcript = _with_words(transcript)
    speaker_view = build_speaker_labeled_transcript(
        transcript, diarization, identity_assembly, created_at=NOW
    )
    before_transcript = transcript.model_dump_json()
    before_speaker = speaker_view.model_dump_json()

    run, corpus = build_utterance_corpus(
        transcript, speaker_view, diarization, created_at=NOW
    )
    repeated_run, repeated_corpus = build_utterance_corpus(
        transcript, speaker_view, diarization, created_at=NOW
    )
    assert repeated_run == run
    assert repeated_corpus == corpus
    assert canonical_hash(repeated_corpus) == canonical_hash(corpus)
    assert corpus.utterances
    assert any(
        item.attribution.status == UtteranceAttributionStatus.UNKNOWN
        for item in corpus.utterances
    )
    assert any(
        item.review_status == UtteranceReviewStatus.REVIEW_REQUIRED
        for item in corpus.utterances
    )
    word_ids = [
        word_id
        for utterance in corpus.utterances
        for component in utterance.components
        for word_id in component.transcript_word_ids
    ]
    assert len(word_ids) == len(set(word_ids))
    assert set(word_ids) == {item.word_id for item in transcript.words}
    assert all(
        item.source_intervals and item.normalized_audio_intervals
        for item in corpus.utterances
    )
    assert all(
        component.speaker_observation_ids
        for utterance in corpus.utterances
        for component in utterance.components
        if component.speaker_turn_ids
    )
    assert transcript.model_dump_json() == before_transcript
    assert speaker_view.model_dump_json() == before_speaker


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_persistence_replays_and_policy_changes_only_phase4_identity(
    tmp_path: Path,
) -> None:
    values, transcript, identity_assembly = _speaker_inputs(tmp_path)
    diarization = values[1]
    transcript = _with_words(transcript)
    speaker_view = build_speaker_labeled_transcript(
        transcript, diarization, identity_assembly, created_at=NOW
    )
    before_transcript = transcript.model_dump_json()
    run, corpus = build_utterance_corpus(
        transcript, speaker_view, diarization, created_at=NOW
    )
    first = persist_utterance_corpus(
        run, corpus, transcript, speaker_view, diarization, tmp_path / "phase4"
    )
    replay = persist_utterance_corpus(
        run, corpus, transcript, speaker_view, diarization, tmp_path / "phase4"
    )
    assert not first[4]
    assert replay[4]
    loaded = load_utterance_corpus(first[3])
    assert loaded[:2] == (run, corpus)
    assert validate_utterance_corpus(
        *loaded[:2], transcript, speaker_view, diarization, report=loaded[2]
    ).valid

    changed_run, changed_corpus = build_utterance_corpus(
        transcript,
        speaker_view,
        diarization,
        policy=UtteranceSegmentationPolicy(
            maximum_gap_microseconds=1
        ),
        created_at=NOW,
    )
    assert changed_run.configuration_hash != run.configuration_hash
    assert changed_corpus.corpus_id != corpus.corpus_id
    assert transcript.model_dump_json() == before_transcript

    corrupted = first[3] / "corpus.json"
    corrupted.write_text("{}", encoding="utf-8")
    with pytest.raises(Exception):
        persist_utterance_corpus(
            run, corpus, transcript, speaker_view, diarization, tmp_path / "phase4"
        )


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_incompatible_speaker_view_lineage_is_refused(tmp_path: Path) -> None:
    values, transcript, identity_assembly = _speaker_inputs(tmp_path)
    diarization = values[1]
    transcript = _with_words(transcript)
    speaker_view = build_speaker_labeled_transcript(
        transcript, diarization, identity_assembly, created_at=NOW
    )
    incompatible = speaker_view.model_copy(
        update={"source_assembly_id": "txassembly_" + "f" * 32}
    )
    with pytest.raises(
        UtteranceSegmentationIntegrityError, match="integrity is invalid"
    ):
        build_utterance_corpus(
            transcript, incompatible, diarization, created_at=NOW
        )


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_utterance_cli_build_list_inspect_validate_and_replay(
    tmp_path: Path, capsys
) -> None:
    values, transcript, identity_assembly = _speaker_inputs(tmp_path)
    diarization = values[1]
    transcript = _with_words(transcript)
    speaker_view = build_speaker_labeled_transcript(
        transcript, diarization, identity_assembly, created_at=NOW
    )
    assembly_root = tmp_path / "assembly"
    assembly_root.mkdir()
    (assembly_root / "assembly.json").write_bytes(canonical_bytes(transcript))
    speaker_persisted = persist_speaker_labeled_transcript(
        speaker_view,
        transcript,
        diarization,
        identity_assembly,
        tmp_path / "speaker",
    )
    destination = tmp_path / "utterance"
    command = [
        "--json",
        "utterance",
        "build",
        str(assembly_root),
        str(speaker_persisted[2]),
        str(values[11]),
        str(destination),
    ]
    assert main(command) == 0
    first = json.loads(capsys.readouterr().out)
    assert not first["reused"]
    root = first["utterance_corpus_root"]
    assert main(command) == 0
    assert json.loads(capsys.readouterr().out)["reused"]
    assert main(["--json", "utterance", "list", root]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed
    assert main(["--json", "utterance", "inspect", root]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["corpus"]["utterances"]
    assert main(
        [
            "--json",
            "utterance",
            "validate",
            root,
            str(assembly_root),
            str(speaker_persisted[2]),
            str(values[11]),
        ]
    ) == 0
    assert json.loads(capsys.readouterr().out)["valid"]
