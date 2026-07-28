"""Evidence-preserving audio normalization with validated cache reuse."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .addressing import build_source_timeline
from .addressing_contracts import (
    IntervalMapping,
    IntervalMappingSegment,
    MappingClassification,
    MediaInterval,
    TimeDomain,
)
from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .media import fingerprint_file, inspect_media, sha256_file
from .normalization_contracts import (
    AUDIO_DERIVATIVE_FORMAT_VERSION,
    AudioDerivative,
    AudioNormalizationPolicy,
    AudioNormalizationResult,
    CacheDisposition,
    CacheEntry,
    CacheKey,
    DerivativeIntegrityRecord,
)
from .phase1_contracts import (
    AudioStreamDescriptor,
    MediaInspectionResult,
    ToolInvocationRecord,
)
from .qualification import _version, discover_ffmpeg
from .selection_contracts import StreamSelectionResult

PROVIDER_IDENTITY = "ffmpeg.audio-normalizer.v1.0.0"


class AudioNormalizationError(RuntimeError):
    pass


def _selected_audio(
    inspection: MediaInspectionResult,
    selection: StreamSelectionResult,
) -> AudioStreamDescriptor:
    stream_id = selection.audio.selected_stream_id
    if not selection.valid or stream_id is None:
        raise ValueError("normalization requires a valid selected audio stream")
    stream = next(
        (item for item in inspection.streams if item.stream_id == stream_id),
        None,
    )
    if not isinstance(stream, AudioStreamDescriptor):
        raise ValueError("selected audio stream does not resolve to audio metadata")
    if stream.channels is None or stream.channels <= 0:
        raise ValueError("selected audio stream has no valid channel count")
    return stream


def _coefficient_text(value: Decimal) -> str:
    text = format(value, "f").rstrip("0").rstrip(".")
    return text or "0"


def equal_weight_pan_filter(channels: int) -> str | None:
    if channels <= 0:
        raise ValueError("channel count must be positive")
    if channels == 1:
        return None
    weight = (Decimal(1) / Decimal(channels)).quantize(Decimal("0.000000000001"))
    weights = [weight] * (channels - 1)
    weights.append(Decimal(1) - sum(weights))
    terms = "+".join(
        f"{_coefficient_text(value)}*c{index}"
        for index, value in enumerate(weights)
    )
    return f"pan=mono|c0={terms}"


def build_audio_cache_key(
    inspection: MediaInspectionResult,
    selection: StreamSelectionResult,
    policy: AudioNormalizationPolicy,
    tool,
) -> CacheKey:
    stream = _selected_audio(inspection, selection)
    configuration_hash = canonical_hash({
        "policy": policy.model_dump(
            mode="json",
            exclude={
                "timeout_seconds",
                "invalid_cache_action",
                "duration_tolerance_microseconds",
            },
        ),
        "selected_stream_id": stream.stream_id,
        "selected_stream_index": stream.stream_index,
        "original_channels": stream.channels,
        "original_layout": stream.channel_layout,
    })
    tool_hash = canonical_hash({
        "product": tool.product,
        "executable_sha256": tool.executable_sha256,
        "version_line": tool.version_line,
        "build_configuration": tool.build_configuration,
    })
    components = {
        "operation": "audio.normalize",
        "operation_version": policy.policy_version,
        "source_fingerprint": inspection.source_fingerprint.model_dump(mode="json"),
        "source_stream_id": stream.stream_id,
        "configuration_hash": configuration_hash,
        "provider_identity": PROVIDER_IDENTITY,
        "external_tool_identity_hash": tool_hash,
        "artifact_format_version": AUDIO_DERIVATIVE_FORMAT_VERSION,
    }
    digest = canonical_hash(components)
    return CacheKey(
        cache_id=typed_id("cache", digest),
        digest=digest,
        source_fingerprint=inspection.source_fingerprint,
        source_stream_id=stream.stream_id,
        configuration_hash=configuration_hash,
        provider_identity=PROVIDER_IDENTITY,
        external_tool_identity_hash=tool_hash,
    )


def _safe_derivative_path(entry_dir: Path, relative: str) -> Path:
    relative_path = Path(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise AudioNormalizationError("cache derivative path is not portable")
    path = (entry_dir / relative_path).resolve()
    root = entry_dir.resolve()
    if path != root and root not in path.parents:
        raise AudioNormalizationError("cache derivative escapes its entry")
    return path


def _inspect_normalized_audio(
    path: Path,
    expected_duration_microseconds: int,
    policy: AudioNormalizationPolicy,
    ffprobe: str | None,
) -> tuple[DerivativeIntegrityRecord, int, int | None]:
    findings: list[str] = []
    try:
        inspection = inspect_media(
            path, ffprobe=ffprobe, timeout_seconds=min(policy.timeout_seconds, 3600)
        )
    except Exception as exc:
        digest = sha256_file(path) if path.is_file() else "0" * 64
        size = path.stat().st_size if path.is_file() else 0
        return (
            DerivativeIntegrityRecord(
                derivative_sha256=digest,
                byte_size=max(size, 1),
                decodable=False,
                duration_agrees=False,
                sample_rate_agrees=False,
                channel_count_agrees=False,
                sample_format_agrees=False,
                valid=False,
                findings=(f"decode inspection failed: {exc}",),
            ),
            1,
            None,
        )
    streams = [
        stream
        for stream in inspection.streams
        if isinstance(stream, AudioStreamDescriptor)
    ]
    decodable = len(streams) == 1
    if not decodable:
        findings.append("normalized derivative must contain exactly one audio stream")
        stream = None
    else:
        stream = streams[0]
    actual_duration = (
        stream.duration_microseconds
        if stream and stream.duration_microseconds is not None
        else inspection.container.duration_microseconds
    )
    duration_agrees = (
        actual_duration is not None
        and abs(actual_duration - expected_duration_microseconds)
        <= policy.duration_tolerance_microseconds
    )
    if not duration_agrees:
        findings.append("normalized duration differs from selected source stream")
    sample_rate_agrees = bool(stream and stream.sample_rate == policy.sample_rate)
    channel_count_agrees = bool(stream and stream.channels == policy.channels)
    sample_format_agrees = bool(stream and stream.sample_format == policy.sample_format)
    if not sample_rate_agrees:
        findings.append("normalized sample rate does not match policy")
    if not channel_count_agrees:
        findings.append("normalized channel count does not match policy")
    if not sample_format_agrees:
        findings.append("normalized sample format does not match policy")
    digest = sha256_file(path)
    size = path.stat().st_size
    integrity = DerivativeIntegrityRecord(
        derivative_sha256=digest,
        byte_size=size,
        decodable=decodable,
        duration_agrees=duration_agrees,
        sample_rate_agrees=sample_rate_agrees,
        channel_count_agrees=channel_count_agrees,
        sample_format_agrees=sample_format_agrees,
        valid=all((
            decodable,
            duration_agrees,
            sample_rate_agrees,
            channel_count_agrees,
            sample_format_agrees,
        )),
        findings=tuple(findings),
    )
    return integrity, actual_duration or 1, stream.duration_timestamp if stream else None


def _validate_cached_entry(
    entry_dir: Path,
    key: CacheKey,
    policy: AudioNormalizationPolicy,
    ffprobe: str | None,
    expected_source_id: str,
    expected_stream_id: str,
    expected_duration_microseconds: int,
) -> tuple[CacheEntry | None, CacheDisposition]:
    manifest = entry_dir / "entry.json"
    if not manifest.is_file():
        return None, CacheDisposition.INVALID
    try:
        entry = load_contract(manifest.read_bytes(), CacheEntry)
        assert isinstance(entry, CacheEntry)
    except Exception:
        return None, CacheDisposition.CORRUPTED
    if entry.key != key:
        return None, CacheDisposition.STALE
    if (
        entry.derivative.source_id != expected_source_id
        or entry.derivative.source_stream_id != expected_stream_id
    ):
        return None, CacheDisposition.INCOMPATIBLE
    if not entry.complete:
        return None, CacheDisposition.INVALID
    try:
        derivative_path = _safe_derivative_path(
            entry_dir, entry.derivative.relative_path
        )
    except AudioNormalizationError:
        return None, CacheDisposition.CORRUPTED
    if not derivative_path.is_file():
        return None, CacheDisposition.CORRUPTED
    if sha256_file(derivative_path) != entry.derivative.content_sha256:
        return None, CacheDisposition.CORRUPTED
    integrity, duration, sample_count = _inspect_normalized_audio(
        derivative_path,
        expected_duration_microseconds,
        policy,
        ffprobe,
    )
    if (
        not integrity.valid
        or duration != entry.derivative.duration_microseconds
        or sample_count != entry.derivative.sample_count
    ):
        return None, CacheDisposition.INVALID
    return entry, CacheDisposition.HIT


def _archive_invalid(entry_dir: Path, cache_root: Path) -> Path:
    invalid_root = cache_root / "invalid"
    invalid_root.mkdir(parents=True, exist_ok=True)
    destination = invalid_root / f"{entry_dir.name}-{uuid.uuid4().hex}"
    shutil.move(str(entry_dir), str(destination))
    return destination


def normalize_audio(
    inspection: MediaInspectionResult,
    selection: StreamSelectionResult,
    output_root: Path,
    *,
    policy: AudioNormalizationPolicy | None = None,
    ffmpeg: str | None = None,
    ffprobe: str | None = None,
    use_cache: bool = True,
) -> AudioNormalizationResult:
    policy = policy or AudioNormalizationPolicy()
    stream = _selected_audio(inspection, selection)
    source = Path(inspection.source).resolve(strict=True)
    before = fingerprint_file(source)
    if before != inspection.source_fingerprint:
        raise ValueError("source fingerprint no longer matches inspection")
    executable = discover_ffmpeg(ffmpeg)
    tool = _version(executable, min(policy.timeout_seconds, 3600))
    key = build_audio_cache_key(inspection, selection, policy, tool)
    root = output_root.expanduser().resolve()
    cache_root = root / ("cache/audio-normalize" if use_cache else "derivatives/audio")
    cache_root.mkdir(parents=True, exist_ok=True)
    entry_dir = cache_root / key.digest
    prior_disposition = CacheDisposition.MISS
    if use_cache and entry_dir.exists():
        expected_cached_duration = (
            stream.duration_microseconds
            or inspection.container.duration_microseconds
        )
        if expected_cached_duration is None:
            raise AudioNormalizationError("selected audio duration is unavailable")
        entry, disposition = _validate_cached_entry(
            entry_dir,
            key,
            policy,
            ffprobe,
            inspection.source_id,
            stream.stream_id,
            expected_cached_duration,
        )
        if entry is not None:
            return AudioNormalizationResult(
                policy=policy,
                cache_disposition=CacheDisposition.HIT,
                cache_key=key,
                cache_entry_path=str(entry_dir),
                derivative=entry.derivative,
            )
        prior_disposition = disposition
        if policy.invalid_cache_action == "refuse":
            raise AudioNormalizationError(
                f"cache entry is {disposition.value}; policy refuses rebuild"
            )
        _archive_invalid(entry_dir, cache_root)
    elif not use_cache:
        prior_disposition = CacheDisposition.BYPASSED
        if entry_dir.exists():
            raise FileExistsError(f"derivative destination already exists: {entry_dir}")
    temp_dir = Path(tempfile.mkdtemp(prefix=f"{key.digest}.partial-", dir=cache_root))
    output = temp_dir / "audio.flac"
    pan = equal_weight_pan_filter(stream.channels)
    arguments = [
        "-hide_banner", "-nostdin", "-v", "error", "-i", str(source),
        "-map", f"0:{stream.stream_index}", "-vn",
    ]
    if pan:
        arguments.extend(("-af", pan))
    arguments.extend((
        "-ac", "1",
        "-ar", str(policy.sample_rate),
        "-sample_fmt", policy.sample_format,
        "-c:a", policy.codec,
        "-compression_level", str(policy.compression_level),
        "-map_metadata", "-1",
        "-fflags", "+bitexact",
        "-flags:a", "+bitexact",
        "-n", str(output),
    ))
    started = datetime.now(timezone.utc)
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
    except subprocess.TimeoutExpired as exc:
        raise AudioNormalizationError(
            f"FFmpeg normalization exceeded {policy.timeout_seconds} seconds; "
            f"partial attempt preserved at {temp_dir}"
        ) from exc
    finished = datetime.now(timezone.utc)
    invocation = ToolInvocationRecord(
        executable=str(executable),
        arguments=tuple(arguments),
        started_at=started,
        completed_at=finished,
        exit_code=completed.returncode,
        standard_output=completed.stdout,
        standard_error=completed.stderr,
    )
    if completed.returncode != 0 or not output.is_file():
        raise AudioNormalizationError(
            f"FFmpeg normalization failed with exit code {completed.returncode}; "
            f"partial attempt preserved at {temp_dir}: {completed.stderr.strip()}"
        )
    expected_duration = (
        stream.duration_microseconds
        or inspection.container.duration_microseconds
    )
    if expected_duration is None or expected_duration <= 0:
        raise AudioNormalizationError("selected audio duration is unavailable")
    integrity, actual_duration, sample_count = _inspect_normalized_audio(
        output, expected_duration, policy, ffprobe
    )
    if not integrity.valid:
        raise AudioNormalizationError(
            f"normalized derivative failed integrity; partial attempt preserved "
            f"at {temp_dir}: {', '.join(integrity.findings)}"
        )
    timeline = build_source_timeline(inspection, selection)
    source_start = (
        stream.start_time_microseconds
        if stream.start_time_microseconds is not None
        else timeline.source_start_microseconds
    )
    derivative_interval = MediaInterval(
        domain=TimeDomain.DERIVATIVE_LOCAL,
        start_microseconds=0,
        duration_microseconds=actual_duration,
    )
    source_interval = MediaInterval(
        domain=TimeDomain.SOURCE_MEDIA,
        start_microseconds=source_start,
        duration_microseconds=actual_duration,
    )
    mapping_classification = (
        MappingClassification.EXACT
        if actual_duration == expected_duration
        else MappingClassification.ROUNDED
    )
    mapping = IntervalMapping(
        source_id=inspection.source_id,
        source_domain=TimeDomain.DERIVATIVE_LOCAL,
        target_domain=TimeDomain.SOURCE_MEDIA,
        requested=derivative_interval,
        mapped=source_interval,
        classification=mapping_classification,
        segments=(
            IntervalMappingSegment(
                source=derivative_interval,
                target=source_interval,
                classification=mapping_classification,
            ),
        ),
        tolerance_microseconds=policy.duration_tolerance_microseconds,
        explanation=(
            "zero-based normalized audio maps linearly to selected audio source time"
            if mapping_classification == MappingClassification.EXACT
            else "linear mapping includes bounded decode/resample duration rounding"
        ),
    )
    derivative_id = typed_id(
        "derivative",
        key.digest,
        integrity.derivative_sha256,
    )
    derivative = AudioDerivative(
        derivative_id=derivative_id,
        source_id=inspection.source_id,
        source_stream_id=stream.stream_id,
        relative_path="audio.flac",
        content_sha256=integrity.derivative_sha256,
        byte_size=integrity.byte_size,
        duration_microseconds=actual_duration,
        interval_mapping=mapping,
        integrity=integrity,
        tool=tool,
        invocation=invocation,
        sample_rate=policy.sample_rate,
        sample_count=sample_count,
        original_channel_layout=stream.channel_layout,
        original_channel_count=stream.channels,
        downmix_policy=policy.downmix_policy,
        resampler=policy.resampler,
    )
    entry = CacheEntry(
        key=key,
        created_at=finished,
        derivative=derivative,
    )
    (temp_dir / "entry.json").write_bytes(canonical_bytes(entry))
    after = fingerprint_file(source)
    if after != before:
        raise ValueError(
            f"source changed during normalization; partial attempt preserved at {temp_dir}"
        )
    os.replace(temp_dir, entry_dir)
    disposition = (
        CacheDisposition.REBUILT
        if prior_disposition
        in {
            CacheDisposition.INVALID,
            CacheDisposition.STALE,
            CacheDisposition.CORRUPTED,
            CacheDisposition.INCOMPATIBLE,
        }
        else prior_disposition
    )
    return AudioNormalizationResult(
        policy=policy,
        cache_disposition=disposition,
        cache_key=key,
        cache_entry_path=str(entry_dir),
        derivative=derivative,
    )


def validate_audio_result(
    result: AudioNormalizationResult,
    *,
    ffprobe: str | None = None,
) -> bool:
    """Validate a committed normalization result before resume reuse."""
    try:
        entry_dir = Path(result.cache_entry_path).expanduser().resolve(strict=True)
        entry = load_contract((entry_dir / "entry.json").read_bytes(), CacheEntry)
        assert isinstance(entry, CacheEntry)
        if (
            entry.key != result.cache_key
            or entry.derivative != result.derivative
            or not entry.complete
        ):
            return False
        derivative_path = _safe_derivative_path(
            entry_dir, result.derivative.relative_path
        )
        if (
            not derivative_path.is_file()
            or sha256_file(derivative_path) != result.derivative.content_sha256
        ):
            return False
        integrity, duration, sample_count = _inspect_normalized_audio(
            derivative_path,
            result.derivative.duration_microseconds,
            result.policy,
            ffprobe,
        )
        return bool(
            integrity.valid
            and integrity == result.derivative.integrity
            and duration == result.derivative.duration_microseconds
            and sample_count == result.derivative.sample_count
        )
    except Exception:
        return False


def inspect_cache(output_root: Path) -> tuple[dict[str, str], ...]:
    cache_root = output_root.expanduser().resolve() / "cache/audio-normalize"
    if not cache_root.exists():
        return ()
    results = []
    for manifest in sorted(cache_root.glob("*/entry.json")):
        try:
            entry = load_contract(manifest.read_bytes(), CacheEntry)
            results.append({
                "cache_id": entry.key.cache_id,
                "digest": entry.key.digest,
                "entry": str(manifest.parent),
                "derivative_sha256": entry.derivative.content_sha256,
            })
        except Exception:
            results.append({
                "cache_id": "invalid",
                "digest": manifest.parent.name,
                "entry": str(manifest.parent),
                "derivative_sha256": "invalid",
            })
    return tuple(results)
