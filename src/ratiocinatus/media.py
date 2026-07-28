"""Production FFprobe boundary and canonical stream inventory."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from pathlib import Path
from typing import Any, Mapping

from .contracts import SourceFingerprint
from .kernel import typed_id
from .phase1_contracts import (
    AudioStreamDescriptor,
    ContainerDescriptor,
    ExternalToolIdentity,
    MediaInspectionRequest,
    MediaInspectionResult,
    MediaStreamDescriptor,
    MediaSupportStatus,
    RawInspectionAttachment,
    StreamDisposition,
    StreamKind,
    SubtitleStreamDescriptor,
    ToolInvocationRecord,
    VideoStreamDescriptor,
)

QUALIFIED_EXTENSIONS = {
    ".aac", ".avi", ".flac", ".m4a", ".mkv", ".mov", ".mp3", ".mp4",
    ".mpeg", ".mpg", ".ts", ".wav", ".webm",
}


class MediaInspectionError(RuntimeError):
    """Inspection failed before a trustworthy inventory could be produced."""


class ToolUnavailableError(MediaInspectionError):
    pass


class ToolTimeoutError(MediaInspectionError):
    pass


class MalformedInspectionOutput(MediaInspectionError):
    pass


def sha256_file(path: Path, block_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest()


def fingerprint_file(path: Path) -> SourceFingerprint:
    return SourceFingerprint(digest=sha256_file(path), byte_size=path.stat().st_size)


def discover_executable(explicit: str | None = None) -> Path:
    candidate = explicit or shutil.which("ffprobe")
    if not candidate:
        raise ToolUnavailableError(
            "FFprobe was not found; install FFmpeg or provide --ffprobe"
        )
    path = Path(candidate).expanduser().resolve()
    if not path.is_file():
        raise ToolUnavailableError(f"FFprobe executable does not exist: {path}")
    return path


def _run(
    executable: Path, arguments: tuple[str, ...], timeout_seconds: int
) -> tuple[subprocess.CompletedProcess[str], datetime, datetime]:
    started = datetime.now(timezone.utc)
    try:
        result = subprocess.run(
            [str(executable), *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolTimeoutError(
            f"FFprobe exceeded the {timeout_seconds}-second timeout"
        ) from exc
    return result, started, datetime.now(timezone.utc)


def inspect_tool(executable: Path, timeout_seconds: int) -> ExternalToolIdentity:
    result, _, _ = _run(executable, ("-version",), timeout_seconds)
    if result.returncode != 0:
        raise ToolUnavailableError(
            f"FFprobe version inspection failed with exit code {result.returncode}"
        )
    lines = result.stdout.splitlines()
    if not lines or not lines[0].startswith("ffprobe version "):
        raise MalformedInspectionOutput("FFprobe returned an unrecognized version")
    configuration = next(
        (
            line.removeprefix("configuration: ").strip()
            for line in lines
            if line.startswith("configuration: ")
        ),
        None,
    )
    return ExternalToolIdentity(
        executable=str(executable),
        executable_sha256=sha256_file(executable),
        version_line=lines[0].strip(),
        build_configuration=configuration,
    )


def _integer(value: Any) -> int | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _microseconds(value: Any) -> int | None:
    if value in (None, "", "N/A"):
        return None
    try:
        result = (Decimal(str(value)) * Decimal(1_000_000)).quantize(
            Decimal(1), rounding=ROUND_HALF_EVEN
        )
        return int(result)
    except (InvalidOperation, TypeError, ValueError):
        return None


def _pairs(value: Any) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, Mapping):
        return ()
    return tuple(sorted((str(key), str(item)) for key, item in value.items()))


def _disposition(raw: Any) -> StreamDisposition:
    data = raw if isinstance(raw, Mapping) else {}
    return StreamDisposition(
        default=bool(data.get("default", 0)),
        forced=bool(data.get("forced", 0)),
        attached_picture=bool(data.get("attached_pic", 0)),
        hearing_impaired=bool(data.get("hearing_impaired", 0)),
        visual_impaired=bool(data.get("visual_impaired", 0)),
        original=bool(data.get("original", 0)),
        commentary=bool(data.get("comment", 0)),
    )


def _rotation(raw: Mapping[str, Any]) -> int | None:
    tags = raw.get("tags")
    if isinstance(tags, Mapping) and "rotate" in tags:
        return _integer(tags["rotate"])
    for side_data in raw.get("side_data_list", ()):
        if isinstance(side_data, Mapping) and "rotation" in side_data:
            return _integer(side_data["rotation"])
    return None


def _stream_kind(codec_type: Any, disposition: StreamDisposition) -> StreamKind:
    if disposition.attached_picture:
        return StreamKind.ATTACHMENT
    try:
        return StreamKind(str(codec_type))
    except ValueError:
        return StreamKind.UNKNOWN


def _base_stream(
    raw: Mapping[str, Any], source_digest: str
) -> tuple[dict[str, Any], StreamKind]:
    index = _integer(raw.get("index"))
    if index is None or index < 0:
        raise MalformedInspectionOutput("stream has no valid non-negative index")
    disposition = _disposition(raw.get("disposition"))
    kind = _stream_kind(raw.get("codec_type"), disposition)
    stream_digest = hashlib.sha256(
        f"{source_digest}:{index}:{kind.value}".encode("utf-8")
    ).hexdigest()[:32]
    tags = raw.get("tags") if isinstance(raw.get("tags"), Mapping) else {}
    base = {
        "stream_id": f"stream_{stream_digest}",
        "stream_index": index,
        "stream_type": kind,
        "codec_name": raw.get("codec_name"),
        "codec_long_name": raw.get("codec_long_name"),
        "profile": raw.get("profile"),
        "level": _integer(raw.get("level")),
        "codec_tag": raw.get("codec_tag_string"),
        "time_base": raw.get("time_base"),
        "start_timestamp": _integer(raw.get("start_pts")),
        "start_time_microseconds": _microseconds(raw.get("start_time")),
        "duration_timestamp": _integer(raw.get("duration_ts")),
        "duration_microseconds": _microseconds(raw.get("duration")),
        "bit_rate": _integer(raw.get("bit_rate")),
        "disposition": disposition,
        "language": tags.get("language"),
        "tags": _pairs(tags),
    }
    return base, kind


def parse_stream(
    raw: Mapping[str, Any], source_digest: str
) -> MediaStreamDescriptor:
    base, kind = _base_stream(raw, source_digest)
    if kind == StreamKind.VIDEO:
        return VideoStreamDescriptor(
            **base,
            width=_integer(raw.get("width")),
            height=_integer(raw.get("height")),
            pixel_format=raw.get("pix_fmt"),
            sample_aspect_ratio=raw.get("sample_aspect_ratio"),
            display_aspect_ratio=raw.get("display_aspect_ratio"),
            average_frame_rate=raw.get("avg_frame_rate"),
            real_frame_rate=raw.get("r_frame_rate"),
            color_range=raw.get("color_range"),
            color_space=raw.get("color_space"),
            color_transfer=raw.get("color_transfer"),
            color_primaries=raw.get("color_primaries"),
            rotation_degrees=_rotation(raw),
            frame_count=_integer(raw.get("nb_frames")),
        )
    if kind == StreamKind.AUDIO:
        return AudioStreamDescriptor(
            **base,
            sample_format=raw.get("sample_fmt"),
            sample_rate=_integer(raw.get("sample_rate")),
            channels=_integer(raw.get("channels")),
            channel_layout=raw.get("channel_layout"),
            bits_per_sample=(
                _integer(raw.get("bits_per_raw_sample"))
                or _integer(raw.get("bits_per_sample"))
            ),
        )
    if kind == StreamKind.SUBTITLE:
        return SubtitleStreamDescriptor(**base)
    return MediaStreamDescriptor(**base)


def parse_ffprobe_result(
    request: MediaInspectionRequest,
    raw_json: str,
    invocation: ToolInvocationRecord,
    tool: ExternalToolIdentity,
) -> MediaInspectionResult:
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise MalformedInspectionOutput("FFprobe did not return valid JSON") from exc
    if not isinstance(parsed, dict):
        raise MalformedInspectionOutput("FFprobe JSON root must be an object")
    raw_streams = parsed.get("streams", [])
    if not isinstance(raw_streams, list):
        raise MalformedInspectionOutput("FFprobe streams must be an array")
    streams = tuple(
        parse_stream(stream, request.source_fingerprint.digest)
        for stream in raw_streams
        if isinstance(stream, Mapping)
    )
    raw_format = parsed.get("format")
    format_data = raw_format if isinstance(raw_format, Mapping) else {}
    format_names = tuple(
        item for item in str(format_data.get("format_name", "")).split(",") if item
    )
    support = (
        MediaSupportStatus.SUPPORTED
        if Path(request.source).suffix.lower() in QUALIFIED_EXTENSIONS
        else MediaSupportStatus.DECODABLE_UNQUALIFIED
    )
    warnings = tuple(
        line.strip() for line in invocation.standard_error.splitlines() if line.strip()
    )
    source_id = typed_id("src", request.source_fingerprint.digest)
    return MediaInspectionResult(
        source_id=source_id,
        source=request.source,
        source_fingerprint=request.source_fingerprint,
        support_status=support,
        container=ContainerDescriptor(
            format_names=format_names,
            format_long_name=format_data.get("format_long_name"),
            duration_microseconds=_microseconds(format_data.get("duration")),
            start_time_microseconds=_microseconds(format_data.get("start_time")),
            bit_rate=_integer(format_data.get("bit_rate")),
            file_size=request.source_fingerprint.byte_size,
            tags=_pairs(format_data.get("tags")),
            chapter_count=len(parsed.get("chapters", ())),
            program_count=len(parsed.get("programs", ())),
        ),
        streams=streams,
        warnings=warnings,
        raw_attachment=RawInspectionAttachment(
            raw_json=raw_json,
            raw_json_sha256=hashlib.sha256(raw_json.encode("utf-8")).hexdigest(),
            invocation=invocation,
            tool=tool,
        ),
    )


def inspect_media(
    source: Path, ffprobe: str | None = None, timeout_seconds: int = 60
) -> MediaInspectionResult:
    source = source.expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    if not source.is_file():
        raise ValueError(f"source is not a regular file: {source}")
    if source.stat().st_size == 0:
        raise ValueError(f"source is empty: {source}")
    fingerprint = fingerprint_file(source)
    executable = discover_executable(ffprobe)
    request = MediaInspectionRequest(
        source=str(source),
        source_fingerprint=fingerprint,
        ffprobe_executable=str(executable),
        timeout_seconds=timeout_seconds,
    )
    tool = inspect_tool(executable, timeout_seconds)
    arguments = (
        "-hide_banner", "-v", "warning", "-print_format", "json",
        "-show_format", "-show_streams", "-show_chapters", "-show_programs",
        str(source),
    )
    result, started, completed = _run(executable, arguments, timeout_seconds)
    invocation = ToolInvocationRecord(
        executable=str(executable),
        arguments=arguments,
        started_at=started,
        completed_at=completed,
        exit_code=result.returncode,
        standard_error=result.stderr,
    )
    if result.returncode != 0:
        raise MediaInspectionError(
            f"FFprobe failed with exit code {result.returncode}: "
            f"{result.stderr.strip() or 'no diagnostic'}"
        )
    return parse_ffprobe_result(request, result.stdout, invocation, tool)
