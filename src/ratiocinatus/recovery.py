"""Selective Phase 2 quarantine, resume, and recovery utilities."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase2_contracts import (
    TranscriptionProviderResponse,
    TranscriptionReport,
    TranscriptionRequest,
)
from .recovery_contracts import (
    Phase2RecoveryPolicy,
    Phase2RecoveryRecord,
    Phase2RecoveryReport,
    Phase2RecoveryStage,
    RecoveryAction,
    RecoveryArtifactFingerprint,
)
from .speech_providers import TranscriptionProvider
from .transcription import (
    TranscriptionIntegrityError,
    _report,
    report_markdown,
    validate_transcription_response,
)


class Phase2RecoveryError(RuntimeError):
    """Raised when safe, selective recovery cannot be completed."""


def _atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def tree_hash(root: Path) -> str:
    root = root.resolve()
    digest = hashlib.sha256()
    if not root.exists():
        digest.update(b"missing")
        return digest.hexdigest()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def fingerprint(label: str, path: Path) -> RecoveryArtifactFingerprint:
    if path.is_dir():
        value = tree_hash(path)
    else:
        value = hashlib.sha256(path.read_bytes()).hexdigest()
    return RecoveryArtifactFingerprint(label=label, content_sha256=value)


def _quarantine_directory(
    artifact_root: Path,
    *,
    report_root: Path,
) -> Path:
    artifact_root = artifact_root.resolve(strict=True)
    parent = artifact_root.parent.resolve()
    if parent not in artifact_root.parents:
        raise Phase2RecoveryError("artifact root has an invalid parent")
    invalid = parent / "invalid"
    invalid.mkdir(parents=True, exist_ok=True)
    suffix = tree_hash(artifact_root)[:16]
    target = invalid / f"{artifact_root.name}-{suffix}"
    sequence = 1
    while target.exists():
        sequence += 1
        target = invalid / f"{artifact_root.name}-{suffix}-{sequence}"
    os.replace(artifact_root, target)
    try:
        target.relative_to(report_root.resolve())
    except ValueError as exc:
        raise Phase2RecoveryError(
            "quarantine target is outside the recovery report root"
        ) from exc
    return target


def recover_artifact(
    *,
    stage: Phase2RecoveryStage,
    artifact_root: Path,
    report_root: Path,
    artifact_id: str,
    validate: Callable[[Path], None],
    rebuild: Callable[[], Path],
    upstream_artifact_ids: tuple[str, ...] = (),
    provider_invoked_on_rebuild: bool = False,
) -> tuple[Phase2RecoveryRecord, Path]:
    """Reuse a valid stage or quarantine and rebuild only that stage."""

    artifact_root = artifact_root.resolve()
    failure: str | None = None
    if artifact_root.exists():
        try:
            validate(artifact_root)
            return (
                Phase2RecoveryRecord(
                    stage=stage,
                    artifact_id=artifact_id,
                    action=RecoveryAction.REUSED_VALID,
                    upstream_artifact_ids=upstream_artifact_ids,
                    provider_invoked=False,
                    validated_after_recovery=True,
                ),
                artifact_root,
            )
        except Exception as exc:
            failure = f"{type(exc).__name__}: {exc}"
            quarantine = _quarantine_directory(
                artifact_root, report_root=report_root
            )
            action = RecoveryAction.QUARANTINED_AND_REBUILT
    else:
        quarantine = None
        failure = "artifact missing at a persisted stage boundary"
        action = RecoveryAction.RESUMED_MISSING
    try:
        rebuilt = rebuild().resolve(strict=True)
        if rebuilt != artifact_root:
            raise Phase2RecoveryError(
                "rebuild returned an unexpected artifact root"
            )
        validate(rebuilt)
    except Exception as exc:
        raise Phase2RecoveryError(
            f"{stage.value} recovery failed after {failure}: {exc}"
        ) from exc
    relative = (
        quarantine.relative_to(report_root.resolve()).as_posix()
        if quarantine is not None
        else None
    )
    return (
        Phase2RecoveryRecord(
            stage=stage,
            artifact_id=artifact_id,
            action=action,
            detected_failure=failure,
            quarantine_relative_path=relative,
            upstream_artifact_ids=upstream_artifact_ids,
            provider_invoked=provider_invoked_on_rebuild,
            validated_after_recovery=True,
        ),
        artifact_root,
    )


def _validate_transcription_report(
    report: TranscriptionReport,
    *,
    request: TranscriptionRequest,
    response: TranscriptionProviderResponse,
    provider: TranscriptionProvider,
) -> None:
    if (
        report.response_id != response.response_id
        or report.request_id != request.request_id
        or report.corpus_id != request.corpus_id
    ):
        raise TranscriptionIntegrityError(
            "transcription report lineage is incompatible"
        )
    expected = _report(request, response, provider).model_copy(
        update={"generated_at": report.generated_at}
    )
    if report != expected:
        raise TranscriptionIntegrityError(
            "transcription report metrics or provider claims disagree"
        )


def repair_transcription_report(
    run_root: Path,
    provider: TranscriptionProvider,
    *,
    report_root: Path,
) -> tuple[TranscriptionReport, Phase2RecoveryRecord]:
    """Repair report metadata from valid evidence without retranscription."""

    run_root = run_root.resolve(strict=True)
    request = load_contract(
        (run_root / "request.json").read_bytes(), TranscriptionRequest
    )
    response = load_contract(
        (run_root / "response.json").read_bytes(),
        TranscriptionProviderResponse,
    )
    if provider.capabilities.identity != request.provider:
        raise Phase2RecoveryError(
            "recovery provider identity differs from transcription request"
        )
    validate_transcription_response(response, request, run_root)
    report_path = run_root / "report.json"
    markdown_path = run_root / "report.md"
    try:
        report = load_contract(report_path.read_bytes(), TranscriptionReport)
        _validate_transcription_report(
            report,
            request=request,
            response=response,
            provider=provider,
        )
        if markdown_path.read_bytes() != report_markdown(report).encode(
            "utf-8"
        ):
            raise TranscriptionIntegrityError(
                "transcription human report differs"
            )
        return report, Phase2RecoveryRecord(
            stage=Phase2RecoveryStage.TRANSCRIPTION_REPORT,
            artifact_id=report.report_id,
            action=RecoveryAction.REUSED_VALID,
            upstream_artifact_ids=(response.response_id,),
            provider_invoked=False,
            validated_after_recovery=True,
        )
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
    invalid = run_root / "invalid"
    invalid.mkdir(parents=True, exist_ok=True)
    content = hashlib.sha256()
    for path in (report_path, markdown_path):
        if path.exists():
            content.update(path.name.encode("utf-8"))
            content.update(path.read_bytes())
    target = invalid / f"report-{content.hexdigest()[:16]}"
    sequence = 1
    while target.exists():
        sequence += 1
        target = invalid / f"report-{content.hexdigest()[:16]}-{sequence}"
    target.mkdir()
    for path in (report_path, markdown_path):
        if path.exists():
            os.replace(path, target / path.name)
    repaired = _report(request, response, provider)
    _atomic(report_path, canonical_bytes(repaired))
    _atomic(
        markdown_path, report_markdown(repaired).encode("utf-8")
    )
    _validate_transcription_report(
        repaired,
        request=request,
        response=response,
        provider=provider,
    )
    try:
        relative = target.relative_to(report_root.resolve()).as_posix()
    except ValueError as exc:
        raise Phase2RecoveryError(
            "transcription report quarantine is outside report root"
        ) from exc
    return repaired, Phase2RecoveryRecord(
        stage=Phase2RecoveryStage.TRANSCRIPTION_REPORT,
        artifact_id=repaired.report_id,
        action=RecoveryAction.REPAIRED_WITHOUT_PROVIDER,
        detected_failure=failure,
        quarantine_relative_path=relative,
        upstream_artifact_ids=(response.response_id,),
        provider_invoked=False,
        validated_after_recovery=True,
    )


def _seal(report: Phase2RecoveryReport) -> Phase2RecoveryReport:
    return report.model_copy(
        update={
            "integrity_sha256": canonical_hash(
                report.model_copy(update={"integrity_sha256": "0" * 64})
            )
        }
    )


def recovery_markdown(report: Phase2RecoveryReport) -> bytes:
    lines = [
        "# Phase 2 cache and recovery report",
        "",
        f"Status: **{report.status.upper()}**",
        "",
        "| Stage | Action | Provider invoked | Valid |",
        "|---|---|---|---|",
    ]
    for item in report.records:
        lines.append(
            f"| `{item.stage.value}` | `{item.action.value}` | "
            f"{item.provider_invoked} | {item.validated_after_recovery} |"
        )
    lines.extend(
        [
            "",
            "Corrupt stage outputs are preserved under their stage-local "
            "`invalid/` directory. Validated upstream evidence is not moved.",
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def build_recovery_report(
    *,
    records: tuple[Phase2RecoveryRecord, ...],
    protected_before: tuple[RecoveryArtifactFingerprint, ...],
    protected_after: tuple[RecoveryArtifactFingerprint, ...],
    interruption_boundaries: tuple[Phase2RecoveryStage, ...],
    negative_proofs: tuple[tuple[str, bool], ...],
    generated_at: datetime | None = None,
) -> Phase2RecoveryReport:
    stable = protected_before == protected_after
    passed = (
        stable
        and all(item.validated_after_recovery for item in records)
        and all(value for _, value in negative_proofs)
    )
    report = Phase2RecoveryReport(
        report_id=typed_id(
            "phase2recovery",
            tuple(item.model_dump(mode="json") for item in records),
            tuple(item.model_dump(mode="json") for item in protected_before),
            tuple(item.model_dump(mode="json") for item in protected_after),
            tuple(item.value for item in interruption_boundaries),
            negative_proofs,
        ),
        generated_at=generated_at or datetime.now(timezone.utc),
        policy=Phase2RecoveryPolicy(),
        records=records,
        protected_before=protected_before,
        protected_after=protected_after,
        interruption_boundaries=interruption_boundaries,
        negative_proofs=negative_proofs,
        findings=(
            "Protected upstream evidence remained byte-identical."
            if stable
            else "One or more protected upstream artifacts changed.",
            "Recovery scope is stage-local and quarantines invalid artifacts.",
        ),
        status="passed" if passed else "failed",
        integrity_sha256="0" * 64,
    )
    return _seal(report)


def persist_recovery_report(
    report: Phase2RecoveryReport,
    destination: Path,
) -> Path:
    destination = destination.resolve()
    root = destination / "recovery-reports" / report.report_id
    _atomic(root / "report.json", canonical_bytes(report))
    _atomic(root / "report.md", recovery_markdown(report))
    validate_recovery_report(report, root=root)
    return root


def validate_recovery_report(
    report: Phase2RecoveryReport,
    *,
    root: Path | None = None,
) -> None:
    if _seal(report).integrity_sha256 != report.integrity_sha256:
        raise Phase2RecoveryError("recovery report integrity seal is invalid")
    if report.status == "passed" and (
        report.protected_before != report.protected_after
        or not all(
            item.validated_after_recovery for item in report.records
        )
        or not all(value for _, value in report.negative_proofs)
    ):
        raise Phase2RecoveryError("recovery report status is inconsistent")
    if root is not None:
        root = root.resolve()
        if (
            (root / "report.json").read_bytes() != canonical_bytes(report)
            or (root / "report.md").read_bytes()
            != recovery_markdown(report)
        ):
            raise Phase2RecoveryError(
                "persisted recovery report failed validation"
            )
