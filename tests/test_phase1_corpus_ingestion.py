from __future__ import annotations

import shutil
import wave
from array import array
from pathlib import Path

import pytest

from ratiocinatus.corpus import export_corpus, load_corpus, validate_corpus
from ratiocinatus.corpus_contracts import (
    CORPUS_CONTRACT_MODELS,
    IngestionPolicy,
    IngestionStage,
    IngestionStageStatus,
)
from ratiocinatus.ingestion import (
    IngestionInterrupted,
    prepare_ingestion_request,
    run_ingestion,
)
from ratiocinatus.normalization_contracts import AudioNormalizationPolicy

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def write_wave(path: Path, seconds: int = 1) -> None:
    samples = array("h", ((index % 1000) - 500 for index in range(48_000 * seconds)))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(48_000)
        output.writeframes(samples.tobytes())


def test_corpus_contract_schemas_are_closed() -> None:
    for model in CORPUS_CONTRACT_MODELS:
        assert model.model_json_schema().get("additionalProperties") is False


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_interruption_resume_portable_export_and_integrity(tmp_path: Path) -> None:
    source = tmp_path / "source audio.wav"
    write_wave(source)
    workspace = tmp_path / "workspace"
    request = prepare_ingestion_request(source, workspace)
    with pytest.raises(IngestionInterrupted, match="inspection_committed"):
        run_ingestion(
            request, interrupt_after=IngestionStage.INSPECTION_COMMITTED
        )

    manifest = run_ingestion(request)
    assert manifest.checkpoint.complete
    inspection_records = [
        item
        for item in manifest.checkpoint.records
        if item.stage == IngestionStage.INSPECTION_COMMITTED
    ]
    assert [item.status for item in inspection_records] == [
        IngestionStageStatus.COMMITTED,
        IngestionStageStatus.INTERRUPTED,
        IngestionStageStatus.REUSED,
    ]
    corpus_root = (
        workspace / "ingestions" / request.ingestion_id / "corpus"
    )
    report = validate_corpus(corpus_root)
    assert report.valid
    loaded = load_corpus(corpus_root)
    assert loaded["source_path"].is_file()
    assert loaded["audio_path"].is_file()
    assert loaded["video"].status.value == "not_applicable"
    assert loaded["chunks"].coverage_complete

    exported = export_corpus(corpus_root, tmp_path / "portable export")
    assert validate_corpus(exported).valid
    assert load_corpus(exported)["corpus"].corpus_id == loaded["corpus"].corpus_id

    normalized_audio = loaded["audio_path"].read_bytes()
    loaded["audio_path"].unlink()
    missing = validate_corpus(corpus_root)
    assert not missing.valid
    assert any("missing" in finding for finding in missing.findings)
    loaded["audio_path"].write_bytes(normalized_audio)
    assert validate_corpus(corpus_root).valid
    with loaded["audio_path"].open("ab") as stream:
        stream.write(b"substitution")
    broken = validate_corpus(corpus_root)
    assert not broken.valid
    assert any(
        "hash mismatch" in finding or "substitution" in finding
        for finding in broken.findings
    )


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_source_and_configuration_changes_create_new_ingestion_identity(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.wav"
    write_wave(source)
    workspace = tmp_path / "workspace"
    first = prepare_ingestion_request(source, workspace)
    changed_policy = prepare_ingestion_request(
        source,
        workspace,
        policy=IngestionPolicy(
            audio=AudioNormalizationPolicy(sample_rate=8_000)
        ),
    )
    assert first.ingestion_id != changed_policy.ingestion_id
    write_wave(source, seconds=2)
    changed_source = prepare_ingestion_request(source, workspace)
    assert first.ingestion_id != changed_source.ingestion_id
