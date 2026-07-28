from __future__ import annotations

import json
import math
import shutil
import wave
from array import array
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ratiocinatus.activity import (
    EnergyActivityConfiguration,
    FFmpegEnergySpeechActivityProvider,
)
from ratiocinatus.addressing_contracts import SourceTimeline
from ratiocinatus.chunk_contracts import ChunkPolicy
from ratiocinatus.chunking import build_chunk_plan
from ratiocinatus.cli import EXIT_SUCCESS, main
from ratiocinatus.corpus import load_corpus
from ratiocinatus.ingestion import prepare_ingestion_request, run_ingestion
from ratiocinatus.media import sha256_file
from ratiocinatus.phase1_contracts import ToolInvocationRecord
from ratiocinatus.phase2_contracts import (
    SpeechActivityClassification,
    SpeechActivityPolicy,
    SpeechActivityRequest,
)
from ratiocinatus.speech_activity import (
    SpeechActivityIntegrityError,
    detect_corpus_activity,
)

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
NOW = datetime(2000, 1, 1, tzinfo=timezone.utc)


def write_silence_tone_silence(path: Path) -> None:
    samples = array("h")
    for index in range(3 * 48_000):
        second = index / 48_000
        value = (
            int(0.25 * 32767 * math.sin(2 * math.pi * 440 * second))
            if 1 <= second < 2
            else 0
        )
        samples.append(value)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(48_000)
        output.writeframes(samples.tobytes())


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_energy_activity_persists_complete_report_and_reuses(
    tmp_path: Path, capsys,
) -> None:
    source = tmp_path / "silence-tone-silence.wav"
    write_silence_tone_silence(source)
    ingestion = prepare_ingestion_request(source, tmp_path / "phase1")
    run_ingestion(ingestion)
    corpus_root = (
        Path(ingestion.workspace)
        / "ingestions"
        / ingestion.ingestion_id
        / "corpus"
    )
    phase2_root = tmp_path / "phase2"
    run, report, stored, reused = detect_corpus_activity(
        corpus_root, phase2_root
    )

    assert run.complete and not reused
    assert report.status == "warning"
    assert report.coverage_complete
    assert sum(
        item.normalized_audio_interval.duration_microseconds
        for item in run.intervals
    ) == run.request.normalized_audio_duration_microseconds
    classifications = {item.classification for item in run.intervals}
    assert SpeechActivityClassification.PROBABLE_SPEECH in classifications
    assert SpeechActivityClassification.PROBABLE_NON_SPEECH in classifications
    assert (stored / "request.json").is_file()
    assert (stored / "run.json").is_file()
    assert (stored / "report.json").is_file()
    assert (stored / "report.md").is_file()

    repeated, repeated_report, repeated_root, reused = detect_corpus_activity(
        corpus_root, phase2_root
    )
    assert reused
    assert repeated.run_id == run.run_id
    assert repeated_report.report_id == report.report_id
    assert repeated_root == stored
    assert main([
        "--json",
        "speech",
        "detect",
        str(corpus_root),
        str(phase2_root),
    ]) == EXIT_SUCCESS
    payload = json.loads(capsys.readouterr().out)
    assert payload["reused"] is True
    assert payload["run"]["run_id"] == run.run_id
    run_path = stored / "run.json"
    corrupted = json.loads(run_path.read_text(encoding="utf-8"))
    corrupted["intervals"][0]["findings"].append("unrecorded mutation")
    run_path.write_text(json.dumps(corrupted), encoding="utf-8")
    with pytest.raises(
        SpeechActivityIntegrityError,
        match="evidence hash",
    ):
        detect_corpus_activity(corpus_root, phase2_root)


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_phase1_overlap_ownership_prevents_duplicate_activity(
    tmp_path: Path,
) -> None:
    class MemoryProvider(FFmpegEnergySpeechActivityProvider):
        def _decode_chunk(
            self,
            source: Path,
            *,
            start_microseconds: int,
            duration_microseconds: int,
            timeout_seconds: int,
        ):
            count = (
                duration_microseconds
                * self.configuration.sample_rate
                // 1_000_000
            )
            invocation = ToolInvocationRecord(
                executable="memory",
                arguments=(),
                started_at=NOW,
                completed_at=NOW,
                exit_code=0,
                standard_error="",
            )
            return array("h", [10_000]) * count, invocation

    source = tmp_path / "audio.bin"
    source.write_bytes(b"activity-source")
    timeline = SourceTimeline(
        source_id="src_" + "1" * 32,
        source_start_microseconds=0,
        source_duration_microseconds=2_000_000,
        corpus_duration_microseconds=2_000_000,
        mapping_offset_microseconds=0,
    )
    plan = build_chunk_plan(
        timeline,
        ChunkPolicy(
            target_duration_microseconds=1_000_000,
            overlap_microseconds=200_000,
            minimum_duration_microseconds=500_000,
            maximum_duration_microseconds=2_000_000,
        ),
    )
    provider = MemoryProvider(
        configuration=EnergyActivityConfiguration(
            sample_rate=1_000,
            frame_duration_microseconds=100_000,
        )
    )
    request = SpeechActivityRequest(
        request_id="sareq_" + "2" * 32,
        requested_at=NOW,
        corpus_id="corpus_" + "3" * 32,
        source_id=timeline.source_id,
        normalized_audio_sha256=sha256_file(source),
        normalized_audio_duration_microseconds=2_000_000,
        audio_derivative_duration_microseconds=2_000_000,
        chunk_plan_id=plan.plan_id,
        chunks=plan.chunks,
        source_mapping_offset_microseconds=0,
        policy=SpeechActivityPolicy(),
        provider=provider.capabilities.identity,
        configuration_hash="4" * 64,
    )
    result = provider.detect(request, source)

    assert result.complete
    assert len(result.intervals) == len(plan.chunks)
    assert sum(
        item.normalized_audio_interval.duration_microseconds
        for item in result.intervals
    ) == 2_000_000
    first_end = (
        result.intervals[0].normalized_audio_interval.start_microseconds
        + result.intervals[0].normalized_audio_interval.duration_microseconds
    )
    assert (
        result.intervals[1].normalized_audio_interval.start_microseconds
        == first_end
    )

@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_pinned_semantic_vad_rejects_tone_as_speech_and_can_evaluate(
    tmp_path: Path, capsys,
) -> None:
    pytest.importorskip("silero_vad")
    from ratiocinatus.silero_activity import SileroSpeechActivityProvider

    source = tmp_path / "silence-tone-silence.wav"
    write_silence_tone_silence(source)
    ingestion = prepare_ingestion_request(source, tmp_path / "phase1")
    run_ingestion(ingestion)
    corpus_root = (
        Path(ingestion.workspace)
        / "ingestions"
        / ingestion.ingestion_id
        / "corpus"
    )
    provider = SileroSpeechActivityProvider()
    run, _, stored, reused = detect_corpus_activity(
        corpus_root, tmp_path / "phase2", provider=provider
    )

    assert run.complete and not reused
    assert run.provider.provider_id == "local.silero_vad"
    assert run.provider.model_version == "6.2.1"
    assert run.provider.model_fingerprint == (
        "e1122837f4154c511485fe0b9c64455f7b929c96fbb8d79fbdb336383ebd3720"
    )
    assert not run.provider.model_redistributed
    assert not [
        item
        for item in run.intervals
        if item.classification
        == SpeechActivityClassification.PROBABLE_SPEECH
    ]

    schedule = tmp_path / "schedule.json"
    schedule.write_text(
        '{"fixture_id":"semantic-unit","lines":['
        '{"start_microseconds":1000000,"end_microseconds":2000000,'
        '"duration_microseconds":1000000}]}',
        encoding="utf-8",
    )
    output = tmp_path / "evaluation.json"
    assert main([
        "--json",
        "speech",
        "evaluate-activity",
        str(stored),
        str(schedule),
        "tone-control",
        "--output",
        str(output),
    ]) == EXIT_SUCCESS
    payload = json.loads(capsys.readouterr().out)
    assert payload["metrics"]["true_positive_microseconds"] == 0
    assert payload["metrics"]["false_negative_microseconds"] == 1_000_000
    assert output.is_file()

@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_semantic_vad_rejects_unqualified_model_fingerprint(
    monkeypatch,
) -> None:
    pytest.importorskip("silero_vad")
    from ratiocinatus.silero_activity import SileroSpeechActivityProvider

    monkeypatch.setattr(
        SileroSpeechActivityProvider,
        "EXPECTED_MODEL_SHA256",
        "0" * 64,
    )
    with pytest.raises(RuntimeError, match="model artifact hash"):
        SileroSpeechActivityProvider()

@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_semantic_vad_inherits_chunk_overlap_ownership(tmp_path: Path) -> None:
    pytest.importorskip("silero_vad")
    from ratiocinatus.silero_activity import SileroSpeechActivityProvider

    source = tmp_path / "chunked-tone.wav"
    write_silence_tone_silence(source)
    timeline = SourceTimeline(
        source_id="src_" + "8" * 32,
        source_start_microseconds=0,
        source_duration_microseconds=3_000_000,
        corpus_duration_microseconds=3_000_000,
        mapping_offset_microseconds=0,
    )
    plan = build_chunk_plan(
        timeline,
        ChunkPolicy(
            target_duration_microseconds=1_000_000,
            overlap_microseconds=200_000,
            minimum_duration_microseconds=500_000,
            maximum_duration_microseconds=2_000_000,
        ),
    )
    provider = SileroSpeechActivityProvider()
    request = SpeechActivityRequest(
        request_id="sareq_" + "9" * 32,
        requested_at=NOW,
        corpus_id="corpus_" + "a" * 32,
        source_id=timeline.source_id,
        normalized_audio_sha256=sha256_file(source),
        normalized_audio_duration_microseconds=3_000_000,
        audio_derivative_duration_microseconds=3_000_000,
        chunk_plan_id=plan.plan_id,
        chunks=plan.chunks,
        source_mapping_offset_microseconds=0,
        policy=SpeechActivityPolicy(),
        provider=provider.capabilities.identity,
        configuration_hash="b" * 64,
    )

    result = provider.detect(request, source)

    assert result.complete
    assert len(result.invocations) == len(plan.chunks)
    assert sum(
        item.normalized_audio_interval.duration_microseconds
        for item in result.intervals
    ) == 3_000_000
    assert {
        item.processing_chunk_id for item in result.intervals
    } == {item.chunk_id for item in plan.chunks}
