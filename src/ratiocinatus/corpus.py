"""Portable corpus assembly, loading, export, and integrity validation."""

from __future__ import annotations

import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .addressing_contracts import SourceTimeline
from .chunk_contracts import ProcessingChunkPlan
from .contracts import IntegrityState
from .corpus_contracts import (
    AudiovisualCorpus,
    CorpusArtifactReference,
    CorpusIntegrityReport,
    NormalizedSourceReport,
)
from .kernel import canonical_bytes, load_contract, typed_id
from .media import fingerprint_file, inspect_media, sha256_file
from .normalization_contracts import AudioDerivative, AudioNormalizationResult
from .phase1_contracts import MediaInspectionResult
from .qualification_contracts import DecodeQualificationResult
from .selection_contracts import StreamSelectionResult
from .video_contracts import VideoAccessPlan


def _atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.partial-{uuid.uuid4().hex}")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f"{destination.name}.partial-{uuid.uuid4().hex}"
    )
    shutil.copyfile(source, temporary)
    os.replace(temporary, destination)


def _reference(root: Path, path: Path, artifact_type: str) -> CorpusArtifactReference:
    relative = path.relative_to(root).as_posix()
    return CorpusArtifactReference(
        artifact_type=artifact_type,
        relative_path=relative,
        content_sha256=sha256_file(path),
        byte_size=path.stat().st_size,
    )


def _safe_path(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"non-portable corpus path: {relative}")
    resolved_root = root.resolve()
    resolved = (resolved_root / candidate).resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ValueError(f"corpus path escapes root: {relative}")
    return resolved


def assemble_corpus(
    corpus_root: Path,
    *,
    source: Path,
    inspection: MediaInspectionResult,
    selection: StreamSelectionResult,
    qualification: DecodeQualificationResult,
    timeline: SourceTimeline,
    audio_result: AudioNormalizationResult,
    video_access: VideoAccessPlan,
    chunk_plan: ProcessingChunkPlan,
    configuration_hash: str,
    created_at: datetime | None = None,
) -> AudiovisualCorpus:
    root = corpus_root.expanduser().resolve()
    manifest_path = root / "manifest.json"
    if manifest_path.exists():
        raise FileExistsError(f"corpus already exists: {root}")
    root.mkdir(parents=True, exist_ok=True)
    source = source.resolve(strict=True)
    if fingerprint_file(source) != inspection.source_fingerprint:
        raise ValueError("source fingerprint does not match inspection")

    source_path = root / "source" / f"original{source.suffix.lower()}"
    if not source_path.exists():
        _atomic_copy(source, source_path)
    audio_source = (
        Path(audio_result.cache_entry_path)
        / audio_result.derivative.relative_path
    ).resolve(strict=True)
    audio_path = root / "derivatives" / "audio.flac"
    _atomic_copy(audio_source, audio_path)

    metadata = root / "metadata"
    portable_inspection = inspection.model_copy(
        update={"source": source_path.relative_to(root).as_posix()}
    )
    portable_video = video_access.model_copy(
        update={"source": source_path.relative_to(root).as_posix()}
    )
    portable_audio = audio_result.derivative.model_copy(
        update={"relative_path": audio_path.relative_to(root).as_posix()}
    )
    values: tuple[tuple[str, Any, str], ...] = (
        ("inspection.json", portable_inspection, "media_inspection"),
        ("selection.json", selection, "stream_selection"),
        ("qualification.json", qualification, "decode_qualification"),
        ("timeline.json", timeline, "source_timeline"),
        ("audio-derivative.json", portable_audio, "audio_derivative"),
        ("video-access.json", portable_video, "video_access"),
        ("chunk-plan.json", chunk_plan, "chunk_plan"),
    )
    references: dict[str, CorpusArtifactReference] = {}
    for filename, value, artifact_type in values:
        path = metadata / filename
        _atomic_bytes(path, canonical_bytes(value))
        references[artifact_type] = _reference(root, path, artifact_type)
    source_ref = _reference(root, source_path, "original_source")
    audio_ref = _reference(root, audio_path, "normalized_audio")
    corpus_id = typed_id(
        "corpus",
        inspection.source_id,
        configuration_hash,
        tuple(sorted(ref.content_sha256 for ref in references.values())),
        source_ref.content_sha256,
        audio_ref.content_sha256,
    )
    corpus = AudiovisualCorpus(
        corpus_id=corpus_id,
        created_at=created_at or datetime.now(timezone.utc),
        source_id=inspection.source_id,
        source_fingerprint=inspection.source_fingerprint,
        source=source_ref,
        inspection=references["media_inspection"],
        selection=references["stream_selection"],
        qualification=references["decode_qualification"],
        timeline=references["source_timeline"],
        normalized_audio=audio_ref,
        normalized_audio_manifest=references["audio_derivative"],
        video_access=references["video_access"],
        chunk_plan=references["chunk_plan"],
        cache_keys=(audio_result.cache_key,),
        configuration_hash=configuration_hash,
        integrity=IntegrityState.VALID,
        provenance=tuple(references.values()),
        complete=True,
    )
    _atomic_bytes(manifest_path, canonical_bytes(corpus))
    report = validate_corpus(root)
    if not report.valid:
        raise ValueError(
            "assembled corpus failed integrity: " + "; ".join(report.findings)
        )
    return corpus


def load_corpus(root: Path) -> dict[str, Any]:
    root = root.expanduser().resolve()
    corpus = load_contract((root / "manifest.json").read_bytes(), AudiovisualCorpus)
    assert isinstance(corpus, AudiovisualCorpus)

    def load(reference: CorpusArtifactReference, model):
        return load_contract(
            _safe_path(root, reference.relative_path).read_bytes(), model
        )

    inspection = load(corpus.inspection, MediaInspectionResult)
    selection = load(corpus.selection, StreamSelectionResult)
    qualification = load(corpus.qualification, DecodeQualificationResult)
    timeline = load(corpus.timeline, SourceTimeline)
    audio = load(corpus.normalized_audio_manifest, AudioDerivative)
    video = load(corpus.video_access, VideoAccessPlan)
    chunks = load(corpus.chunk_plan, ProcessingChunkPlan)
    source_path = _safe_path(root, corpus.source.relative_path)
    video = video.model_copy(update={"source": str(source_path)})
    inspection = inspection.model_copy(update={"source": str(source_path)})
    return {
        "root": root,
        "corpus": corpus,
        "inspection": inspection,
        "selection": selection,
        "qualification": qualification,
        "timeline": timeline,
        "audio": audio,
        "audio_path": _safe_path(root, corpus.normalized_audio.relative_path),
        "video": video,
        "chunks": chunks,
        "source_path": source_path,
    }


def validate_corpus(root: Path) -> CorpusIntegrityReport:
    root = root.expanduser().resolve()
    findings: list[str] = []
    checked = 0
    try:
        corpus = load_contract((root / "manifest.json").read_bytes(), AudiovisualCorpus)
        assert isinstance(corpus, AudiovisualCorpus)
    except Exception as exc:
        return CorpusIntegrityReport(
            corpus_id="corpus_" + "0" * 32,
            generated_at=datetime.now(timezone.utc),
            valid=False,
            checked_artifacts=0,
            findings=(f"manifest invalid: {exc}",),
        )
    references = (
        corpus.source,
        corpus.inspection,
        corpus.selection,
        corpus.qualification,
        corpus.timeline,
        corpus.normalized_audio,
        corpus.normalized_audio_manifest,
        corpus.video_access,
        corpus.chunk_plan,
        *corpus.provenance,
    )
    seen: set[str] = set()
    for reference in references:
        if reference.relative_path in seen:
            continue
        seen.add(reference.relative_path)
        checked += 1
        try:
            path = _safe_path(root, reference.relative_path)
        except ValueError as exc:
            findings.append(str(exc))
            continue
        if not path.is_file():
            findings.append(f"missing artifact: {reference.relative_path}")
            continue
        if path.stat().st_size != reference.byte_size:
            findings.append(f"artifact size mismatch: {reference.relative_path}")
        if sha256_file(path) != reference.content_sha256:
            findings.append(f"artifact hash mismatch: {reference.relative_path}")
    try:
        loaded = load_corpus(root)
        if fingerprint_file(loaded["source_path"]) != corpus.source_fingerprint:
            findings.append("source fingerprint mismatch")
        if loaded["inspection"].source_id != corpus.source_id:
            findings.append("inspection source identity mismatch")
        inventory_ids = {
            stream.stream_id for stream in loaded["inspection"].streams
        }
        for selected_id in (
            loaded["selection"].audio.selected_stream_id,
            loaded["selection"].video.selected_stream_id,
        ):
            if selected_id is not None and selected_id not in inventory_ids:
                findings.append("selection references unknown stream")
        if not loaded["qualification"].valid:
            findings.append("decode qualification is invalid")
        if loaded["timeline"].source_id != corpus.source_id:
            findings.append("timeline source identity mismatch")
        if not loaded["audio"].integrity.valid:
            findings.append("audio derivative integrity is invalid")
        if sha256_file(loaded["audio_path"]) != loaded["audio"].content_sha256:
            findings.append("audio derivative substitution detected")
        if not loaded["chunks"].coverage_complete:
            findings.append("chunk coverage is incomplete")
    except Exception as exc:
        findings.append(f"contract lineage invalid: {exc}")
    return CorpusIntegrityReport(
        corpus_id=corpus.corpus_id,
        generated_at=datetime.now(timezone.utc),
        valid=not findings,
        checked_artifacts=checked,
        findings=tuple(findings),
    )


def normalized_source_report(root: Path) -> NormalizedSourceReport:
    loaded = load_corpus(root)
    corpus = loaded["corpus"]
    return NormalizedSourceReport(
        corpus_id=corpus.corpus_id,
        generated_at=datetime.now(timezone.utc),
        source_id=corpus.source_id,
        source_bytes=corpus.source.byte_size,
        source_duration_microseconds=loaded["timeline"].source_duration_microseconds,
        audio_derivative_bytes=corpus.normalized_audio.byte_size,
        audio_duration_microseconds=loaded["audio"].duration_microseconds,
        video_strategy=loaded["video"].policy.strategy,
        chunk_count=len(loaded["chunks"].chunks),
        cache_ids=tuple(key.cache_id for key in corpus.cache_keys),
        status="complete",
    )


def export_corpus(root: Path, destination: Path) -> Path:
    source = root.expanduser().resolve(strict=True)
    destination = destination.expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f"corpus export destination exists: {destination}")
    shutil.copytree(source, destination)
    report = validate_corpus(destination)
    if not report.valid:
        raise ValueError("exported corpus failed validation")
    return destination
