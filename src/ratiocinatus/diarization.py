"""Phase 3 diarization orchestration and canonical evidence persistence."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .corpus import load_corpus, validate_corpus
from .diarization_evidence import prepare_diarization_request
from .diarization_normalization import (
    DiarizationNormalizationError,
    canonicalize_diarization,
    validate_diarization_response as _validate_normalized_response,
    validate_diarization_run as _validate_normalized_run,
)
from .diarization_providers import DiarizationProvider
from .kernel import canonical_bytes, load_contract, typed_id
from .phase2_contracts import (
    SpeechActivityClassification,
    SpeechActivityRun,
)
from .phase3_contracts import (
    DiarizationPolicy,
    DiarizationProviderResponse,
    DiarizationReport,
    DiarizationRequest,
    DiarizationRun,
    SpeakerTurnKind,
)
from .speech_activity import validate_activity_run
from .transcript_assembly import validate_transcript_assembly
from .transcript_contracts import TranscriptAssembly


class DiarizationIntegrityError(RuntimeError):
    """Phase 3 evidence failed lineage or content-integrity validation."""


def _atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.partial-{uuid.uuid4().hex}")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def validate_diarization_response(
    response: DiarizationProviderResponse,
    request: DiarizationRequest,
    run_root: Path,
) -> None:
    try:
        _validate_normalized_response(response, request, run_root)
    except DiarizationNormalizationError as exc:
        raise DiarizationIntegrityError(str(exc)) from exc


def _canonicalize(
    request: DiarizationRequest,
    response: DiarizationProviderResponse,
) -> DiarizationRun:
    try:
        return canonicalize_diarization(request, response)
    except DiarizationNormalizationError as exc:
        raise DiarizationIntegrityError(str(exc)) from exc


def validate_diarization_run(run: DiarizationRun) -> None:
    try:
        _validate_normalized_run(run)
    except DiarizationNormalizationError as exc:
        raise DiarizationIntegrityError(str(exc)) from exc

def _report(
    request: DiarizationRequest,
    run: DiarizationRun,
    provider: DiarizationProvider,
) -> DiarizationReport:
    unknown = sum(
        item.turn_kind
        in {
            SpeakerTurnKind.UNCERTAIN_SPEAKER,
            SpeakerTurnKind.UNASSIGNED_SPEECH,
        }
        for item in run.turns
    )
    review_boundaries = sum(item.review_required for item in run.boundaries)
    overlap_duration = sum(
        item.normalized_audio_interval.duration_microseconds
        for item in run.overlaps
    )
    status = (
        "failed"
        if not run.complete
        else (
            "partial"
            if unknown
            else (
                "warning"
                if provider.capabilities.limitations or run.overlaps
                else "complete"
            )
        )
    )
    return DiarizationReport(
        report_id=typed_id("diareport", run.run_id),
        run_id=run.run_id,
        request_id=request.request_id,
        corpus_id=request.corpus_id,
        generated_at=datetime.now(timezone.utc),
        provider=run.provider,
        observation_count=len(run.observations),
        turn_count=len(run.turns),
        boundary_count=len(run.boundaries),
        unknown_turn_count=unknown,
        review_boundary_count=review_boundaries,
        overlap_count=len(run.overlaps),
        overlap_duration_microseconds=overlap_duration,
        measured=(
            f"{len(run.observations)} normalized speaker observations",
            f"{len(run.turns)} provisional speaker turns",
            f"{unknown} unknown or unassigned turns",
            f"{review_boundaries} boundaries requiring review",
            f"{len(run.overlaps)} explicit overlap intervals",
        ),
        provider_claims=(
            f"Speaker evidence supplied by {run.provider.display_name}.",
            "Provider speaker labels are acoustic labels, not identities.",
        ),
        unresolved_limitations=provider.capabilities.limitations,
        status=status,
    )


def report_markdown(report: DiarizationReport) -> str:
    return "\n".join(
        [
            "# Phase 3 diarization report",
            "",
            f"Status: **{report.status.upper()}**",
            "",
            f"Run: `{report.run_id}`",
            "",
            f"- Speaker observations: {report.observation_count}",
            f"- Provisional turns: {report.turn_count}",
            f"- Change boundaries: {report.boundary_count}",
            f"- Unknown or unassigned turns: {report.unknown_turn_count}",
            f"- Boundaries requiring review: {report.review_boundary_count}",
            f"- Explicit overlap intervals: {report.overlap_count}",
            (
                "- Overlap duration (microseconds): "
                f"{report.overlap_duration_microseconds}"
            ),
            "",
            "No acoustic observation, provider label, or provisional turn is "
            "a participant identity.",
            "",
        ]
    )


def diarize_corpus(
    corpus_root: Path,
    activity_run_root: Path,
    destination: Path,
    *,
    provider: DiarizationProvider,
    policy: DiarizationPolicy | None = None,
    speech_interval_ids: tuple[str, ...] | None = None,
    transcript_assembly_root: Path | None = None,
) -> tuple[
    DiarizationRequest,
    DiarizationProviderResponse,
    DiarizationRun,
    DiarizationReport,
    Path,
    bool,
]:
    corpus_root = corpus_root.expanduser().resolve(strict=True)
    activity_run_root = activity_run_root.expanduser().resolve(strict=True)
    destination = destination.expanduser().resolve()
    if destination == corpus_root or corpus_root in destination.parents:
        raise ValueError("Phase 3 output must not modify the Phase 1 corpus")
    integrity = validate_corpus(corpus_root)
    if not integrity.valid:
        raise DiarizationIntegrityError(
            "Phase 1 corpus is invalid: " + "; ".join(integrity.findings)
        )
    loaded = load_corpus(corpus_root)
    activity = load_contract(
        (activity_run_root / "run.json").read_bytes(), SpeechActivityRun
    )
    validate_activity_run(activity)
    transcript = None
    if transcript_assembly_root is not None:
        transcript = load_contract(
            (
                transcript_assembly_root.expanduser().resolve(strict=True)
                / "assembly.json"
            ).read_bytes(),
            TranscriptAssembly,
        )
        validate_transcript_assembly(transcript)
    selected_ids = speech_interval_ids or tuple(
        item.interval_id
        for item in activity.intervals
        if item.classification
        == SpeechActivityClassification.PROBABLE_SPEECH
    )
    selected_stream_id = loaded["selection"].audio.selected_stream_id
    if selected_stream_id is None:
        raise DiarizationIntegrityError(
            "Phase 1 corpus has no selected audio stream"
        )
    request = prepare_diarization_request(
        loaded["corpus"],
        loaded["audio"],
        loaded["timeline"],
        loaded["chunks"],
        activity,
        provider.capabilities.identity,
        datetime.now(timezone.utc),
        selected_audio_stream_id=selected_stream_id,
        speech_interval_ids=selected_ids,
        policy=policy,
        transcript=transcript,
    )
    run_root = destination / "diarization" / request.request_id
    expected_paths = (
        run_root / "request.json",
        run_root / "response.json",
        run_root / "run.json",
        run_root / "report.json",
    )
    existing = tuple(path.exists() for path in expected_paths)
    if any(existing) and not all(existing):
        raise DiarizationIntegrityError(
            "cached diarization run is incomplete"
        )
    if all(existing):
        stored_request = load_contract(
            expected_paths[0].read_bytes(), DiarizationRequest
        )
        response = load_contract(
            expected_paths[1].read_bytes(), DiarizationProviderResponse
        )
        run = load_contract(expected_paths[2].read_bytes(), DiarizationRun)
        report = load_contract(
            expected_paths[3].read_bytes(), DiarizationReport
        )
        expected_request = request.model_copy(
            update={"requested_at": stored_request.requested_at}
        )
        if stored_request != expected_request:
            raise DiarizationIntegrityError(
                "cached diarization request is incompatible"
            )
        validate_diarization_response(response, stored_request, run_root)
        validate_diarization_run(run)
        if (
            run.request_id != stored_request.request_id
            or run.response_id != response.response_id
            or report.run_id != run.run_id
            or report.request_id != stored_request.request_id
            or report.corpus_id != stored_request.corpus_id
        ):
            raise DiarizationIntegrityError(
                "cached diarization report lineage is incompatible"
            )
        return stored_request, response, run, report, run_root, True

    run_root.mkdir(parents=True, exist_ok=True)
    response = provider.diarize(
        request,
        loaded["audio_path"],
        evidence_root=run_root,
    )
    validate_diarization_response(response, request, run_root)
    run = _canonicalize(request, response)
    validate_diarization_run(run)
    report = _report(request, run, provider)
    _atomic(expected_paths[0], canonical_bytes(request))
    _atomic(expected_paths[1], canonical_bytes(response))
    _atomic(expected_paths[2], canonical_bytes(run))
    _atomic(expected_paths[3], canonical_bytes(report))
    _atomic(
        run_root / "report.md", report_markdown(report).encode("utf-8")
    )
    return request, response, run, report, run_root, False
