"""Phase 2 transcription orchestration, persistence, and reporting."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .corpus import load_corpus, validate_corpus
from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .media import sha256_file
from .phase2_contracts import (
    SpeechActivityClassification,
    SpeechActivityRun,
    TranscriptionPolicy,
    TranscriptionProviderResponse,
    TranscriptionReport,
    TranscriptionRequest,
)
from .speech_activity import validate_activity_run
from .speech_evidence import prepare_transcription_request
from .speech_providers import TranscriptionProvider


class TranscriptionIntegrityError(RuntimeError):
    pass


def _atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.partial-{uuid.uuid4().hex}")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def validate_transcription_response(
    response: TranscriptionProviderResponse,
    request: TranscriptionRequest,
    run_root: Path,
) -> None:
    if response.request_id != request.request_id:
        raise TranscriptionIntegrityError(
            "transcription response belongs to another request"
        )
    if response.provider != request.provider:
        raise TranscriptionIntegrityError(
            "transcription response provider is incompatible"
        )
    expected_hash = canonical_hash(
        {
            "request_id": request.request_id,
            "provider": response.provider.model_dump(mode="json"),
            "observations": [
                item.model_dump(mode="json") for item in response.observations
            ],
        }
    )
    if response.normalized_evidence_sha256 != expected_hash:
        raise TranscriptionIntegrityError(
            "normalized transcription evidence hash does not match observations"
        )
    known = set(request.speech_interval_ids)
    previous_end = 0
    for observation in response.observations:
        if not set(observation.speech_interval_ids).issubset(known):
            raise TranscriptionIntegrityError(
                "transcript observation references unknown speech evidence"
            )
        normalized = observation.normalized_audio_interval
        start = normalized.start_microseconds
        end = start + normalized.duration_microseconds
        if start < previous_end:
            raise TranscriptionIntegrityError(
                "transcript observations overlap or regress"
            )
        if end > request.normalized_audio_duration_microseconds:
            raise TranscriptionIntegrityError(
                "transcript observation exceeds normalized audio"
            )
        if (
            observation.source_interval.start_microseconds
            != start + request.source_mapping_offset_microseconds
        ):
            raise TranscriptionIntegrityError(
                "transcript observation source mapping is invalid"
            )
        previous_end = end
    raw = response.raw_evidence
    if raw.relative_path is not None:
        relative = Path(raw.relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise TranscriptionIntegrityError(
                "raw transcription evidence path is unsafe"
            )
        root = run_root.resolve()
        path = (root / relative).resolve()
        if root not in path.parents:
            raise TranscriptionIntegrityError(
                "raw transcription evidence escapes its run root"
            )
        if (
            not path.is_file()
            or sha256_file(path) != raw.content_sha256
            or path.stat().st_size != raw.byte_size
        ):
            raise TranscriptionIntegrityError(
                "raw transcription evidence fails integrity validation"
            )


def _report(
    request: TranscriptionRequest,
    response: TranscriptionProviderResponse,
    provider: TranscriptionProvider,
) -> TranscriptionReport:
    selected = [
        candidate
        for observation in response.observations
        for candidate in observation.candidates
        if candidate.selected
    ]
    languages = tuple(
        sorted(
            {
                candidate.language
                for candidate in selected
                if candidate.language is not None
            }
        )
    )
    unresolved = sum(
        observation.selected_candidate_id is None
        for observation in response.observations
    )
    findings = (
        (response.failure_message or "transcription provider failed",)
        if not response.complete
        else ()
    )
    status = (
        "failed"
        if not response.complete
        else (
            "partial"
            if unresolved
            else ("warning" if provider.capabilities.limitations else "complete")
        )
    )
    return TranscriptionReport(
        report_id=typed_id("txreport", response.response_id),
        response_id=response.response_id,
        request_id=request.request_id,
        corpus_id=request.corpus_id,
        generated_at=datetime.now(timezone.utc),
        provider=response.provider,
        observation_count=len(response.observations),
        selected_candidate_count=len(selected),
        unresolved_observation_count=unresolved,
        word_observation_count=sum(len(item.words) for item in selected),
        languages=languages,
        configured_policy=request.policy,
        measured=(
            f"{len(response.observations)} provider transcript observations",
            f"{len(selected)} selected fallible candidates",
            f"{sum(len(item.words) for item in selected)} word observations",
            f"{unresolved} observations without selected lexical text",
        ),
        provider_claims=(
            f"Transcript observations supplied by {response.provider.display_name}.",
            "Capability and limitation statements are provider-declared.",
        ),
        inferred_classifications=(
            "Candidate selection records the single available provider result; "
            "it does not establish transcript correctness.",
        ),
        validation_findings=findings,
        unresolved_limitations=provider.capabilities.limitations,
        status=status,
    )


def report_markdown(report: TranscriptionReport) -> str:
    return "\n".join(
        [
            "# Phase 2 transcription-provider report",
            "",
            f"Status: **{report.status.upper()}**",
            "",
            f"Response: `{report.response_id}`",
            "",
            f"- Observations: {report.observation_count}",
            f"- Selected candidates: {report.selected_candidate_count}",
            f"- Unresolved observations: {report.unresolved_observation_count}",
            f"- Word observations: {report.word_observation_count}",
            f"- Languages proposed: {', '.join(report.languages) or 'none'}",
            "",
            "All text remains provider observation evidence. No canonical "
            "transcript segment, word, correction, or speaker identity is "
            "created by this stage.",
            "",
        ]
    )


def transcribe_corpus(
    corpus_root: Path,
    activity_run_root: Path,
    destination: Path,
    *,
    provider: TranscriptionProvider,
    policy: TranscriptionPolicy | None = None,
    speech_interval_ids: tuple[str, ...] | None = None,
) -> tuple[
    TranscriptionRequest,
    TranscriptionProviderResponse,
    TranscriptionReport,
    Path,
    bool,
]:
    corpus_root = corpus_root.expanduser().resolve(strict=True)
    activity_run_root = activity_run_root.expanduser().resolve(strict=True)
    destination = destination.expanduser().resolve()
    if destination == corpus_root or corpus_root in destination.parents:
        raise ValueError("Phase 2 output must not modify the Phase 1 corpus")
    integrity = validate_corpus(corpus_root)
    if not integrity.valid:
        raise TranscriptionIntegrityError(
            "Phase 1 corpus is invalid: " + "; ".join(integrity.findings)
        )
    loaded = load_corpus(corpus_root)
    activity = load_contract(
        (activity_run_root / "run.json").read_bytes(),
        SpeechActivityRun,
    )
    validate_activity_run(activity)
    if activity.request.corpus_id != loaded["corpus"].corpus_id:
        raise TranscriptionIntegrityError(
            "speech activity belongs to another Phase 1 corpus"
        )
    selected_ids = speech_interval_ids or tuple(
        item.interval_id
        for item in activity.intervals
        if item.classification == SpeechActivityClassification.PROBABLE_SPEECH
    )
    request = prepare_transcription_request(
        activity,
        provider.capabilities.identity,
        datetime.now(timezone.utc),
        speech_interval_ids=selected_ids,
        policy=policy,
    )
    run_root = destination / "transcription" / request.request_id
    response_path = run_root / "response.json"
    report_path = run_root / "report.json"
    if response_path.exists() and report_path.exists():
        response = load_contract(
            response_path.read_bytes(), TranscriptionProviderResponse
        )
        report = load_contract(report_path.read_bytes(), TranscriptionReport)
        stored_request = load_contract(
            (run_root / "request.json").read_bytes(), TranscriptionRequest
        )
        expected_request = request.model_copy(
            update={"requested_at": stored_request.requested_at}
        )
        if stored_request != expected_request:
            raise TranscriptionIntegrityError(
                "cached transcription request is incompatible"
            )
        validate_transcription_response(response, stored_request, run_root)
        if (
            report.response_id != response.response_id
            or report.request_id != stored_request.request_id
            or report.corpus_id != stored_request.corpus_id
        ):
            raise TranscriptionIntegrityError(
                "cached transcription report lineage is incompatible"
            )
        return stored_request, response, report, run_root, True

    run_root.mkdir(parents=True, exist_ok=True)
    response = provider.transcribe(
        request,
        loaded["audio_path"],
        evidence_root=run_root,
    )
    validate_transcription_response(response, request, run_root)
    report = _report(request, response, provider)
    _atomic(run_root / "request.json", canonical_bytes(request))
    _atomic(response_path, canonical_bytes(response))
    _atomic(report_path, canonical_bytes(report))
    _atomic(
        run_root / "report.md",
        report_markdown(report).encode("utf-8"),
    )
    return request, response, report, run_root, False
