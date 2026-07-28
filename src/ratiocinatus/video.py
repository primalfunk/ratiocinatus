"""Passthrough, timestamp-authoritative video access."""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from fractions import Fraction
from pathlib import Path

from .addressing import build_source_timeline, map_timestamp
from .addressing_contracts import (
    MappingClassification,
    MediaInterval,
    MediaTimestamp,
    TimeDomain,
)
from .kernel import typed_id
from .media import discover_executable, fingerprint_file, inspect_media, sha256_file
from .phase1_contracts import (
    MediaInspectionResult,
    ToolInvocationRecord,
    VideoStreamDescriptor,
)
from .qualification import discover_ffmpeg
from .qualification_contracts import DecodeQualificationResult, QualificationStatus
from .selection_contracts import StreamSelectionResult
from .video_contracts import (
    FrameAccessRequest,
    FrameAccessResult,
    FrameTimestampIndex,
    VideoAccessPlan,
    VideoAccessStatus,
    VideoNormalizationPolicy,
)


class VideoAccessError(RuntimeError):
    pass


def _microseconds(value: str) -> int:
    try:
        return int(
            (Decimal(value) * Decimal(1_000_000)).quantize(
                Decimal(1), rounding=ROUND_HALF_EVEN
            )
        )
    except (InvalidOperation, ValueError) as exc:
        raise VideoAccessError(f"invalid frame timestamp: {value}") from exc


def _seconds(value: int) -> str:
    whole, fraction = divmod(value, 1_000_000)
    return f"{whole}.{fraction:06d}"


def _valid_time_base(value: str | None) -> bool:
    if not value:
        return False
    try:
        return Fraction(value) > 0
    except (ValueError, ZeroDivisionError):
        return False


def create_video_access_plan(
    inspection: MediaInspectionResult,
    selection: StreamSelectionResult,
    qualification: DecodeQualificationResult | None = None,
    policy: VideoNormalizationPolicy | None = None,
) -> VideoAccessPlan:
    policy = policy or VideoNormalizationPolicy()
    if not selection.valid:
        raise ValueError("cannot create video access from invalid selection")
    timeline = build_source_timeline(inspection, selection)
    stream_id = selection.video.selected_stream_id
    if stream_id is None:
        return VideoAccessPlan(
            plan_id=typed_id(
                "videoaccess", inspection.source_id, "audio-only", policy.model_dump(mode="json")
            ),
            source_id=inspection.source_id,
            source=inspection.source,
            source_fingerprint=inspection.source_fingerprint,
            policy=policy,
            status=VideoAccessStatus.NOT_APPLICABLE,
            timeline=timeline,
            seek_qualified=True,
            explanation="No video stream selected; audio-only ingestion is valid.",
        )
    stream = next(
        (item for item in inspection.streams if item.stream_id == stream_id), None
    )
    if not isinstance(stream, VideoStreamDescriptor):
        raise ValueError("selected video stream does not resolve to video metadata")
    seek_qualified = False
    video_probe_failed = False
    if qualification is not None:
        video_probes = [
            probe
            for probe in qualification.probes
            if probe.stream_id == stream_id and probe.label in {"early", "middle", "late"}
        ]
        seek_qualified = len(video_probes) == 3 and all(
            probe.status in {QualificationStatus.SUCCESS, QualificationStatus.WARNING}
            for probe in video_probes
        )
        video_probe_failed = any(
            probe.status == QualificationStatus.FAILURE
            for probe in video_probes
        )
    findings: list[str] = []
    if not _valid_time_base(stream.time_base):
        findings.append("unsupported or missing video time base")
    if (
        stream.pixel_format is None
        or stream.pixel_format not in policy.supported_pixel_formats
    ):
        findings.append(
            f"unsupported pixel format: {stream.pixel_format or 'missing'}"
        )
    if video_probe_failed:
        findings.append("video decode or timestamp qualification failed")
    status = (
        VideoAccessStatus.REFUSED
        if findings
        else (
            VideoAccessStatus.AVAILABLE
            if seek_qualified
            else VideoAccessStatus.UNQUALIFIED
        )
    )
    return VideoAccessPlan(
        plan_id=typed_id(
            "videoaccess",
            inspection.source_id,
            stream.stream_id,
            policy.model_dump(mode="json"),
        ),
        source_id=inspection.source_id,
        source=inspection.source,
        source_fingerprint=inspection.source_fingerprint,
        policy=policy,
        status=status,
        video_stream_id=stream.stream_id,
        video_stream_index=stream.stream_index,
        timeline=timeline,
        time_base=stream.time_base,
        average_frame_rate=stream.average_frame_rate,
        real_frame_rate=stream.real_frame_rate,
        variable_frame_rate=timeline.variable_frame_rate,
        width=stream.width,
        height=stream.height,
        pixel_format=stream.pixel_format,
        sample_aspect_ratio=stream.sample_aspect_ratio,
        display_aspect_ratio=stream.display_aspect_ratio,
        rotation_degrees=stream.rotation_degrees,
        transformations=(),
        policy_findings=tuple(findings),
        seek_qualified=seek_qualified,
        explanation=(
            "Source passthrough refused: " + "; ".join(findings)
            if findings
            else (
                "Qualified source passthrough; frames are addressed by timestamp. "
                "Encoded pixels, rotation metadata, aspect ratio, dimensions, and "
                "speed remain unchanged."
            )
        ),
    )


def _run(
    executable: Path, arguments: tuple[str, ...], timeout: int
) -> tuple[subprocess.CompletedProcess[str], ToolInvocationRecord]:
    started = datetime.now(timezone.utc)
    try:
        result = subprocess.run(
            [str(executable), *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise VideoAccessError(f"video access timed out after {timeout} seconds") from exc
    completed = datetime.now(timezone.utc)
    return result, ToolInvocationRecord(
        executable=str(executable),
        arguments=arguments,
        started_at=started,
        completed_at=completed,
        exit_code=result.returncode,
        standard_output=result.stdout,
        standard_error=result.stderr,
    )


def _frame_times(
    plan: VideoAccessPlan,
    start_source_microseconds: int,
    duration_microseconds: int,
    ffprobe: str | None,
) -> tuple[tuple[int, ...], ToolInvocationRecord]:
    executable = discover_executable(ffprobe)
    end_source_microseconds = start_source_microseconds + duration_microseconds
    probe_end_microseconds = (
        end_source_microseconds + plan.policy.frame_search_radius_microseconds
    )
    interval = (
        f"{_seconds(start_source_microseconds)}%"
        f"{_seconds(probe_end_microseconds)}"
    )
    arguments = (
        "-hide_banner", "-v", "error",
        "-select_streams", str(plan.video_stream_index),
        "-read_intervals", interval,
        "-show_entries", "frame=best_effort_timestamp_time",
        "-of", "json",
        plan.source,
    )
    result, invocation = _run(executable, arguments, plan.policy.timeout_seconds)
    if result.returncode != 0:
        raise VideoAccessError(
            f"FFprobe frame lookup failed with exit code {result.returncode}: "
            f"{result.stderr.strip()}"
        )
    try:
        payload = json.loads(result.stdout)
        parsed_times = (
            _microseconds(item["best_effort_timestamp_time"])
            for item in payload.get("frames", ())
            if "best_effort_timestamp_time" in item
        )
        times = tuple(
            value
            for value in parsed_times
            if start_source_microseconds
            <= value
            < end_source_microseconds
        )
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        raise VideoAccessError("FFprobe returned malformed frame timestamps") from exc
    return times, invocation


def frames_over_interval(
    plan: VideoAccessPlan,
    interval: MediaInterval,
    *,
    ffprobe: str | None = None,
    max_frames: int = 100_000,
) -> FrameTimestampIndex:
    if plan.status != VideoAccessStatus.AVAILABLE:
        raise VideoAccessError("video access plan is not qualified and available")
    if interval.domain != TimeDomain.NORMALIZED_CORPUS:
        raise ValueError("frame interval must use normalized corpus time")
    if max_frames <= 0:
        raise ValueError("max_frames must be positive")
    start = map_timestamp(
        plan.timeline,
        MediaTimestamp(
            domain=TimeDomain.NORMALIZED_CORPUS,
            microseconds=interval.start_microseconds,
        ),
    )
    if start.mapped is None:
        raise VideoAccessError("frame interval begins outside the source timeline")
    times, invocation = _frame_times(
        plan,
        start.mapped.microseconds,
        interval.duration_microseconds,
        ffprobe,
    )
    truncated = len(times) > max_frames
    selected = times[:max_frames]
    corpus_times = tuple(
        MediaTimestamp(
            domain=TimeDomain.NORMALIZED_CORPUS,
            microseconds=value - plan.timeline.mapping_offset_microseconds,
        )
        for value in selected
        if 0
        <= value - plan.timeline.mapping_offset_microseconds
        <= plan.timeline.corpus_duration_microseconds
    )
    return FrameTimestampIndex(
        plan_id=plan.plan_id,
        requested_interval=interval,
        corpus_timestamps=corpus_times,
        truncated=truncated,
        invocation=invocation,
    )


def extract_frame(
    plan: VideoAccessPlan,
    corpus_timestamp_microseconds: int,
    output: Path,
    *,
    ffmpeg: str | None = None,
    ffprobe: str | None = None,
) -> FrameAccessResult:
    if plan.status != VideoAccessStatus.AVAILABLE:
        raise VideoAccessError("video access plan is not qualified and available")
    source = Path(plan.source).resolve(strict=True)
    if fingerprint_file(source) != plan.source_fingerprint:
        raise VideoAccessError("source fingerprint no longer matches video plan")
    requested = MediaTimestamp(
        domain=TimeDomain.NORMALIZED_CORPUS,
        microseconds=corpus_timestamp_microseconds,
    )
    mapped = map_timestamp(plan.timeline, requested)
    if mapped.mapped is None:
        raise VideoAccessError("requested frame timestamp is outside the corpus")
    radius = plan.policy.frame_search_radius_microseconds
    source_lower = plan.timeline.source_start_microseconds
    lookup_start = max(mapped.mapped.microseconds - radius, source_lower)
    lookup_duration = radius * 2
    times, locator_invocation = _frame_times(
        plan, lookup_start, lookup_duration, ffprobe
    )
    if not times:
        raise VideoAccessError("no video frame found near requested timestamp")
    actual_source = min(times, key=lambda value: abs(value - mapped.mapped.microseconds))
    actual_corpus = actual_source - plan.timeline.mapping_offset_microseconds
    error = abs(actual_corpus - corpus_timestamp_microseconds)
    output = output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"frame output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(
        f"{output.stem}.partial-{uuid.uuid4().hex}.png"
    )
    executable = discover_ffmpeg(ffmpeg)
    arguments = (
        "-hide_banner", "-nostdin", "-v", "error", "-noautorotate",
        "-ss", _seconds(actual_source), "-i", str(source),
        "-map", f"0:{plan.video_stream_index}", "-frames:v", "1",
        "-fps_mode", "passthrough", "-c:v", "png", "-n", str(partial),
    )
    result, extraction_invocation = _run(
        executable, arguments, plan.policy.timeout_seconds
    )
    if result.returncode != 0 or not partial.is_file():
        raise VideoAccessError(
            f"FFmpeg frame extraction failed with exit code {result.returncode}: "
            f"{result.stderr.strip()}"
        )
    image_inspection = inspect_media(partial, ffprobe=ffprobe)
    video = next(
        (
            stream
            for stream in image_inspection.streams
            if isinstance(stream, VideoStreamDescriptor)
        ),
        None,
    )
    if video is None or video.width is None or video.height is None:
        raise VideoAccessError("extracted frame did not validate as an image")
    digest = sha256_file(partial)
    size = partial.stat().st_size
    os.replace(partial, output)
    if fingerprint_file(source) != plan.source_fingerprint:
        raise VideoAccessError("source changed during frame extraction")
    return FrameAccessResult(
        request=FrameAccessRequest(
            plan_id=plan.plan_id,
            corpus_timestamp=requested,
            output=str(output),
        ),
        source_timestamp=MediaTimestamp(
            domain=TimeDomain.SOURCE_MEDIA,
            microseconds=actual_source,
        ),
        located_corpus_timestamp=MediaTimestamp(
            domain=TimeDomain.NORMALIZED_CORPUS,
            microseconds=actual_corpus,
        ),
        classification=(
            MappingClassification.EXACT
            if error == 0
            else MappingClassification.ROUNDED
        ),
        timestamp_error_microseconds=error,
        output=str(output),
        content_sha256=digest,
        byte_size=size,
        width=video.width,
        height=video.height,
        rotation_degrees=plan.rotation_degrees,
        display_transform_required=bool(plan.rotation_degrees),
        locator_invocation=locator_invocation,
        extraction_invocation=extraction_invocation,
    )
