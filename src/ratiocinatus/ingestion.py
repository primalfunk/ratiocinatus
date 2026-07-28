"""Atomic Phase 1 ingestion stages with validation, interruption, and resume."""

from __future__ import annotations

import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .addressing import build_source_timeline
from .addressing_contracts import SourceTimeline
from .chunk_contracts import ProcessingChunkPlan
from .chunking import build_chunk_plan
from .corpus import (
    assemble_corpus,
    normalized_source_report,
    validate_corpus,
)
from .corpus_contracts import (
    AudiovisualCorpus,
    CorpusArtifactReference,
    IngestionCheckpoint,
    IngestionManifest,
    IngestionPolicy,
    IngestionRequest,
    IngestionStage,
    IngestionStageRecord,
    IngestionStageStatus,
)
from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .media import (
    discover_executable,
    fingerprint_file,
    inspect_media,
    inspect_tool,
    sha256_file,
)
from .normalization import normalize_audio, validate_audio_result
from .normalization_contracts import AudioNormalizationResult
from .phase1_contracts import MediaInspectionResult
from .qualification import (
    FFmpegDecodeQualificationProvider,
    _version,
    discover_ffmpeg,
)
from .qualification_contracts import DecodeQualificationResult
from .selection import select_streams
from .selection_contracts import StreamSelectionResult
from .video import create_video_access_plan
from .video_contracts import VideoAccessPlan


class IngestionInterrupted(RuntimeError):
    pass


def _atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.partial-{uuid.uuid4().hex}")
    temporary.write_bytes(canonical_bytes(value))
    os.replace(temporary, path)


def _reference(root: Path, path: Path, kind: str) -> CorpusArtifactReference:
    return CorpusArtifactReference(
        artifact_type=kind,
        relative_path=path.relative_to(root).as_posix(),
        content_sha256=sha256_file(path),
        byte_size=path.stat().st_size,
    )


def prepare_ingestion_request(
    source: Path,
    workspace: Path,
    *,
    policy: IngestionPolicy | None = None,
    ffprobe: str | None = None,
    ffmpeg: str | None = None,
) -> IngestionRequest:
    source = source.expanduser().resolve(strict=True)
    workspace = workspace.expanduser().resolve()
    policy = policy or IngestionPolicy()
    source_fingerprint = fingerprint_file(source)
    ffprobe_path = discover_executable(ffprobe)
    ffmpeg_path = discover_ffmpeg(ffmpeg)
    probe_tool = inspect_tool(ffprobe_path, policy.qualification.timeout_seconds)
    media_tool = _version(ffmpeg_path, policy.qualification.timeout_seconds)
    probe_hash = canonical_hash(probe_tool.model_dump(mode="json", exclude={"executable"}))
    media_hash = canonical_hash(media_tool.model_dump(mode="json", exclude={"executable"}))
    configuration_hash = canonical_hash({
        "policy": policy.model_dump(mode="json"),
        "ffprobe_identity": probe_hash,
        "ffmpeg_identity": media_hash,
    })
    ingestion_id = typed_id(
        "ingestion", source_fingerprint.digest, configuration_hash
    )
    return IngestionRequest(
        ingestion_id=ingestion_id,
        requested_at=datetime.now(timezone.utc),
        source=str(source),
        workspace=str(workspace),
        source_fingerprint=source_fingerprint,
        policy=policy,
        configuration_hash=configuration_hash,
        ffprobe=str(ffprobe_path),
        ffmpeg=str(ffmpeg_path),
        external_tool_identity_hashes=(probe_hash, media_hash),
    )


def run_ingestion(
    request: IngestionRequest,
    *,
    interrupt_after: IngestionStage | None = None,
) -> IngestionManifest:
    source = Path(request.source).resolve(strict=True)
    if fingerprint_file(source) != request.source_fingerprint:
        raise ValueError("source changed after ingestion request creation")
    workspace = Path(request.workspace).resolve()
    run_root = workspace / "ingestions" / request.ingestion_id
    run_root.mkdir(parents=True, exist_ok=True)
    request_path = run_root / "request.json"
    if request_path.exists():
        existing = load_contract(request_path.read_bytes(), IngestionRequest)
        if (
            existing.source_fingerprint != request.source_fingerprint
            or existing.configuration_hash != request.configuration_hash
        ):
            raise ValueError("existing ingestion request is incompatible")
    else:
        _atomic(request_path, request)
    checkpoint_path = run_root / "checkpoint.json"
    if checkpoint_path.exists():
        checkpoint = load_contract(
            checkpoint_path.read_bytes(), IngestionCheckpoint
        )
        assert isinstance(checkpoint, IngestionCheckpoint)
    else:
        checkpoint = IngestionCheckpoint(
            ingestion_id=request.ingestion_id,
            source_fingerprint=request.source_fingerprint,
            configuration_hash=request.configuration_hash,
        )
    attempt_id = typed_id(
        "attempt", request.ingestion_id, datetime.now(timezone.utc).isoformat(), uuid.uuid4().hex
    )

    def record(
        stage: IngestionStage,
        status: IngestionStageStatus,
        artifact: CorpusArtifactReference | None = None,
        message: str | None = None,
    ) -> None:
        nonlocal checkpoint
        item = IngestionStageRecord(
            stage=stage,
            status=status,
            attempt_id=attempt_id,
            recorded_at=datetime.now(timezone.utc),
            artifact=artifact,
            message=message,
        )
        checkpoint = checkpoint.model_copy(update={
            "latest_committed_stage": (
                stage
                if status in {IngestionStageStatus.COMMITTED, IngestionStageStatus.REUSED}
                else checkpoint.latest_committed_stage
            ),
            "records": (*checkpoint.records, item),
            "complete": stage == IngestionStage.COMPLETE and status in {
                IngestionStageStatus.COMMITTED,
                IngestionStageStatus.REUSED,
            },
        })
        _atomic(checkpoint_path, checkpoint)
        _atomic(
            run_root / "manifest.json",
            IngestionManifest(
                request=request,
                checkpoint=checkpoint,
                corpus=(
                    _reference(run_root, run_root / "corpus/manifest.json", "audiovisual_corpus")
                    if (run_root / "corpus/manifest.json").is_file()
                    else None
                ),
            ),
        )

    def maybe_interrupt(stage: IngestionStage) -> None:
        if interrupt_after == stage:
            record(
                stage,
                IngestionStageStatus.INTERRUPTED,
                message="intentional qualification interruption after committed stage",
            )
            raise IngestionInterrupted(f"interrupted after {stage.value}")

    def latest(stage: IngestionStage) -> IngestionStageRecord | None:
        return next(
            (
                item
                for item in reversed(checkpoint.records)
                if item.stage == stage
                and item.status
                in {IngestionStageStatus.COMMITTED, IngestionStageStatus.REUSED}
                and item.artifact is not None
            ),
            None,
        )

    def stage_model(
        stage: IngestionStage,
        relative: str,
        model,
        builder: Callable[[], Any],
        validator: Callable[[Any], bool] | None = None,
    ):
        path = run_root / relative
        for partial in sorted(path.parent.glob(f"{path.name}.partial-*")):
            if not partial.is_file():
                continue
            archive = (
                run_root / "attempts" / attempt_id / "partials" / relative / partial.name
            )
            archive.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(partial), str(archive))
            record(
                stage,
                IngestionStageStatus.FAILED,
                (
                    _reference(run_root, archive, f"{stage.value}_partial")
                    if archive.stat().st_size > 0
                    else None
                ),
                "orphan partial output preserved before stage recovery",
            )
        previous = latest(stage)
        if (
            previous is not None
            and path.is_file()
            and sha256_file(path) == previous.artifact.content_sha256
        ):
            try:
                value = load_contract(path.read_bytes(), model)
                if validator is not None and not validator(value):
                    raise ValueError("stage-specific reuse validation failed")
                record(stage, IngestionStageStatus.REUSED, previous.artifact)
                maybe_interrupt(stage)
                return value
            except Exception:
                pass
        if previous is not None:
            record(
                stage,
                IngestionStageStatus.INVALIDATED,
                previous.artifact,
                "artifact missing, modified, or contract-invalid",
            )
            if path.exists():
                archive = run_root / "attempts" / attempt_id / "invalid" / relative
                archive.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(archive))
        try:
            value = builder()
            _atomic(path, value)
        except Exception as exc:
            record(
                stage,
                IngestionStageStatus.FAILED,
                message=f"{type(exc).__name__}: {exc}",
            )
            raise
        artifact = _reference(run_root, path, stage.value)
        record(stage, IngestionStageStatus.COMMITTED, artifact)
        maybe_interrupt(stage)
        return value

    input_path = run_root / "input" / f"original{source.suffix.lower()}"
    source_record = latest(IngestionStage.SOURCE_VERIFIED)
    if (
        source_record
        and input_path.is_file()
        and sha256_file(input_path) == request.source_fingerprint.digest
    ):
        record(
            IngestionStage.SOURCE_VERIFIED,
            IngestionStageStatus.REUSED,
            source_record.artifact,
        )
    else:
        if source_record is not None:
            record(
                IngestionStage.SOURCE_VERIFIED,
                IngestionStageStatus.INVALIDATED,
                source_record.artifact,
                "copied source missing or fingerprint-invalid",
            )
        if input_path.exists():
            archive = run_root / "attempts" / attempt_id / "invalid" / input_path.name
            archive.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(input_path), str(archive))
        input_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = input_path.with_name(f"{input_path.name}.partial-{uuid.uuid4().hex}")
        shutil.copyfile(source, temporary)
        if sha256_file(temporary) != request.source_fingerprint.digest:
            raise ValueError("copied source failed fingerprint verification")
        os.replace(temporary, input_path)
        record(
            IngestionStage.SOURCE_VERIFIED,
            IngestionStageStatus.COMMITTED,
            _reference(run_root, input_path, "original_source"),
        )
    maybe_interrupt(IngestionStage.SOURCE_VERIFIED)

    inspection = stage_model(
        IngestionStage.INSPECTION_COMMITTED,
        "state/inspection.json",
        MediaInspectionResult,
        lambda: inspect_media(
            input_path,
            ffprobe=request.ffprobe,
            timeout_seconds=request.policy.qualification.timeout_seconds,
        ),
    )
    selection = stage_model(
        IngestionStage.SELECTION_COMMITTED,
        "state/selection.json",
        StreamSelectionResult,
        lambda: select_streams(inspection, request.policy.selection),
    )
    qualification = stage_model(
        IngestionStage.QUALIFICATION_COMMITTED,
        "state/qualification.json",
        DecodeQualificationResult,
        lambda: FFmpegDecodeQualificationProvider(request.ffmpeg).qualify(
            inspection, selection, request.policy.qualification
        ),
    )
    audio = stage_model(
        IngestionStage.AUDIO_NORMALIZATION_COMMITTED,
        "state/audio-normalization.json",
        AudioNormalizationResult,
        lambda: normalize_audio(
            inspection,
            selection,
            workspace,
            policy=request.policy.audio,
            ffmpeg=request.ffmpeg,
            ffprobe=request.ffprobe,
        ),
        lambda result: validate_audio_result(
            result, ffprobe=request.ffprobe
        ),
    )
    video = stage_model(
        IngestionStage.VIDEO_ACCESS_COMMITTED,
        "state/video-access.json",
        VideoAccessPlan,
        lambda: create_video_access_plan(
            inspection, selection, qualification, request.policy.video
        ),
    )
    timeline = stage_model(
        IngestionStage.TIMELINE_COMMITTED,
        "state/timeline.json",
        SourceTimeline,
        lambda: build_source_timeline(inspection, selection),
    )
    chunks = stage_model(
        IngestionStage.CHUNK_PLAN_COMMITTED,
        "state/chunk-plan.json",
        ProcessingChunkPlan,
        lambda: build_chunk_plan(timeline, request.policy.chunks),
    )

    corpus_path = run_root / "corpus/manifest.json"
    corpus_record = latest(IngestionStage.CORPUS_COMMITTED)
    if (
        corpus_record
        and corpus_path.is_file()
        and sha256_file(corpus_path) == corpus_record.artifact.content_sha256
        and validate_corpus(corpus_path.parent).valid
    ):
        corpus = load_contract(corpus_path.read_bytes(), AudiovisualCorpus)
        if (
            corpus.source_fingerprint != request.source_fingerprint
            or corpus.configuration_hash != request.configuration_hash
        ):
            raise ValueError("committed corpus is incompatible with resume request")
        record(
            IngestionStage.CORPUS_COMMITTED,
            IngestionStageStatus.REUSED,
            corpus_record.artifact,
        )
    else:
        if corpus_record is not None:
            record(
                IngestionStage.CORPUS_COMMITTED,
                IngestionStageStatus.INVALIDATED,
                corpus_record.artifact,
                "corpus missing, modified, incompatible, or integrity-invalid",
            )
        if corpus_path.parent.exists():
            archive = run_root / "attempts" / attempt_id / "invalid" / "corpus"
            archive.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(corpus_path.parent), str(archive))
        corpus = assemble_corpus(
            corpus_path.parent,
            source=input_path,
            inspection=inspection,
            selection=selection,
            qualification=qualification,
            timeline=timeline,
            audio_result=audio,
            video_access=video,
            chunk_plan=chunks,
            configuration_hash=request.configuration_hash,
        )
        record(
            IngestionStage.CORPUS_COMMITTED,
            IngestionStageStatus.COMMITTED,
            _reference(run_root, corpus_path, "audiovisual_corpus"),
        )
    maybe_interrupt(IngestionStage.CORPUS_COMMITTED)

    reports_marker = run_root / "corpus/reports/completion.json"
    reports_record = latest(IngestionStage.REPORTS_COMMITTED)
    if reports_record and reports_marker.is_file() and (
        sha256_file(reports_marker) == reports_record.artifact.content_sha256
    ):
        record(
            IngestionStage.REPORTS_COMMITTED,
            IngestionStageStatus.REUSED,
            reports_record.artifact,
        )
    else:
        if reports_record is not None:
            record(
                IngestionStage.REPORTS_COMMITTED,
                IngestionStageStatus.INVALIDATED,
                reports_record.artifact,
                "completion reports missing, modified, or invalid",
            )
        integrity = validate_corpus(corpus_path.parent)
        normalized = normalized_source_report(corpus_path.parent)
        reports = corpus_path.parent / "reports"
        _atomic(reports / "integrity.json", integrity)
        _atomic(reports / "normalized-source.json", normalized)
        (reports / "integrity.txt").write_text(
            f"Corpus integrity\nValid: {integrity.valid}\n"
            f"Checked artifacts: {integrity.checked_artifacts}\n"
            + "\n".join(integrity.findings)
            + "\n",
            encoding="utf-8",
        )
        (reports / "normalized-source.txt").write_text(
            f"Normalized source\nCorpus: {normalized.corpus_id}\n"
            f"Source duration (us): {normalized.source_duration_microseconds}\n"
            f"Audio duration (us): {normalized.audio_duration_microseconds}\n"
            f"Video strategy: {normalized.video_strategy}\n"
            f"Chunks: {normalized.chunk_count}\n",
            encoding="utf-8",
        )
        _atomic(reports_marker, normalized)
        record(
            IngestionStage.REPORTS_COMMITTED,
            IngestionStageStatus.COMMITTED,
            _reference(run_root, reports_marker, "completion_reports"),
        )
    maybe_interrupt(IngestionStage.REPORTS_COMMITTED)
    complete_ref = _reference(run_root, corpus_path, "audiovisual_corpus")
    record(IngestionStage.COMPLETE, IngestionStageStatus.COMMITTED, complete_ref)
    maybe_interrupt(IngestionStage.COMPLETE)
    manifest = load_contract(
        (run_root / "manifest.json").read_bytes(), IngestionManifest
    )
    assert isinstance(manifest, IngestionManifest)
    return manifest
