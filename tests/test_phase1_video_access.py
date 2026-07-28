from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ratiocinatus.addressing_contracts import MediaInterval, TimeDomain
from ratiocinatus.contracts import SourceFingerprint
from ratiocinatus.media import inspect_media
from ratiocinatus.phase1_contracts import (
    AudioStreamDescriptor,
    ContainerDescriptor,
    ExternalToolIdentity,
    MediaInspectionResult,
    MediaSupportStatus,
    RawInspectionAttachment,
    StreamDisposition,
    ToolInvocationRecord,
    VideoStreamDescriptor,
)
from ratiocinatus.qualification import FFmpegDecodeQualificationProvider
from ratiocinatus.selection import select_streams
from ratiocinatus.video import (
    VideoAccessError,
    create_video_access_plan,
    extract_frame,
    frames_over_interval,
)
from ratiocinatus.video_contracts import (
    VIDEO_CONTRACT_MODELS,
    VideoAccessStatus,
)

NOW = datetime(2000, 1, 1, tzinfo=timezone.utc)
HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def inspection(audio_only: bool = False, variable: bool = False) -> MediaInspectionResult:
    audio = AudioStreamDescriptor(
        stream_id="stream_" + "1" * 32,
        stream_index=1 if not audio_only else 0,
        disposition=StreamDisposition(default=True),
        codec_name="aac",
        sample_rate=48_000,
        channels=2,
        duration_microseconds=2_000_000,
        start_time_microseconds=0,
    )
    streams = (audio,) if audio_only else (
        VideoStreamDescriptor(
            stream_id="stream_" + "0" * 32,
            stream_index=0,
            disposition=StreamDisposition(default=True),
            codec_name="h264",
            width=320,
            height=240,
            time_base="1/15360",
            pixel_format="yuv420p",
            average_frame_rate="30000/1001" if variable else "30/1",
            real_frame_rate="30/1",
            duration_microseconds=2_000_000,
            start_time_microseconds=0,
            rotation_degrees=90,
        ),
        audio,
    )
    raw = json.dumps({"streams": [], "format": {}})
    invocation = ToolInvocationRecord(
        executable="ffprobe",
        arguments=(),
        started_at=NOW,
        completed_at=NOW,
        exit_code=0,
        standard_error="",
    )
    return MediaInspectionResult(
        source_id="src_" + "a" * 32,
        source="source.mp4",
        source_fingerprint=SourceFingerprint(digest="a" * 64, byte_size=100),
        support_status=MediaSupportStatus.SUPPORTED,
        container=ContainerDescriptor(
            duration_microseconds=2_000_000,
            start_time_microseconds=0,
            file_size=100,
        ),
        streams=streams,
        raw_attachment=RawInspectionAttachment(
            raw_json=raw,
            raw_json_sha256=hashlib.sha256(raw.encode()).hexdigest(),
            invocation=invocation,
            tool=ExternalToolIdentity(
                executable="ffprobe",
                executable_sha256="b" * 64,
                version_line="ffprobe version test",
            ),
        ),
    )


def test_video_contract_schemas_are_closed() -> None:
    for model in VIDEO_CONTRACT_MODELS:
        assert model.model_json_schema().get("additionalProperties") is False


def test_unqualified_plan_preserves_video_metadata_without_transform() -> None:
    source = inspection(variable=True)
    plan = create_video_access_plan(source, select_streams(source))
    assert plan.status == VideoAccessStatus.UNQUALIFIED
    assert plan.variable_frame_rate
    assert plan.rotation_degrees == 90
    assert plan.transformations == ()
    assert plan.policy.frame_number_authoritative is False
    assert plan.policy.crop is False and plan.policy.resize is False


def test_audio_only_plan_is_valid_and_not_applicable() -> None:
    source = inspection(audio_only=True)
    plan = create_video_access_plan(source, select_streams(source))
    assert plan.status == VideoAccessStatus.NOT_APPLICABLE
    assert plan.video_stream_id is None
    assert plan.seek_qualified


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_timestamp_frame_lookup_interval_and_non_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "vidéo source with spaces.mp4"
    command = [
        shutil.which("ffmpeg"),
        "-hide_banner", "-nostdin", "-v", "error",
        "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=2",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", "-n", str(source),
    ]
    subprocess.run(command, check=True)
    inspected = inspect_media(source)
    selected = select_streams(inspected)
    qualified = FFmpegDecodeQualificationProvider().qualify(inspected, selected)
    plan = create_video_access_plan(inspected, selected, qualified)
    assert plan.status == VideoAccessStatus.AVAILABLE

    index = frames_over_interval(
        plan,
        MediaInterval(
            domain=TimeDomain.NORMALIZED_CORPUS,
            start_microseconds=400_000,
            duration_microseconds=200_000,
        ),
    )
    assert 4 <= len(index.corpus_timestamps) <= 8
    assert all(
        index.corpus_timestamps[position].microseconds
        <= index.corpus_timestamps[position + 1].microseconds
        for position in range(len(index.corpus_timestamps) - 1)
    )

    output = tmp_path / "fråme output.png"
    frame = extract_frame(plan, 500_000, output)
    assert output.is_file()
    assert frame.width == 320 and frame.height == 240
    assert frame.timestamp_error_microseconds <= 20_000
    assert frame.content_sha256 == hashlib.sha256(output.read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):
        extract_frame(plan, 500_000, output)

def test_video_policy_refuses_unsupported_pixel_format_and_time_base() -> None:
    source = inspection()
    video = source.streams[0]
    unsupported = source.model_copy(
        update={
            "streams": (
                video.model_copy(update={"pixel_format": "yuv444p"}),
                *source.streams[1:],
            )
        }
    )
    pixel_plan = create_video_access_plan(
        unsupported, select_streams(unsupported)
    )
    assert pixel_plan.status == VideoAccessStatus.REFUSED
    assert pixel_plan.policy_findings == (
        "unsupported pixel format: yuv444p",
    )

    invalid_time = source.model_copy(
        update={
            "streams": (
                video.model_copy(update={"time_base": "1/0"}),
                *source.streams[1:],
            )
        }
    )
    time_plan = create_video_access_plan(
        invalid_time, select_streams(invalid_time)
    )
    assert time_plan.status == VideoAccessStatus.REFUSED
    assert "unsupported or missing video time base" in time_plan.policy_findings
    with pytest.raises(VideoAccessError, match="not qualified and available"):
        frames_over_interval(
            time_plan,
            MediaInterval(
                domain=TimeDomain.NORMALIZED_CORPUS,
                start_microseconds=0,
                duration_microseconds=100_000,
            ),
        )