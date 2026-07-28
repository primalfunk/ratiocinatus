from __future__ import annotations

import shutil
import wave
from array import array
from decimal import Decimal
from pathlib import Path

import pytest

from ratiocinatus.media import inspect_media
from ratiocinatus.normalization import (
    AudioNormalizationError,
    equal_weight_pan_filter,
    inspect_cache,
    normalize_audio,
)
from ratiocinatus.normalization_contracts import (
    AudioNormalizationPolicy,
    CacheDisposition,
    NORMALIZATION_CONTRACT_MODELS,
)
from ratiocinatus.selection import select_streams

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def write_wave(
    path: Path,
    *,
    channels: int = 2,
    sample_rate: int = 11_025,
    seconds: int = 1,
) -> None:
    samples = array("h")
    for index in range(sample_rate * seconds):
        for channel in range(channels):
            samples.append(((index * (channel + 1)) % 2000) - 1000)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(samples.tobytes())


def test_normalization_contract_schemas_are_closed() -> None:
    for model in NORMALIZATION_CONTRACT_MODELS:
        assert model.model_json_schema().get("additionalProperties") is False


@pytest.mark.parametrize("channels", [2, 3, 6])
def test_equal_weight_downmix_has_unit_total_gain(channels: int) -> None:
    expression = equal_weight_pan_filter(channels)
    assert expression is not None
    coefficients = [
        Decimal(term.split("*", 1)[0])
        for term in expression.split("=", 2)[2].split("+")
    ]
    assert len(coefficients) == channels
    assert sum(coefficients) == Decimal(1)


def test_mono_requires_no_downmix_filter() -> None:
    assert equal_weight_pan_filter(1) is None
    with pytest.raises(ValueError):
        equal_weight_pan_filter(0)


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_normalize_cache_hit_corruption_rebuild_and_policy_invalidation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "unusual rate stereo.wav"
    write_wave(source)
    inspection = inspect_media(source)
    selection = select_streams(inspection)
    output_root = tmp_path / "workspace with spaces"

    first = normalize_audio(inspection, selection, output_root)
    assert first.cache_disposition == CacheDisposition.MISS
    derivative_path = (
        Path(first.cache_entry_path) / first.derivative.relative_path
    )
    assert derivative_path.is_file()
    assert first.derivative.sample_rate == 16_000
    assert first.derivative.channels == 1
    assert first.derivative.sample_format == "s16"
    assert first.derivative.original_channel_count == 2
    assert first.derivative.integrity.valid

    second = normalize_audio(inspection, selection, output_root)
    assert second.cache_disposition == CacheDisposition.HIT
    assert second.derivative.content_sha256 == first.derivative.content_sha256

    with derivative_path.open("ab") as stream:
        stream.write(b"corruption")
    rebuilt = normalize_audio(inspection, selection, output_root)
    assert rebuilt.cache_disposition == CacheDisposition.REBUILT
    assert rebuilt.derivative.content_sha256 == first.derivative.content_sha256
    assert any((output_root / "cache/audio-normalize/invalid").iterdir())

    rebuilt_path = Path(rebuilt.cache_entry_path) / rebuilt.derivative.relative_path
    with rebuilt_path.open("ab") as stream:
        stream.write(b"corruption again")
    with pytest.raises(AudioNormalizationError, match="refuses rebuild"):
        normalize_audio(
            inspection,
            selection,
            output_root,
            policy=AudioNormalizationPolicy(invalid_cache_action="refuse"),
        )
    normalize_audio(inspection, selection, output_root)

    changed = normalize_audio(
        inspection,
        selection,
        output_root,
        policy=AudioNormalizationPolicy(sample_rate=8_000),
    )
    assert changed.cache_disposition == CacheDisposition.MISS
    assert changed.cache_key.digest != first.cache_key.digest
    assert changed.derivative.sample_rate == 8_000
    assert len(inspect_cache(output_root)) == 2


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_bypassed_normalization_never_overwrites(tmp_path: Path) -> None:
    source = tmp_path / "mono.wav"
    write_wave(source, channels=1, sample_rate=48_000)
    inspection = inspect_media(source)
    selection = select_streams(inspection)
    output = tmp_path / "output"
    result = normalize_audio(
        inspection, selection, output, use_cache=False
    )
    assert result.cache_disposition == CacheDisposition.BYPASSED
    with pytest.raises(FileExistsError):
        normalize_audio(inspection, selection, output, use_cache=False)
