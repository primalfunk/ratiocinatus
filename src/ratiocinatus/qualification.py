"""Bounded representative decode qualification through FFmpeg."""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .media import ToolUnavailableError, fingerprint_file, sha256_file
from .phase1_contracts import (
    ExternalToolIdentity,
    MediaInspectionResult,
    StreamKind,
    ToolInvocationRecord,
)
from .qualification_contracts import (
    DecodeQualificationPolicy,
    DecodeQualificationProbe,
    DecodeQualificationResult,
    QualificationStatus,
)
from .selection_contracts import StreamSelectionResult


def discover_ffmpeg(explicit: str | None = None) -> Path:
    candidate = explicit or shutil.which("ffmpeg")
    if not candidate:
        raise ToolUnavailableError(
            "FFmpeg was not found; install FFmpeg or provide --ffmpeg"
        )
    path = Path(candidate).expanduser().resolve()
    if not path.is_file():
        raise ToolUnavailableError(f"FFmpeg executable does not exist: {path}")
    return path


def _version(executable: Path, timeout_seconds: int) -> ExternalToolIdentity:
    try:
        result = subprocess.run(
            [str(executable), "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolUnavailableError("FFmpeg version inspection timed out") from exc
    lines = result.stdout.splitlines()
    if result.returncode != 0 or not lines or not lines[0].startswith("ffmpeg version "):
        raise ToolUnavailableError("FFmpeg version inspection failed")
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
        product="ffmpeg",
        version_line=lines[0].strip(),
        build_configuration=configuration,
    )


def _seconds(microseconds: int) -> str:
    whole, fraction = divmod(microseconds, 1_000_000)
    return f"{whole}.{fraction:06d}"


def probe_positions(
    duration_microseconds: int, probe_duration_microseconds: int
) -> tuple[tuple[str, int], ...]:
    available_start = max(duration_microseconds - probe_duration_microseconds, 0)
    return (
        ("early", 0),
        ("middle", available_start // 2),
        ("late", available_start),
    )


def _selected_streams(
    inspection: MediaInspectionResult, selection: StreamSelectionResult
) -> tuple[tuple[str, int, StreamKind], ...]:
    selected_ids = {
        item
        for item in (
            selection.audio.selected_stream_id,
            selection.video.selected_stream_id,
        )
        if item is not None
    }
    return tuple(
        (stream.stream_id, stream.stream_index, stream.stream_type)
        for stream in inspection.streams
        if stream.stream_id in selected_ids
    )


def _decoded_output_observed(stdout: str, stream_type: StreamKind) -> bool:
    progress: dict[str, list[str]] = {}
    for line in stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            progress.setdefault(key, []).append(value)
    if stream_type == StreamKind.VIDEO:
        return any(
            value.isdigit() and int(value) > 0
            for value in progress.get("frame", ())
        )
    return any(
        value not in {"N/A", ""} and value.lstrip("-").isdigit() and int(value) > 0
        for value in progress.get("out_time_us", ())
    )


def _probe(
    executable: Path,
    source: Path,
    stream_id: str,
    stream_index: int,
    stream_type: StreamKind,
    label: str,
    start_microseconds: int,
    duration_microseconds: int,
    timeout_seconds: int,
    full: bool = False,
) -> DecodeQualificationProbe:
    arguments = ["-hide_banner", "-nostdin", "-v", "error"]
    if not full:
        arguments.extend(("-ss", _seconds(start_microseconds)))
    arguments.extend(("-i", str(source), "-map", f"0:{stream_index}"))
    if not full:
        arguments.extend(("-t", _seconds(duration_microseconds)))
    arguments.extend(("-progress", "pipe:1", "-nostats", "-f", "null", "-"))
    started = datetime.now(timezone.utc)
    timed_out = False
    try:
        completed = subprocess.run(
            [str(executable), *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
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
    decoded = (
        not timed_out
        and exit_code == 0
        and _decoded_output_observed(stdout, stream_type)
    )
    status = (
        QualificationStatus.FAILURE
        if exit_code != 0 or timed_out or not decoded
        else (
            QualificationStatus.WARNING
            if stderr.strip()
            else QualificationStatus.SUCCESS
        )
    )
    message = (
        f"FFmpeg timed out after {timeout_seconds} seconds"
        if timed_out
        else (
            f"FFmpeg exited with code {exit_code}"
            if exit_code != 0
            else (
                "FFmpeg produced no decoded output"
                if not decoded
                else (stderr.strip() or None)
            )
        )
    )
    return DecodeQualificationProbe(
        label="full" if full else label,
        stream_id=stream_id,
        stream_index=stream_index,
        stream_type=stream_type,
        requested_start_microseconds=start_microseconds,
        requested_duration_microseconds=duration_microseconds,
        status=status,
        invocation=ToolInvocationRecord(
            executable=str(executable),
            arguments=tuple(arguments),
            started_at=started,
            completed_at=finished,
            exit_code=exit_code,
            standard_output=stdout,
            standard_error=stderr,
            timed_out=timed_out,
        ),
        message=message,
    )


def _aggregate(
    probes: tuple[DecodeQualificationProbe, ...]
) -> QualificationStatus:
    if not probes:
        return QualificationStatus.NOT_PERFORMED
    if any(item.status == QualificationStatus.FAILURE for item in probes):
        return QualificationStatus.FAILURE
    if any(item.status == QualificationStatus.WARNING for item in probes):
        return QualificationStatus.WARNING
    return QualificationStatus.SUCCESS


def _duration_status(
    inspection: MediaInspectionResult,
    selected: tuple[tuple[str, int, StreamKind], ...],
) -> tuple[QualificationStatus, str | None]:
    duration = inspection.container.duration_microseconds
    if duration is None or duration <= 0:
        return QualificationStatus.FAILURE, "container duration is missing or invalid"
    tolerance = max(2_000_000, duration // 100)
    by_id = {stream.stream_id: stream for stream in inspection.streams}
    compared = 0
    for stream_id, _, _ in selected:
        stream_duration = by_id[stream_id].duration_microseconds
        if stream_duration is None:
            continue
        compared += 1
        if abs(stream_duration - duration) > tolerance:
            return (
                QualificationStatus.FAILURE,
                f"stream {stream_id} duration differs from container by more "
                f"than {tolerance} microseconds",
            )
    if compared != len(selected):
        return QualificationStatus.WARNING, "some selected streams omit duration"
    return QualificationStatus.SUCCESS, None


class FFmpegDecodeQualificationProvider:
    """Provider boundary for source-open and representative decode checks."""

    def __init__(self, executable: str | None = None) -> None:
        self.executable = discover_ffmpeg(executable)

    def qualify(
        self,
        inspection: MediaInspectionResult,
        selection: StreamSelectionResult,
        policy: DecodeQualificationPolicy | None = None,
    ) -> DecodeQualificationResult:
        policy = policy or DecodeQualificationPolicy()
        if not selection.valid:
            raise ValueError("cannot qualify an invalid stream selection")
        source = Path(inspection.source).resolve(strict=True)
        before = fingerprint_file(source)
        if before != inspection.source_fingerprint:
            raise ValueError("source fingerprint no longer matches inspection")
        tool = _version(self.executable, policy.timeout_seconds)
        duration = inspection.container.duration_microseconds
        if duration is None or duration <= 0:
            positions = (("early", 0),)
        else:
            positions = probe_positions(
                duration, policy.probe_duration_microseconds
            )
        selected = _selected_streams(inspection, selection)
        sampled: list[DecodeQualificationProbe] = []
        for stream_id, stream_index, stream_type in selected:
            for label, start in positions:
                sampled.append(
                    _probe(
                        self.executable,
                        source,
                        stream_id,
                        stream_index,
                        stream_type,
                        label,
                        start,
                        policy.probe_duration_microseconds,
                        policy.timeout_seconds,
                    )
                )
        full_probes: list[DecodeQualificationProbe] = []
        if policy.full_decode:
            for stream_id, stream_index, stream_type in selected:
                full_probes.append(
                    _probe(
                        self.executable,
                        source,
                        stream_id,
                        stream_index,
                        stream_type,
                        "full",
                        0,
                        max(duration or 1, 1),
                        policy.timeout_seconds,
                        full=True,
                    )
                )
        probes = tuple((*sampled, *full_probes))
        early = tuple(item for item in sampled if item.label == "early")
        sampled_status = _aggregate(tuple(sampled))
        full_status = (
            _aggregate(tuple(full_probes))
            if policy.full_decode
            else QualificationStatus.NOT_PERFORMED
        )
        duration_status, duration_warning = _duration_status(inspection, selected)
        warnings = [
            item.message
            for item in probes
            if item.status == QualificationStatus.WARNING and item.message
        ]
        if duration_warning:
            warnings.append(duration_warning)
        after = fingerprint_file(source)
        if after != before:
            raise ValueError("source changed during decode qualification")
        required = (
            _aggregate(early),
            sampled_status,
            duration_status,
        )
        valid = all(
            item in {QualificationStatus.SUCCESS, QualificationStatus.WARNING}
            for item in required
        )
        return DecodeQualificationResult(
            source_id=inspection.source_id,
            policy=policy,
            selection=selection,
            tool=tool,
            inspection_status=QualificationStatus.SUCCESS,
            decode_start_status=_aggregate(early),
            sampled_decode_status=sampled_status,
            full_decode_status=full_status,
            duration_plausibility_status=duration_status,
            probes=probes,
            warnings=tuple(warnings),
            valid=valid,
        )
