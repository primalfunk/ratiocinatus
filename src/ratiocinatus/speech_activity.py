"""Phase 2 speech-activity orchestration, persistence, and reporting."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .activity import FFmpegEnergySpeechActivityProvider
from .corpus import load_corpus, validate_corpus
from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase2_contracts import (
    SpeechActivityClassification,
    SpeechActivityReport,
    SpeechActivityRun,
    SpeechActivitySummary,
    SpeechActivityPolicy,
)
from .speech_evidence import prepare_speech_activity_request
from .speech_providers import SpeechActivityProvider


class SpeechActivityIntegrityError(RuntimeError):
    pass


def _atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.partial-{uuid.uuid4().hex}")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _report(
    run: SpeechActivityRun,
    provider: SpeechActivityProvider,
) -> SpeechActivityReport:
    measured = tuple(
        SpeechActivitySummary(
            classification=classification,
            interval_count=sum(
                item.classification == classification
                for item in run.intervals
            ),
            duration_microseconds=sum(
                item.normalized_audio_interval.duration_microseconds
                for item in run.intervals
                if item.classification == classification
            ),
        )
        for classification in SpeechActivityClassification
    )
    coverage = sum(
        item.normalized_audio_interval.duration_microseconds
        for item in run.intervals
    ) == run.request.normalized_audio_duration_microseconds
    findings = () if run.complete and coverage else (
        run.failure_message or "speech activity coverage is incomplete",
    )
    limitations = provider.capabilities.limitations
    status = (
        "failed"
        if not run.complete
        else ("warning" if limitations else "complete")
    )
    return SpeechActivityReport(
        report_id=typed_id("speechreport", run.run_id),
        run_id=run.run_id,
        corpus_id=run.request.corpus_id,
        generated_at=datetime.now(timezone.utc),
        provider=run.provider,
        measured=measured,
        configured_thresholds=(
            ("speech_threshold", run.request.policy.speech_threshold),
            (
                "non_speech_threshold",
                run.request.policy.non_speech_threshold,
            ),
        ),
        provider_claims=(
            f"Activity observations supplied by {run.provider.display_name}.",
            "Capability and limitation statements are provider-declared.",
        ),
        inferred_classifications=(
            "Probable speech, probable non-speech, and uncertain are policy "
            "threshold classifications over the provider-specific speech "
            "presence score; each interval records its score origin.",
        ),
        coverage_complete=coverage,
        duplicate_owned_interval_count=0,
        validation_findings=findings,
        unresolved_limitations=limitations,
        status=status,
    )


def validate_activity_run(run: SpeechActivityRun) -> None:
    if not run.complete:
        raise SpeechActivityIntegrityError(
            run.failure_message or "speech activity run is incomplete"
        )
    expected_hash = canonical_hash(
        {
            "request_id": run.request.request_id,
            "provider": run.provider.model_dump(mode="json"),
            "intervals": [
                item.model_dump(mode="json") for item in run.intervals
            ],
        }
    )
    if run.raw_evidence.content_sha256 != expected_hash:
        raise SpeechActivityIntegrityError(
            "speech activity evidence hash does not match intervals"
        )

def report_markdown(report: SpeechActivityReport) -> str:
    lines = [
        "# Phase 2 speech-activity report",
        "",
        f"Status: **{report.status.upper()}**",
        "",
        f"Run: `{report.run_id}`",
        "",
        "| Classification | Intervals | Duration (µs) |",
        "|---|---:|---:|",
    ]
    for item in report.measured:
        lines.append(
            f"| `{item.classification.value}` | {item.interval_count} | "
            f"{item.duration_microseconds} |"
        )
    lines.extend(
        [
            "",
            f"Coverage complete: `{str(report.coverage_complete).lower()}`",
            "",
            (
                "The provider is an energy-activity baseline and cannot "
                "distinguish speech from music, noise, or non-lexical sound."
                if report.provider.provider_id
                == "local.ffmpeg_energy_activity"
                else "The provider is the pinned local Silero semantic VAD; "
                "its probabilities remain uncalibrated by Ratiocinatus."
            ),
            "",
            "No transcript text or speaker identity is produced.",
            "",
        ]
    )
    return "\n".join(lines)


def detect_corpus_activity(
    corpus_root: Path,
    destination: Path,
    *,
    provider: SpeechActivityProvider | None = None,
    policy: SpeechActivityPolicy | None = None,
) -> tuple[SpeechActivityRun, SpeechActivityReport, Path, bool]:
    corpus_root = corpus_root.expanduser().resolve(strict=True)
    destination = destination.expanduser().resolve()
    if destination == corpus_root or corpus_root in destination.parents:
        raise ValueError("Phase 2 output must not modify the Phase 1 corpus")
    integrity = validate_corpus(corpus_root)
    if not integrity.valid:
        raise SpeechActivityIntegrityError(
            "Phase 1 corpus is invalid: " + "; ".join(integrity.findings)
        )
    loaded = load_corpus(corpus_root)
    provider = provider or FFmpegEnergySpeechActivityProvider()
    request = prepare_speech_activity_request(
        loaded["corpus"],
        loaded["audio"],
        loaded["timeline"],
        loaded["chunks"],
        provider.capabilities.identity,
        datetime.now(timezone.utc),
        policy=policy,
    )
    run_root = destination / "speech_activity" / request.request_id
    run_path = run_root / "run.json"
    report_path = run_root / "report.json"
    if run_path.exists() and report_path.exists():
        run = load_contract(run_path.read_bytes(), SpeechActivityRun)
        report = load_contract(report_path.read_bytes(), SpeechActivityReport)
        assert isinstance(run, SpeechActivityRun)
        assert isinstance(report, SpeechActivityReport)
        validate_activity_run(run)
        if report.run_id != run.run_id or report.corpus_id != run.request.corpus_id:
            raise SpeechActivityIntegrityError("cached report lineage is incompatible")
        if run.request != request.model_copy(
            update={"requested_at": run.request.requested_at}
        ):
            raise SpeechActivityIntegrityError(
                "cached activity request is incompatible"
            )
        return run, report, run_root, True

    run = provider.detect(request, loaded["audio_path"])
    validate_activity_run(run)
    report = _report(run, provider)
    _atomic(run_root / "request.json", canonical_bytes(request))
    _atomic(run_path, canonical_bytes(run))
    _atomic(report_path, canonical_bytes(report))
    _atomic(
        run_root / "report.md",
        report_markdown(report).encode("utf-8"),
    )
    return run, report, run_root, False
