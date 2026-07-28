"""Explicit, validated audio chunk materialization with cache reuse."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .addressing_contracts import MediaInterval, TimeDomain
from .chunk_contracts import ProcessingChunk
from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .materialization_contracts import (
    MATERIALIZED_CHUNK_FORMAT_VERSION,
    ChunkMaterializationKey,
    ChunkMaterializationPolicy,
    ChunkMaterializationResult,
    MaterializedChunk,
    MaterializedChunkEntry,
    MaterializedChunkIntegrity,
)
from .media import inspect_media, sha256_file
from .normalization_contracts import (
    AudioDerivative,
    CacheDisposition,
)
from .phase1_contracts import AudioStreamDescriptor, ToolInvocationRecord
from .qualification import _version, discover_ffmpeg

PROVIDER_IDENTITY = "ffmpeg.audio-chunk-materializer.v1.0.0"


class ChunkMaterializationError(RuntimeError):
    pass


def _decimal_seconds(microseconds: int) -> str:
    whole, fractional = divmod(microseconds, 1_000_000)
    return f"{whole}.{fractional:06d}"


def build_chunk_materialization_key(
    chunk: ProcessingChunk,
    derivative: AudioDerivative,
    policy: ChunkMaterializationPolicy,
    tool,
    reason: str,
) -> ChunkMaterializationKey:
    configuration_hash = canonical_hash(
        {
            "policy": policy.model_dump(
                mode="json",
                exclude={
                    "timeout_seconds",
                    "invalid_cache_action",
                    "duration_tolerance_microseconds",
                },
            ),
            "corpus_interval": chunk.corpus_interval.model_dump(mode="json"),
            "source_interval": chunk.source_interval.model_dump(mode="json"),
            "sample_rate": derivative.sample_rate,
            "channels": derivative.channels,
            "sample_format": derivative.sample_format,
            "reason": reason,
        }
    )
    tool_hash = canonical_hash(
        {
            "product": tool.product,
            "executable_sha256": tool.executable_sha256,
            "version_line": tool.version_line,
            "build_configuration": tool.build_configuration,
        }
    )
    components = {
        "operation": "chunk.materialize.audio",
        "operation_version": policy.policy_version,
        "chunk_id": chunk.chunk_id,
        "source_derivative_id": derivative.derivative_id,
        "source_derivative_sha256": derivative.content_sha256,
        "configuration_hash": configuration_hash,
        "provider_identity": PROVIDER_IDENTITY,
        "external_tool_identity_hash": tool_hash,
        "artifact_format_version": MATERIALIZED_CHUNK_FORMAT_VERSION,
    }
    digest = canonical_hash(components)
    return ChunkMaterializationKey(
        cache_id=typed_id("chunkcache", digest),
        digest=digest,
        chunk_id=chunk.chunk_id,
        source_derivative_id=derivative.derivative_id,
        source_derivative_sha256=derivative.content_sha256,
        configuration_hash=configuration_hash,
        provider_identity=PROVIDER_IDENTITY,
        external_tool_identity_hash=tool_hash,
    )


def _inspect_chunk(
    path: Path,
    derivative: AudioDerivative,
    expected_duration: int,
    policy: ChunkMaterializationPolicy,
    ffprobe: str | None,
) -> tuple[MaterializedChunkIntegrity, int]:
    findings: list[str] = []
    try:
        inspection = inspect_media(
            path,
            ffprobe=ffprobe,
            timeout_seconds=min(policy.timeout_seconds, 3600),
        )
        streams = [
            stream
            for stream in inspection.streams
            if isinstance(stream, AudioStreamDescriptor)
        ]
    except Exception as exc:
        streams = []
        findings.append(f"decode inspection failed: {exc}")
        inspection = None
    decodable = len(streams) == 1
    if not decodable and not findings:
        findings.append("materialized chunk must contain exactly one audio stream")
    stream = streams[0] if decodable else None
    actual_duration = (
        stream.duration_microseconds
        if stream and stream.duration_microseconds is not None
        else (
            inspection.container.duration_microseconds
            if inspection is not None
            else None
        )
    )
    duration_agrees = (
        actual_duration is not None
        and abs(actual_duration - expected_duration)
        <= policy.duration_tolerance_microseconds
    )
    sample_rate_agrees = bool(
        stream and stream.sample_rate == derivative.sample_rate
    )
    channel_count_agrees = bool(stream and stream.channels == derivative.channels)
    sample_format_agrees = bool(
        stream and stream.sample_format == derivative.sample_format
    )
    if not duration_agrees:
        findings.append("materialized duration differs from requested interval")
    if not sample_rate_agrees:
        findings.append("sample rate differs from normalized derivative")
    if not channel_count_agrees:
        findings.append("channel count differs from normalized derivative")
    if not sample_format_agrees:
        findings.append("sample format differs from normalized derivative")
    if not path.is_file() or path.stat().st_size <= 0:
        raise ChunkMaterializationError("materialized output is absent or empty")
    integrity = MaterializedChunkIntegrity(
        content_sha256=sha256_file(path),
        byte_size=path.stat().st_size,
        decodable=decodable,
        duration_agrees=duration_agrees,
        sample_rate_agrees=sample_rate_agrees,
        channel_count_agrees=channel_count_agrees,
        sample_format_agrees=sample_format_agrees,
        valid=all(
            (
                decodable,
                duration_agrees,
                sample_rate_agrees,
                channel_count_agrees,
                sample_format_agrees,
            )
        ),
        findings=tuple(findings),
    )
    return integrity, actual_duration or 1


def _safe_output(entry_dir: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ChunkMaterializationError("chunk path is not portable")
    resolved = (entry_dir / candidate).resolve()
    root = entry_dir.resolve()
    if resolved != root and root not in resolved.parents:
        raise ChunkMaterializationError("chunk path escapes cache entry")
    return resolved


def _validate_entry(
    entry_dir: Path,
    key: ChunkMaterializationKey,
    derivative: AudioDerivative,
    expected_duration: int,
    policy: ChunkMaterializationPolicy,
    ffprobe: str | None,
) -> tuple[MaterializedChunkEntry | None, CacheDisposition]:
    manifest = entry_dir / "entry.json"
    if not manifest.is_file():
        return None, CacheDisposition.INVALID
    try:
        entry = load_contract(manifest.read_bytes(), MaterializedChunkEntry)
        assert isinstance(entry, MaterializedChunkEntry)
    except Exception:
        return None, CacheDisposition.CORRUPTED
    if entry.key != key:
        return None, CacheDisposition.STALE
    if not entry.complete:
        return None, CacheDisposition.INVALID
    materialized = entry.materialized_chunk
    if (
        materialized.source_derivative_id != derivative.derivative_id
        or materialized.source_derivative_sha256 != derivative.content_sha256
    ):
        return None, CacheDisposition.INCOMPATIBLE
    try:
        output = _safe_output(entry_dir, materialized.relative_path)
    except ChunkMaterializationError:
        return None, CacheDisposition.CORRUPTED
    if (
        not output.is_file()
        or sha256_file(output) != materialized.integrity.content_sha256
    ):
        return None, CacheDisposition.CORRUPTED
    integrity, actual_duration = _inspect_chunk(
        output, derivative, expected_duration, policy, ffprobe
    )
    if (
        not integrity.valid
        or integrity != materialized.integrity
        or actual_duration != materialized.actual_duration_microseconds
    ):
        return None, CacheDisposition.INVALID
    return entry, CacheDisposition.HIT


def _archive_invalid(entry_dir: Path, cache_root: Path) -> None:
    invalid = cache_root / "invalid"
    invalid.mkdir(parents=True, exist_ok=True)
    shutil.move(
        str(entry_dir),
        str(invalid / f"{entry_dir.name}-{uuid.uuid4().hex}"),
    )


def materialize_audio_chunk(
    chunk: ProcessingChunk,
    derivative: AudioDerivative,
    derivative_path: Path,
    output_root: Path,
    *,
    reason: str = "provider_required",
    policy: ChunkMaterializationPolicy | None = None,
    ffmpeg: str | None = None,
    ffprobe: str | None = None,
    use_cache: bool = True,
) -> ChunkMaterializationResult:
    policy = policy or ChunkMaterializationPolicy()
    source = derivative_path.expanduser().resolve(strict=True)
    if sha256_file(source) != derivative.content_sha256:
        raise ChunkMaterializationError(
            "normalized derivative hash no longer matches its manifest"
        )
    executable = discover_ffmpeg(ffmpeg)
    tool = _version(executable, min(policy.timeout_seconds, 3600))
    key = build_chunk_materialization_key(
        chunk, derivative, policy, tool, reason
    )
    root = output_root.expanduser().resolve()
    cache_root = root / (
        "cache/chunk-materialize" if use_cache else "derivatives/chunks"
    )
    cache_root.mkdir(parents=True, exist_ok=True)
    entry_dir = cache_root / key.digest
    prior = CacheDisposition.MISS
    expected_duration = chunk.corpus_interval.duration_microseconds
    if use_cache and entry_dir.exists():
        entry, disposition = _validate_entry(
            entry_dir,
            key,
            derivative,
            expected_duration,
            policy,
            ffprobe,
        )
        if entry is not None:
            return ChunkMaterializationResult(
                policy=policy,
                cache_disposition=CacheDisposition.HIT,
                cache_key=key,
                cache_entry_path=str(entry_dir),
                materialized_chunk=entry.materialized_chunk,
            )
        prior = disposition
        if policy.invalid_cache_action == "refuse":
            raise ChunkMaterializationError(
                f"chunk cache entry is {disposition.value}; policy refuses rebuild"
            )
        _archive_invalid(entry_dir, cache_root)
    elif not use_cache:
        prior = CacheDisposition.BYPASSED
        if entry_dir.exists():
            raise FileExistsError(
                f"materialized chunk destination already exists: {entry_dir}"
            )
    temp_dir = Path(
        tempfile.mkdtemp(prefix=f"{key.digest}.partial-", dir=cache_root)
    )
    output = temp_dir / "chunk.flac"
    arguments = (
        "-hide_banner",
        "-nostdin",
        "-v",
        "error",
        "-ss",
        _decimal_seconds(chunk.corpus_interval.start_microseconds),
        "-i",
        str(source),
        "-t",
        _decimal_seconds(expected_duration),
        "-map",
        "0:a:0",
        "-vn",
        "-c:a",
        policy.codec,
        "-compression_level",
        str(policy.compression_level),
        "-map_metadata",
        "-1",
        "-fflags",
        "+bitexact",
        "-flags:a",
        "+bitexact",
        "-n",
        str(output),
    )
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
        raise ChunkMaterializationError(
            f"chunk materialization exceeded {policy.timeout_seconds} seconds; "
            f"partial attempt preserved at {temp_dir}"
        ) from exc
    finished = datetime.now(timezone.utc)
    invocation = ToolInvocationRecord(
        executable=str(executable),
        arguments=arguments,
        started_at=started,
        completed_at=finished,
        exit_code=completed.returncode,
        standard_output=completed.stdout,
        standard_error=completed.stderr,
    )
    if completed.returncode != 0 or not output.is_file():
        raise ChunkMaterializationError(
            f"FFmpeg chunk materialization failed with exit code "
            f"{completed.returncode}; partial attempt preserved at {temp_dir}: "
            f"{completed.stderr.strip()}"
        )
    integrity, actual_duration = _inspect_chunk(
        output, derivative, expected_duration, policy, ffprobe
    )
    if not integrity.valid:
        raise ChunkMaterializationError(
            "materialized chunk failed integrity; partial attempt preserved at "
            f"{temp_dir}: {', '.join(integrity.findings)}"
        )
    derivative_local = MediaInterval(
        domain=TimeDomain.DERIVATIVE_LOCAL,
        start_microseconds=chunk.corpus_interval.start_microseconds,
        duration_microseconds=expected_duration,
    )
    materialized = MaterializedChunk(
        materialized_chunk_id=typed_id(
            "materialized", key.digest, integrity.content_sha256
        ),
        chunk_id=chunk.chunk_id,
        ordinal=chunk.ordinal,
        source_derivative_id=derivative.derivative_id,
        source_derivative_sha256=derivative.content_sha256,
        relative_path="chunk.flac",
        reason=reason,
        corpus_interval=chunk.corpus_interval,
        source_interval=chunk.source_interval,
        derivative_local_interval=derivative_local,
        sample_rate=derivative.sample_rate,
        channels=derivative.channels,
        sample_format=derivative.sample_format,
        expected_duration_microseconds=expected_duration,
        actual_duration_microseconds=actual_duration,
        integrity=integrity,
        tool=tool,
        invocation=invocation,
    )
    entry = MaterializedChunkEntry(
        key=key,
        created_at=finished,
        materialized_chunk=materialized,
    )
    (temp_dir / "entry.json").write_bytes(canonical_bytes(entry))
    if sha256_file(source) != derivative.content_sha256:
        raise ChunkMaterializationError(
            f"normalized derivative changed during materialization; "
            f"partial attempt preserved at {temp_dir}"
        )
    os.replace(temp_dir, entry_dir)
    disposition = (
        CacheDisposition.REBUILT
        if prior
        in {
            CacheDisposition.INVALID,
            CacheDisposition.STALE,
            CacheDisposition.CORRUPTED,
            CacheDisposition.INCOMPATIBLE,
        }
        else prior
    )
    return ChunkMaterializationResult(
        policy=policy,
        cache_disposition=disposition,
        cache_key=key,
        cache_entry_path=str(entry_dir),
        materialized_chunk=materialized,
    )


def load_materialized_chunk(entry: Path) -> MaterializedChunkEntry:
    manifest = entry if entry.name == "entry.json" else entry / "entry.json"
    result = load_contract(manifest.read_bytes(), MaterializedChunkEntry)
    assert isinstance(result, MaterializedChunkEntry)
    return result


def list_materialized_chunks(output_root: Path) -> tuple[MaterializedChunkEntry, ...]:
    root = output_root.expanduser().resolve() / "cache/chunk-materialize"
    if not root.exists():
        return ()
    return tuple(
        load_materialized_chunk(path)
        for path in sorted(root.glob("*/entry.json"))
    )
