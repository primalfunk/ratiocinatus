"""Bounded FFprobe packet-timestamp continuity qualification."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from pathlib import Path
from statistics import median
from typing import Any

from .addressing_contracts import MediaInterval, SourceTimeline, TimeDomain
from .media import discover_executable, fingerprint_file, inspect_tool
from .packet_contracts import (
    PacketContinuityPolicy,
    PacketContinuityProbe,
    PacketContinuityResult,
    PacketContinuityStatus,
)
from .phase1_contracts import MediaInspectionResult, StreamKind, ToolInvocationRecord
from .qualification import probe_positions
from .selection_contracts import StreamSelectionResult


class PacketContinuityError(RuntimeError):
    pass


def _microseconds(value: str | None) -> int | None:
    if value in {None, "N/A"}:
        return None
    try:
        return int(
            (Decimal(value) * Decimal(1_000_000)).quantize(
                Decimal(1), rounding=ROUND_HALF_EVEN
            )
        )
    except (InvalidOperation, ValueError) as exc:
        raise PacketContinuityError(
            f"invalid packet timestamp value: {value}"
        ) from exc


def _seconds(microseconds: int) -> str:
    whole, fraction = divmod(microseconds, 1_000_000)
    return f"{whole}.{fraction:06d}"


def _selected_streams(
    inspection: MediaInspectionResult,
    selection: StreamSelectionResult,
) -> tuple[tuple[str, int, StreamKind], ...]:
    selected = {
        value
        for value in (
            selection.audio.selected_stream_id,
            selection.video.selected_stream_id,
        )
        if value is not None
    }
    return tuple(
        (stream.stream_id, stream.stream_index, stream.stream_type)
        for stream in inspection.streams
        if stream.stream_id in selected
    )


def analyze_packet_payload(
    packets: list[dict[str, Any]],
    *,
    policy: PacketContinuityPolicy,
) -> dict[str, Any]:
    pts = [_microseconds(packet.get("pts_time")) for packet in packets]
    dts = [_microseconds(packet.get("dts_time")) for packet in packets]
    durations = [
        value
        for value in (
            _microseconds(packet.get("duration_time"))
            for packet in packets
        )
        if value is not None and value > 0
    ]
    present_dts = [value for value in dts if value is not None]
    gaps = [
        right - left
        for left, right in zip(present_dts, present_dts[1:])
        if right >= left
    ]
    regressions = [
        (left, right)
        for left, right in zip(present_dts, present_dts[1:])
        if right < left
    ]
    typical_duration = int(median(durations)) if durations else 0
    threshold = max(
        policy.absolute_gap_warning_microseconds,
        typical_duration * policy.duration_gap_multiplier,
    )
    large_gaps = [
        (left, right)
        for left, right in zip(present_dts, present_dts[1:])
        if right - left > threshold
    ]
    return {
        "missing_pts_count": sum(value is None for value in pts),
        "missing_dts_count": sum(value is None for value in dts),
        "dts_regression_count": len(regressions),
        "maximum_dts_gap_microseconds": max(gaps) if gaps else None,
        "regressions": regressions,
        "large_gaps": large_gaps,
    }


def _probe(
    executable: Path,
    source: Path,
    *,
    label: str,
    start_microseconds: int,
    duration_microseconds: int,
    stream_id: str,
    stream_index: int,
    stream_type: StreamKind,
    policy: PacketContinuityPolicy,
) -> PacketContinuityProbe:
    interval = (
        f"{_seconds(start_microseconds)}%"
        f"+{_seconds(duration_microseconds)}"
    )
    arguments = (
        "-hide_banner",
        "-v",
        "error",
        "-select_streams",
        str(stream_index),
        "-read_intervals",
        interval,
        "-show_entries",
        "packet=pts_time,dts_time,duration_time",
        "-of",
        "json",
        str(source),
    )
    started = datetime.now(timezone.utc)
    timed_out = False
    try:
        completed = subprocess.run(
            [str(executable), *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=policy.timeout_seconds,
            check=False,
            shell=False,
        )
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = -1
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
    finished = datetime.now(timezone.utc)
    invocation = ToolInvocationRecord(
        executable=str(executable),
        arguments=arguments,
        started_at=started,
        completed_at=finished,
        exit_code=exit_code,
        standard_output=stdout,
        standard_error=stderr,
        timed_out=timed_out,
    )
    findings: list[str] = []
    packets: list[dict[str, Any]] = []
    if timed_out:
        findings.append("packet probe timed out")
    elif exit_code != 0:
        findings.append(f"FFprobe exited with code {exit_code}")
    else:
        try:
            payload = json.loads(stdout)
            packets = payload.get("packets", [])
            if not isinstance(packets, list) or not all(
                isinstance(packet, dict) for packet in packets
            ):
                raise TypeError("packets is not an object array")
        except (json.JSONDecodeError, TypeError) as exc:
            findings.append(f"malformed packet output: {exc}")
            packets = []
    truncated = len(packets) > policy.maximum_packets_per_probe
    packets = packets[: policy.maximum_packets_per_probe]
    analysis = analyze_packet_payload(packets, policy=policy)
    if not packets:
        findings.append("probe produced no packets")
    if analysis["missing_dts_count"]:
        findings.append("one or more packets omit DTS")
    if analysis["dts_regression_count"]:
        findings.append("packet DTS regressed")
    if analysis["large_gaps"]:
        findings.append("packet DTS gap exceeds policy threshold")
    if truncated:
        findings.append("packet probe reached its configured packet bound")
    discontinuities = tuple(
        MediaInterval(
            domain=TimeDomain.SOURCE_MEDIA,
            start_microseconds=min(left, right),
            duration_microseconds=max(abs(right - left), 1),
        )
        for left, right in (
            *analysis["regressions"],
            *analysis["large_gaps"],
        )
    )
    failure = bool(
        timed_out
        or exit_code != 0
        or not packets
        or analysis["missing_dts_count"] == len(packets)
        or analysis["dts_regression_count"]
    )
    warning = bool(findings)
    status = (
        PacketContinuityStatus.FAILURE
        if failure
        else (
            PacketContinuityStatus.WARNING
            if warning
            else PacketContinuityStatus.SUCCESS
        )
    )
    return PacketContinuityProbe(
        label=label,
        stream_id=stream_id,
        stream_index=stream_index,
        stream_type=stream_type,
        requested_interval=MediaInterval(
            domain=TimeDomain.SOURCE_MEDIA,
            start_microseconds=start_microseconds,
            duration_microseconds=duration_microseconds,
        ),
        packet_count=len(packets),
        truncated=truncated,
        missing_pts_count=analysis["missing_pts_count"],
        missing_dts_count=analysis["missing_dts_count"],
        dts_regression_count=analysis["dts_regression_count"],
        maximum_dts_gap_microseconds=analysis[
            "maximum_dts_gap_microseconds"
        ],
        discontinuities=discontinuities,
        status=status,
        invocation=invocation,
        findings=tuple(findings),
    )


def qualify_packet_continuity(
    inspection: MediaInspectionResult,
    selection: StreamSelectionResult,
    *,
    policy: PacketContinuityPolicy | None = None,
    ffprobe: str | None = None,
) -> PacketContinuityResult:
    if not selection.valid:
        raise ValueError("cannot qualify packets for an invalid selection")
    policy = policy or PacketContinuityPolicy()
    source = Path(inspection.source).resolve(strict=True)
    before = fingerprint_file(source)
    if before != inspection.source_fingerprint:
        raise ValueError("source fingerprint no longer matches inspection")
    executable = discover_executable(ffprobe)
    tool = inspect_tool(executable, policy.timeout_seconds)
    duration = inspection.container.duration_microseconds
    if duration is None or duration <= 0:
        raise PacketContinuityError("source duration is unavailable")
    probes = tuple(
        _probe(
            executable,
            source,
            label=label,
            start_microseconds=start,
            duration_microseconds=min(
                policy.probe_duration_microseconds,
                duration - start,
            ),
            stream_id=stream_id,
            stream_index=stream_index,
            stream_type=stream_type,
            policy=policy,
        )
        for stream_id, stream_index, stream_type in _selected_streams(
            inspection, selection
        )
        for label, start in probe_positions(
            duration, policy.probe_duration_microseconds
        )
    )
    if fingerprint_file(source) != before:
        raise ValueError("source changed during packet qualification")
    discontinuities = tuple(
        interval
        for probe in probes
        for interval in probe.discontinuities
    )
    return PacketContinuityResult(
        source_id=inspection.source_id,
        policy=policy,
        tool=tool,
        probes=probes,
        discontinuities=discontinuities,
        valid=bool(probes)
        and all(
            probe.status != PacketContinuityStatus.FAILURE
            for probe in probes
        ),
    )


def apply_packet_discontinuities(
    timeline: SourceTimeline,
    result: PacketContinuityResult,
) -> SourceTimeline:
    if timeline.source_id != result.source_id:
        raise ValueError("packet result belongs to a different source")
    return timeline.model_copy(
        update={
            "discontinuities": tuple(
                sorted(
                    {*timeline.discontinuities, *result.discontinuities},
                    key=lambda interval: (
                        interval.start_microseconds,
                        interval.duration_microseconds,
                    ),
                )
            )
        }
    )
