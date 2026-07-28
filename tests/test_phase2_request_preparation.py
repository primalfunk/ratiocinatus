from __future__ import annotations

import shutil
import wave
from array import array
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ratiocinatus.corpus import load_corpus
from ratiocinatus.ingestion import prepare_ingestion_request, run_ingestion
from ratiocinatus.phase2_contracts import SpeechActivityPolicy
from ratiocinatus.speech_evidence import prepare_speech_activity_request
from ratiocinatus.speech_providers import SpeechProviderRegistry

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_speech_request_identity_tracks_evidence_configuration(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.wav"
    samples = array("h", (index % 500 for index in range(48_000)))
    with wave.open(str(source), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(48_000)
        output.writeframes(samples.tobytes())

    request = prepare_ingestion_request(source, tmp_path / "workspace")
    manifest = run_ingestion(request)
    loaded = load_corpus(
        Path(request.workspace)
        / "ingestions"
        / request.ingestion_id
        / "corpus"
    )
    provider = SpeechProviderRegistry.with_boundaries().get(
        "unconfigured.speech_activity"
    ).capabilities.identity
    first = prepare_speech_activity_request(
        loaded["corpus"],
        loaded["audio"],
        loaded["timeline"],
        loaded["chunks"],
        provider,
        datetime(2000, 1, 1, tzinfo=timezone.utc),
    )
    repeated = prepare_speech_activity_request(
        loaded["corpus"],
        loaded["audio"],
        loaded["timeline"],
        loaded["chunks"],
        provider,
        datetime(2001, 1, 1, tzinfo=timezone.utc),
    )
    changed = prepare_speech_activity_request(
        loaded["corpus"],
        loaded["audio"],
        loaded["timeline"],
        loaded["chunks"],
        provider,
        datetime(2000, 1, 1, tzinfo=timezone.utc),
        policy=SpeechActivityPolicy(speech_threshold=0.7),
    )

    assert manifest.checkpoint.complete
    assert first.request_id == repeated.request_id
    assert first.configuration_hash == repeated.configuration_hash
    assert changed.request_id != first.request_id
