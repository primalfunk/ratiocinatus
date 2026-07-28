from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from ratiocinatus.addressing import map_interval
from ratiocinatus.addressing_contracts import (
    MappingClassification,
    MediaInterval,
    SourceTimeline,
    TimeDomain,
)
from ratiocinatus.cli import build_parser
from ratiocinatus.chunk_contracts import ChunkPolicy
from ratiocinatus.media import inspect_media
from ratiocinatus.normalization_contracts import AudioNormalizationPolicy
from ratiocinatus.packet_contracts import (
    PACKET_CONTRACT_MODELS,
    PacketContinuityPolicy,
)
from ratiocinatus.packets import (
    analyze_packet_payload,
    apply_packet_discontinuities,
    qualify_packet_continuity,
)
from ratiocinatus.selection import select_streams
from ratiocinatus.video_contracts import VideoNormalizationPolicy

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def test_packet_contract_schemas_are_closed() -> None:
    for model in PACKET_CONTRACT_MODELS:
        assert model.model_json_schema().get("additionalProperties") is False


def test_packet_analysis_detects_regression_missing_timestamp_and_gap() -> None:
    result = analyze_packet_payload(
        [
            {"pts_time": "0", "dts_time": "0", "duration_time": "0.04"},
            {"pts_time": "0.04", "dts_time": "0.04", "duration_time": "0.04"},
            {"pts_time": None, "dts_time": "3.0", "duration_time": "0.04"},
            {"pts_time": "2.9", "dts_time": "2.9", "duration_time": "0.04"},
        ],
        policy=PacketContinuityPolicy(),
    )
    assert result["missing_pts_count"] == 1
    assert result["dts_regression_count"] == 1
    assert result["large_gaps"] == [(40_000, 3_000_000)]


def test_packet_discontinuities_flow_into_interval_mapping() -> None:
    timeline = SourceTimeline(
        source_id="src_" + "a" * 32,
        source_start_microseconds=0,
        source_duration_microseconds=10_000_000,
        corpus_duration_microseconds=10_000_000,
        mapping_offset_microseconds=0,
    )
    from ratiocinatus.packet_contracts import PacketContinuityResult
    from ratiocinatus.media import inspect_tool

    # Avoid external discovery: build the result from a model-constructed tool
    # because this test exercises only the mapping handoff.
    from ratiocinatus.phase1_contracts import ExternalToolIdentity

    result = PacketContinuityResult(
        source_id=timeline.source_id,
        policy=PacketContinuityPolicy(),
        tool=ExternalToolIdentity(
            executable="ffprobe",
            executable_sha256="b" * 64,
            version_line="ffprobe version test",
        ),
        probes=(),
        discontinuities=(
            MediaInterval(
                domain=TimeDomain.SOURCE_MEDIA,
                start_microseconds=4_000_000,
                duration_microseconds=1_000_000,
            ),
        ),
        valid=False,
    )
    updated = apply_packet_discontinuities(timeline, result)
    mapping = map_interval(
        updated,
        MediaInterval(
            domain=TimeDomain.NORMALIZED_CORPUS,
            start_microseconds=3_500_000,
            duration_microseconds=2_000_000,
        ),
    )
    assert mapping.classification == MappingClassification.DISCONTINUOUS


def test_phase1_versions_are_compatibility_gates() -> None:
    with pytest.raises(ValidationError):
        AudioNormalizationPolicy(policy_version="9.0.0")
    with pytest.raises(ValidationError):
        ChunkPolicy(policy_version="9.0.0")
    timeline = SourceTimeline(
        source_id="src_" + "a" * 32,
        source_start_microseconds=0,
        source_duration_microseconds=1,
        corpus_duration_microseconds=1,
        mapping_offset_microseconds=0,
    )
    payload = timeline.model_dump(mode="json")
    payload["format_version"] = "9.0.0"
    with pytest.raises(ValidationError):
        SourceTimeline.model_validate(payload)


def test_packet_cli_is_exposed() -> None:
    args = build_parser().parse_args(
        ["media", "packets", "source.mp4", "--probe-duration-ms", "500"]
    )
    assert args.action == "packets"
    assert args.probe_duration_ms == 500


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_real_packet_continuity_qualification(tmp_path: Path) -> None:
    source = tmp_path / "packet source.mp4"
    subprocess.run(
        [
            shutil.which("ffmpeg"),
            "-hide_banner",
            "-nostdin",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x120:rate=30:duration=3",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=16000:duration=3",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            "-n",
            str(source),
        ],
        check=True,
    )
    inspection = inspect_media(source)
    selection = select_streams(inspection)
    result = qualify_packet_continuity(
        inspection,
        selection,
        policy=PacketContinuityPolicy(
            probe_duration_microseconds=500_000
        ),
    )
    assert result.valid
    assert len(result.probes) == 6
    assert all(probe.packet_count > 0 for probe in result.probes)
