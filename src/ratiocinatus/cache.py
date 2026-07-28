"""Read-only cache and derivative inspection utilities."""

from __future__ import annotations

from pathlib import Path

from .kernel import load_contract
from .media import sha256_file
from .normalization import _inspect_normalized_audio, _safe_derivative_path
from .normalization_contracts import (
    AudioNormalizationPolicy,
    CacheEntry,
)


def entry_manifests(output_root: Path) -> tuple[Path, ...]:
    root = output_root.expanduser().resolve()
    paths = {
        *root.glob("cache/audio-normalize/*/entry.json"),
        *root.glob("derivatives/audio/*/entry.json"),
    }
    return tuple(sorted(paths))


def load_cache_entry(path: Path) -> CacheEntry:
    target = path.expanduser().resolve()
    manifest = target / "entry.json" if target.is_dir() else target
    entry = load_contract(manifest.read_bytes(), CacheEntry)
    assert isinstance(entry, CacheEntry)
    return entry


def list_derivatives(output_root: Path) -> tuple[dict[str, object], ...]:
    results = []
    for manifest in entry_manifests(output_root):
        try:
            entry = load_cache_entry(manifest)
            results.append({
                "derivative_id": entry.derivative.derivative_id,
                "source_id": entry.derivative.source_id,
                "source_stream_id": entry.derivative.source_stream_id,
                "entry_path": str(manifest.parent),
                "content_sha256": entry.derivative.content_sha256,
                "sample_rate": entry.derivative.sample_rate,
                "channels": entry.derivative.channels,
                "valid": entry.derivative.integrity.valid,
            })
        except Exception as exc:
            results.append({
                "derivative_id": "invalid",
                "entry_path": str(manifest.parent),
                "valid": False,
                "error": str(exc),
            })
    return tuple(results)


def validate_cache(
    output_root: Path,
    ffprobe: str | None = None,
) -> tuple[dict[str, object], ...]:
    results = []
    for manifest in entry_manifests(output_root):
        findings: list[str] = []
        try:
            entry = load_cache_entry(manifest)
            derivative_path = _safe_derivative_path(
                manifest.parent, entry.derivative.relative_path
            )
            if not derivative_path.is_file():
                findings.append("derivative file is missing")
            elif sha256_file(derivative_path) != entry.derivative.content_sha256:
                findings.append("derivative hash mismatch")
            else:
                policy = AudioNormalizationPolicy(
                    sample_rate=entry.derivative.sample_rate
                )
                integrity, duration, sample_count = _inspect_normalized_audio(
                    derivative_path,
                    entry.derivative.duration_microseconds,
                    policy,
                    ffprobe,
                )
                if not integrity.valid:
                    findings.extend(integrity.findings)
                if duration != entry.derivative.duration_microseconds:
                    findings.append("derivative duration metadata mismatch")
                if sample_count != entry.derivative.sample_count:
                    findings.append("derivative sample-count metadata mismatch")
            results.append({
                "cache_id": entry.key.cache_id,
                "entry_path": str(manifest.parent),
                "valid": not findings,
                "findings": findings,
            })
        except Exception as exc:
            results.append({
                "cache_id": "invalid",
                "entry_path": str(manifest.parent),
                "valid": False,
                "findings": [str(exc)],
            })
    return tuple(results)
