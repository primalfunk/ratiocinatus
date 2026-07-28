from __future__ import annotations

import shutil
import wave
from array import array
from pathlib import Path

import pytest

from ratiocinatus.corpus import validate_corpus
from ratiocinatus.corpus_contracts import (
    IngestionStage,
    IngestionStageStatus,
)
from ratiocinatus.ingestion import (
    IngestionInterrupted,
    prepare_ingestion_request,
    run_ingestion,
)
from ratiocinatus.kernel import load_contract
from ratiocinatus.normalization_contracts import AudioNormalizationResult

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def write_wave(path: Path, seconds: int = 1) -> None:
    samples = array(
        "h",
        ((index % 1000) - 500 for index in range(16_000 * seconds)),
    )
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(samples.tobytes())


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_resume_detects_and_rebuilds_committed_derivative(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.wav"
    write_wave(source)
    workspace = tmp_path / "workspace"
    request = prepare_ingestion_request(source, workspace)
    with pytest.raises(IngestionInterrupted):
        run_ingestion(
            request,
            interrupt_after=IngestionStage.AUDIO_NORMALIZATION_COMMITTED,
        )
    run_root = workspace / "ingestions" / request.ingestion_id
    result = load_contract(
        (run_root / "state/audio-normalization.json").read_bytes(),
        AudioNormalizationResult,
    )
    assert isinstance(result, AudioNormalizationResult)
    derivative = (
        Path(result.cache_entry_path) / result.derivative.relative_path
    )
    with derivative.open("ab") as stream:
        stream.write(b"committed derivative substitution")

    manifest = run_ingestion(request)
    audio_records = [
        record
        for record in manifest.checkpoint.records
        if record.stage == IngestionStage.AUDIO_NORMALIZATION_COMMITTED
    ]
    assert any(
        record.status == IngestionStageStatus.INVALIDATED
        for record in audio_records
    )
    assert audio_records[-1].status == IngestionStageStatus.COMMITTED
    assert any((workspace / "cache/audio-normalize/invalid").iterdir())
    assert validate_corpus(run_root / "corpus").valid


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_resume_preserves_orphan_partial_as_failed_attempt(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.wav"
    write_wave(source)
    workspace = tmp_path / "workspace"
    request = prepare_ingestion_request(source, workspace)
    with pytest.raises(IngestionInterrupted):
        run_ingestion(
            request,
            interrupt_after=IngestionStage.INSPECTION_COMMITTED,
        )
    run_root = workspace / "ingestions" / request.ingestion_id
    partial = run_root / "state/selection.json.partial-simulated-crash"
    partial.write_bytes(b'{"incomplete":')

    manifest = run_ingestion(request)
    selection_records = [
        record
        for record in manifest.checkpoint.records
        if record.stage == IngestionStage.SELECTION_COMMITTED
    ]
    failed = [
        record
        for record in selection_records
        if record.status == IngestionStageStatus.FAILED
    ]
    assert len(failed) == 1
    assert failed[0].artifact is not None
    assert "orphan partial output preserved" in (failed[0].message or "")
    preserved = run_root / failed[0].artifact.relative_path
    assert preserved.read_bytes() == b'{"incomplete":'
    assert manifest.checkpoint.complete
    assert validate_corpus(run_root / "corpus").valid
