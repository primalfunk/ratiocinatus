from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ratiocinatus.contracts import SourceFingerprint
from ratiocinatus.phase1_contracts import (
    AudioStreamDescriptor,
    ContainerDescriptor,
    ExternalToolIdentity,
    MediaInspectionResult,
    MediaSupportStatus,
    MediaStreamDescriptor,
    RawInspectionAttachment,
    StreamDisposition,
    StreamKind,
    ToolInvocationRecord,
    VideoStreamDescriptor,
)
from ratiocinatus.qualification import _probe, probe_positions
from ratiocinatus.qualification_contracts import (
    DecodeQualificationPolicy,
    QUALIFICATION_CONTRACT_MODELS,
    QualificationStatus,
)
from ratiocinatus.selection import StreamSelectionError, select_streams
from ratiocinatus.selection_contracts import (
    CandidateDisposition,
    SELECTION_CONTRACT_MODELS,
    StreamSelectionPolicy,
)

NOW = datetime(2000, 1, 1, tzinfo=timezone.utc)


def sid(character: str) -> str:
    return "stream_" + character * 32


def inspection(
    streams: tuple[MediaStreamDescriptor, ...] | None = None,
) -> MediaInspectionResult:
    invocation = ToolInvocationRecord(
        executable="/tools/ffprobe",
        arguments=("-print_format", "json"),
        started_at=NOW,
        completed_at=NOW,
        exit_code=0,
        standard_error="",
    )
    tool = ExternalToolIdentity(
        executable="/tools/ffprobe",
        executable_sha256="f" * 64,
        version_line="ffprobe version test",
    )
    if streams is None:
        streams = (
            VideoStreamDescriptor(
                stream_id=sid("0"),
                stream_index=0,
                disposition=StreamDisposition(),
                codec_name="h264",
                width=1920,
                height=1080,
            ),
            AudioStreamDescriptor(
                stream_id=sid("1"),
                stream_index=1,
                disposition=StreamDisposition(default=True),
                codec_name="aac",
                sample_rate=48_000,
                channels=2,
                channel_layout="stereo",
            ),
            VideoStreamDescriptor(
                stream_id=sid("2"),
                stream_index=2,
                disposition=StreamDisposition(default=True),
                codec_name="vp9",
                width=1280,
                height=720,
            ),
            AudioStreamDescriptor(
                stream_id=sid("3"),
                stream_index=3,
                disposition=StreamDisposition(),
                codec_name="opus",
                sample_rate=48_000,
                channels=1,
                channel_layout="mono",
            ),
            MediaStreamDescriptor(
                stream_id=sid("4"),
                stream_index=4,
                stream_type=StreamKind.ATTACHMENT,
                disposition=StreamDisposition(attached_picture=True),
                codec_name="mjpeg",
            ),
        )
    raw = json.dumps({"format": {}, "streams": []})
    return MediaInspectionResult(
        source_id="src_" + "a" * 32,
        source="/evidence/source.mp4",
        source_fingerprint=SourceFingerprint(digest="a" * 64, byte_size=1000),
        support_status=MediaSupportStatus.SUPPORTED,
        container=ContainerDescriptor(
            duration_microseconds=10_000_000,
            file_size=1000,
        ),
        streams=streams,
        raw_attachment=RawInspectionAttachment(
            raw_json=raw,
            raw_json_sha256=__import__("hashlib").sha256(raw.encode()).hexdigest(),
            invocation=invocation,
            tool=tool,
        ),
    )


def test_selection_and_qualification_contract_schemas_are_closed() -> None:
    for model in (*SELECTION_CONTRACT_MODELS, *QUALIFICATION_CONTRACT_MODELS):
        assert model.model_json_schema().get("additionalProperties") is False


def test_default_selection_prefers_defaults_and_excludes_cover_art() -> None:
    result = select_streams(inspection())
    assert result.valid
    assert result.audio.selected_stream_index == 1
    assert result.video.selected_stream_index == 2
    attached = next(
        item for item in result.video.candidates if item.stream_index == 4
    )
    assert not attached.eligible
    assert attached.final_disposition == CandidateDisposition.DISQUALIFIED
    assert "attached_picture_excluded" in attached.rejection_reasons


def test_explicit_selection_is_deterministic_and_validated() -> None:
    policy = StreamSelectionPolicy(
        explicit_audio_stream_index=3,
        explicit_video_stream_index=0,
    )
    first = select_streams(inspection(), policy)
    second = select_streams(inspection(), policy)
    assert first == second
    assert first.audio.selected_stream_index == 3
    assert first.video.selected_stream_index == 0
    with pytest.raises(StreamSelectionError, match="absent"):
        select_streams(
            inspection(), StreamSelectionPolicy(explicit_audio_stream_index=99)
        )
    with pytest.raises(StreamSelectionError, match="not eligible"):
        select_streams(
            inspection(), StreamSelectionPolicy(explicit_video_stream_index=4)
        )


def test_audio_only_is_valid_but_required_audio_absence_is_not() -> None:
    audio = AudioStreamDescriptor(
        stream_id=sid("1"),
        stream_index=1,
        disposition=StreamDisposition(default=True),
        codec_name="flac",
        sample_rate=48_000,
        channels=2,
    )
    audio_only = select_streams(inspection((audio,)))
    assert audio_only.valid
    assert audio_only.video.selected_stream_id is None
    video = VideoStreamDescriptor(
        stream_id=sid("0"),
        stream_index=0,
        disposition=StreamDisposition(default=True),
        codec_name="h264",
        width=1920,
        height=1080,
    )
    no_audio = select_streams(inspection((video,)))
    assert not no_audio.valid


def test_probe_positions_cover_early_middle_and_late() -> None:
    assert probe_positions(10_000_000, 1_000_000) == (
        ("early", 0),
        ("middle", 4_500_000),
        ("late", 9_000_000),
    )
    assert probe_positions(500_000, 1_000_000) == (
        ("early", 0),
        ("middle", 0),
        ("late", 0),
    )


def test_probe_timeout_is_typed_and_preserves_invocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=1)

    monkeypatch.setattr(subprocess, "run", timeout)
    result = _probe(
        tmp_path / "ffmpeg",
        tmp_path / "source.mp4",
        sid("1"),
        1,
        StreamKind.AUDIO,
        "early",
        0,
        1_000_000,
        1,
    )
    assert result.status == QualificationStatus.FAILURE
    assert result.invocation.timed_out
    assert result.invocation.exit_code == -1


def test_qualification_policy_rejects_unbounded_values() -> None:
    with pytest.raises(ValueError):
        DecodeQualificationPolicy(probe_duration_microseconds=1)
    with pytest.raises(ValueError):
        DecodeQualificationPolicy(timeout_seconds=0)

def test_probe_rejects_zero_exit_without_decoded_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_output(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="frame=0\nout_time_us=N/A\nprogress=end\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", no_output)
    result = _probe(
        tmp_path / "ffmpeg",
        tmp_path / "truncated.mp4",
        sid("0"),
        0,
        StreamKind.VIDEO,
        "late",
        9_000_000,
        1_000_000,
        1,
    )
    assert result.status == QualificationStatus.FAILURE
    assert result.message == "FFmpeg produced no decoded output"