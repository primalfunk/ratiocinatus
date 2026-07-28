from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from ratiocinatus.contracts import SourceFingerprint
from ratiocinatus.kernel import typed_id
from ratiocinatus.media import (
    MalformedInspectionOutput,
    discover_executable,
    parse_ffprobe_result,
)
from ratiocinatus.phase1_contracts import (
    ExternalToolIdentity,
    MediaInspectionRequest,
    MediaSupportStatus,
    PHASE1_CONTRACT_MODELS,
    StreamKind,
    ToolInvocationRecord,
)

NOW = datetime(2000, 1, 1, tzinfo=timezone.utc)
SHA = "a" * 64


def attachment_records() -> tuple[ToolInvocationRecord, ExternalToolIdentity]:
    return (
        ToolInvocationRecord(
            executable="/tools/ffprobe",
            arguments=("-print_format", "json", "source.mp4"),
            started_at=NOW,
            completed_at=NOW,
            exit_code=0,
            standard_error="",
        ),
        ExternalToolIdentity(
            executable="/tools/ffprobe",
            executable_sha256="b" * 64,
            version_line="ffprobe version test",
            build_configuration="--enable-test",
        ),
    )


def request(name: str = "source.mp4") -> MediaInspectionRequest:
    return MediaInspectionRequest(
        source=name,
        source_fingerprint=SourceFingerprint(digest=SHA, byte_size=1234),
    )


def test_phase1_contract_schemas_are_closed() -> None:
    for model in PHASE1_CONTRACT_MODELS:
        assert model.model_json_schema().get("additionalProperties") is False


def test_ffprobe_parse_inventory_and_stable_stream_id() -> None:
    invocation, tool = attachment_records()
    payload = {
        "streams": [
            {
                "index": 0,
                "codec_name": "h264",
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "time_base": "1/15360",
                "avg_frame_rate": "30/1",
                "r_frame_rate": "30/1",
                "duration": "2.500000",
                "disposition": {"default": 1, "attached_pic": 0},
                "tags": {"language": "eng"},
            },
            {
                "index": 1,
                "codec_name": "aac",
                "codec_type": "audio",
                "sample_rate": "48000",
                "channels": 2,
                "channel_layout": "stereo",
                "duration": "2.500000",
                "disposition": {"default": 1},
            },
            {
                "index": 2,
                "codec_name": "mjpeg",
                "codec_type": "video",
                "width": 600,
                "height": 600,
                "disposition": {"attached_pic": 1},
            },
        ],
        "format": {
            "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
            "format_long_name": "QuickTime / MOV",
            "duration": "2.500000",
            "start_time": "-0.021333",
            "bit_rate": "1000000",
            "size": "1234",
            "tags": {"title": "Test"},
        },
        "chapters": [],
        "programs": [],
    }
    raw = json.dumps(payload, sort_keys=True)
    first = parse_ffprobe_result(request(), raw, invocation, tool)
    second = parse_ffprobe_result(request("renamed.mp4"), raw, invocation, tool)
    assert first.support_status == MediaSupportStatus.SUPPORTED
    assert first.source_id == typed_id("src", SHA)
    assert first.container.duration_microseconds == 2_500_000
    assert first.container.start_time_microseconds == -21_333
    assert [stream.stream_type for stream in first.streams] == [
        StreamKind.VIDEO,
        StreamKind.AUDIO,
        StreamKind.ATTACHMENT,
    ]
    assert first.streams[1].sample_rate == 48_000
    assert first.streams[0].stream_id == second.streams[0].stream_id
    assert first.raw_attachment.raw_json_sha256 == hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()


def test_generic_decodable_path_and_malformed_output() -> None:
    invocation, tool = attachment_records()
    result = parse_ffprobe_result(
        request("source.odd"), '{"format":{},"streams":[]}', invocation, tool
    )
    assert result.support_status == MediaSupportStatus.DECODABLE_UNQUALIFIED
    with pytest.raises(MalformedInspectionOutput):
        parse_ffprobe_result(request(), "{bad", invocation, tool)


def test_duplicate_stream_index_is_rejected() -> None:
    invocation, tool = attachment_records()
    raw = json.dumps({
        "format": {},
        "streams": [
            {"index": 0, "codec_type": "audio", "disposition": {}},
            {"index": 0, "codec_type": "video", "disposition": {}},
        ],
    })
    with pytest.raises(ValidationError, match="stream indexes"):
        parse_ffprobe_result(request(), raw, invocation, tool)


def test_executable_discovery_rejects_missing_explicit_path(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="does not exist"):
        discover_executable(str(tmp_path / "missing ffprobe"))
