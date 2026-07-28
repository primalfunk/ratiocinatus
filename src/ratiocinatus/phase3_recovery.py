"""Selective Phase 3 cache quarantine, resume, and recovery orchestration."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase3_recovery_contracts import (
    Phase3InvalidationPlan,
    Phase3RecoveryAction,
    Phase3RecoveryFingerprint,
    Phase3RecoveryPolicy,
    Phase3RecoveryRecord,
    Phase3RecoveryReport,
    Phase3RecoveryStage,
)


class Phase3RecoveryError(RuntimeError):
    """Safe selective Phase 3 recovery could not be completed."""


STAGE_ORDER = tuple(Phase3RecoveryStage)

# Direct dependencies are deliberately stage-granular. Transitive invalidation
# is calculated from this graph rather than from a single monolithic cache key.
DIRECT_DEPENDENTS: dict[
    Phase3RecoveryStage, tuple[Phase3RecoveryStage, ...]
] = {
    Phase3RecoveryStage.DIARIZATION_PROVIDER_RESPONSE: (
        Phase3RecoveryStage.DIARIZATION_NORMALIZED_OBSERVATIONS,
    ),
    Phase3RecoveryStage.DIARIZATION_NORMALIZED_OBSERVATIONS: (
        Phase3RecoveryStage.SPEAKER_EMBEDDINGS,
        Phase3RecoveryStage.CLUSTERING,
    ),
    Phase3RecoveryStage.SPEAKER_EMBEDDINGS: (
        Phase3RecoveryStage.CLUSTERING,
        Phase3RecoveryStage.REFERENCE_ENROLLMENTS,
    ),
    Phase3RecoveryStage.CLUSTERING: (
        Phase3RecoveryStage.IDENTITY_HYPOTHESES,
        Phase3RecoveryStage.IDENTITY_BINDINGS,
    ),
    Phase3RecoveryStage.IDENTITY_HYPOTHESES: (
        Phase3RecoveryStage.IDENTITY_VIEWS,
    ),
    Phase3RecoveryStage.REFERENCE_ENROLLMENTS: (
        Phase3RecoveryStage.REFERENCE_COMPARISONS,
    ),
    Phase3RecoveryStage.REFERENCE_COMPARISONS: (
        Phase3RecoveryStage.IDENTITY_HYPOTHESES,
    ),
    Phase3RecoveryStage.IDENTITY_BINDINGS: (
        Phase3RecoveryStage.IDENTITY_VIEWS,
    ),
    Phase3RecoveryStage.IDENTITY_VIEWS: (
        Phase3RecoveryStage.SPEAKER_TRANSCRIPT,
    ),
    Phase3RecoveryStage.SPEAKER_TRANSCRIPT: (
        Phase3RecoveryStage.PARTICIPANT_SUBTITLES,
    ),
    Phase3RecoveryStage.PARTICIPANT_SUBTITLES: (),
}


@dataclass(frozen=True)
class Phase3RecoveryTask:
    """Runtime callbacks for one persisted Phase 3 stage boundary."""

    stage: Phase3RecoveryStage
    artifact_root: Path
    artifact_id: str
    validate: Callable[[Path], None]
    rebuild: Callable[[], Path]
    upstream_artifact_ids: tuple[str, ...] = ()
    provider_invoked_on_rebuild: bool = False


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
    root = root.expanduser().resolve()
    digest = hashlib.sha256()
    if not root.exists():
        digest.update(b"missing")
        return digest.hexdigest()
    if root.is_file():
        digest.update(root.read_bytes())
        return digest.hexdigest()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def fingerprint(
    label: str, path: Path
) -> Phase3RecoveryFingerprint:
    return Phase3RecoveryFingerprint(
        label=label,
        content_sha256=tree_hash(path),
    )


def downstream_stages(
    changed_stages: tuple[Phase3RecoveryStage, ...],
) -> tuple[Phase3RecoveryStage, ...]:
    """Return the deterministic transitive dependents of changed stages."""

    changed = set(changed_stages)
    pending = list(changed_stages)
    affected: set[Phase3RecoveryStage] = set()
    while pending:
        current = pending.pop()
        for dependent in DIRECT_DEPENDENTS[current]:
            if dependent not in changed and dependent not in affected:
                affected.add(dependent)
                pending.append(dependent)
    return tuple(stage for stage in STAGE_ORDER if stage in affected)


def plan_downstream_invalidation(
    changed_stages: tuple[Phase3RecoveryStage, ...],
    *,
    reason: str,
) -> Phase3InvalidationPlan:
    if not changed_stages:
        raise Phase3RecoveryError("at least one changed stage is required")
    if len(changed_stages) != len(set(changed_stages)):
        raise Phase3RecoveryError("changed recovery stages must be unique")
    changed = tuple(stage for stage in STAGE_ORDER if stage in changed_stages)
    invalidated = downstream_stages(changed)
    affected = set(changed) | set(invalidated)
    preserved = tuple(stage for stage in STAGE_ORDER if stage not in affected)
    return Phase3InvalidationPlan(
        changed_stages=changed,
        invalidated_stages=invalidated,
        preserved_stages=preserved,
        reason=reason,
    )


def _ensure_artifact_scope(path: Path, report_root: Path) -> Path:
    resolved = path.expanduser().resolve()
    root = report_root.expanduser().resolve()
    if resolved == root or root not in resolved.parents:
        raise Phase3RecoveryError(
            "Phase 3 recovery artifact must be below the report root"
        )
    return resolved


def _quarantine_directory(
    artifact_root: Path,
    *,
    report_root: Path,
) -> Path:
    artifact_root = _ensure_artifact_scope(artifact_root, report_root)
    if not artifact_root.exists():
        raise Phase3RecoveryError("cannot quarantine a missing artifact")
    invalid = artifact_root.parent / "invalid"
    invalid.mkdir(parents=True, exist_ok=True)
    suffix = tree_hash(artifact_root)[:16]
    target = invalid / f"{artifact_root.name}-{suffix}"
    sequence = 1
    while target.exists():
        sequence += 1
        target = invalid / f"{artifact_root.name}-{suffix}-{sequence}"
    os.replace(artifact_root, target)
    _ensure_artifact_scope(target, report_root)
    return target


def _recover_task(
    task: Phase3RecoveryTask,
    *,
    report_root: Path,
    invalidated_by_upstream: bool,
) -> Phase3RecoveryRecord:
    artifact_root = _ensure_artifact_scope(task.artifact_root, report_root)
    failure: str | None = None
    quarantine: Path | None = None
    if invalidated_by_upstream and artifact_root.exists():
        failure = "upstream lineage changed at a persisted stage boundary"
        quarantine = _quarantine_directory(
            artifact_root, report_root=report_root
        )
        action = Phase3RecoveryAction.INVALIDATED_AND_REBUILT
    elif artifact_root.exists():
        try:
            task.validate(artifact_root)
            return Phase3RecoveryRecord(
                stage=task.stage,
                artifact_id=task.artifact_id,
                action=Phase3RecoveryAction.REUSED_VALID,
                upstream_artifact_ids=task.upstream_artifact_ids,
                provider_invoked=False,
                validated_after_recovery=True,
            )
        except Exception as exc:
            failure = f"{type(exc).__name__}: {exc}"
            quarantine = _quarantine_directory(
                artifact_root, report_root=report_root
            )
            action = Phase3RecoveryAction.QUARANTINED_AND_REBUILT
    else:
        failure = "artifact missing at a persisted stage boundary"
        action = Phase3RecoveryAction.RESUMED_MISSING
    try:
        rebuilt = task.rebuild().expanduser().resolve(strict=True)
        if rebuilt != artifact_root:
            raise Phase3RecoveryError(
                "rebuild returned an unexpected artifact root"
            )
        task.validate(rebuilt)
    except Exception as exc:
        raise Phase3RecoveryError(
            f"{task.stage.value} recovery failed after {failure}: {exc}"
        ) from exc
    relative = (
        quarantine.relative_to(report_root.expanduser().resolve()).as_posix()
        if quarantine is not None
        else None
    )
    return Phase3RecoveryRecord(
        stage=task.stage,
        artifact_id=task.artifact_id,
        action=action,
        detected_failure=failure,
        quarantine_relative_path=relative,
        upstream_artifact_ids=task.upstream_artifact_ids,
        provider_invoked=task.provider_invoked_on_rebuild,
        validated_after_recovery=True,
    )


def recover_phase3_pipeline(
    tasks: tuple[Phase3RecoveryTask, ...],
    *,
    report_root: Path,
) -> tuple[
    tuple[Phase3RecoveryRecord, ...],
    tuple[Phase3InvalidationPlan, ...],
]:
    """Recover declared stages in dependency order without touching valid parents."""

    if not tasks:
        raise Phase3RecoveryError("at least one Phase 3 recovery task is required")
    if len(tasks) != len({task.stage for task in tasks}):
        raise Phase3RecoveryError("recovery tasks must use unique stages")
    roots = tuple(
        _ensure_artifact_scope(task.artifact_root, report_root) for task in tasks
    )
    if len(roots) != len(set(roots)):
        raise Phase3RecoveryError("recovery tasks must use unique artifact roots")
    by_stage = {task.stage: task for task in tasks}
    records: list[Phase3RecoveryRecord] = []
    plans: list[Phase3InvalidationPlan] = []
    forced: set[Phase3RecoveryStage] = set()
    for stage in STAGE_ORDER:
        task = by_stage.get(stage)
        if task is None:
            continue
        invalidated_by_upstream = stage in forced
        record = _recover_task(
            task,
            report_root=report_root,
            invalidated_by_upstream=invalidated_by_upstream,
        )
        records.append(record)
        if (
            record.action != Phase3RecoveryAction.REUSED_VALID
            and not invalidated_by_upstream
        ):
            plan = plan_downstream_invalidation(
                (stage,),
                reason=record.detected_failure
                or "stage evidence changed during recovery",
            )
            plans.append(plan)
            forced.update(plan.invalidated_stages)
    return tuple(records), tuple(plans)


def _seal(report: Phase3RecoveryReport) -> Phase3RecoveryReport:
    return report.model_copy(
        update={
            "integrity_sha256": canonical_hash(
                report.model_copy(update={"integrity_sha256": "0" * 64})
            )
        }
    )


def recovery_markdown(report: Phase3RecoveryReport) -> bytes:
    lines = [
        "# Phase 3 cache, resume, and recovery report",
        "",
        f"Status: **{report.status.upper()}**",
        "",
        "| Stage | Action | Provider invoked | Valid |",
        "|---|---|---|---|",
    ]
    for record in report.records:
        lines.append(
            f"| `{record.stage.value}` | `{record.action.value}` | "
            f"{record.provider_invoked} | {record.validated_after_recovery} |"
        )
    lines.extend(
        [
            "",
            "Invalid stage outputs are preserved under stage-local `invalid/` "
            "directories. Only transitive downstream dependents are rebuilt.",
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def build_recovery_report(
    *,
    records: tuple[Phase3RecoveryRecord, ...],
    invalidation_plans: tuple[Phase3InvalidationPlan, ...],
    protected_before: tuple[Phase3RecoveryFingerprint, ...],
    protected_after: tuple[Phase3RecoveryFingerprint, ...],
    interruption_boundaries: tuple[Phase3RecoveryStage, ...],
    negative_proofs: tuple[tuple[str, bool], ...],
    generated_at: datetime | None = None,
) -> Phase3RecoveryReport:
    stable = protected_before == protected_after
    passed = stable and all(value for _, value in negative_proofs)
    report = Phase3RecoveryReport(
        report_id=typed_id(
            "phase3recovery",
            tuple(record.model_dump(mode="json") for record in records),
            tuple(plan.model_dump(mode="json") for plan in invalidation_plans),
            tuple(item.model_dump(mode="json") for item in protected_before),
            tuple(item.model_dump(mode="json") for item in protected_after),
            tuple(stage.value for stage in interruption_boundaries),
            negative_proofs,
        ),
        generated_at=generated_at or datetime.now(timezone.utc),
        policy=Phase3RecoveryPolicy(),
        records=records,
        invalidation_plans=invalidation_plans,
        protected_before=protected_before,
        protected_after=protected_after,
        interruption_boundaries=interruption_boundaries,
        negative_proofs=negative_proofs,
        findings=(
            "Protected Phase 1 and Phase 2 evidence remained byte-identical."
            if stable
            else "One or more protected upstream artifacts changed.",
            "Recovery validated each Phase 3 stage before reuse.",
            "Invalidation was limited to transitive downstream dependencies.",
        ),
        status="passed" if passed else "failed",
        integrity_sha256="0" * 64,
    )
    return _seal(report)


def persist_recovery_report(
    report: Phase3RecoveryReport,
    destination: Path,
) -> Path:
    root = (
        destination.expanduser().resolve()
        / "phase3-recovery-reports"
        / report.report_id
    )
    _atomic(root / "report.json", canonical_bytes(report))
    _atomic(root / "report.md", recovery_markdown(report))
    validate_recovery_report(report, root=root)
    return root


def validate_recovery_report(
    report: Phase3RecoveryReport,
    *,
    root: Path | None = None,
) -> None:
    if _seal(report).integrity_sha256 != report.integrity_sha256:
        raise Phase3RecoveryError("Phase 3 recovery integrity seal is invalid")
    stable = report.protected_before == report.protected_after
    passed = stable and all(value for _, value in report.negative_proofs)
    if (report.status == "passed") != passed:
        raise Phase3RecoveryError("Phase 3 recovery report status is inconsistent")
    expected_stages = tuple(
        stage for stage in STAGE_ORDER if stage in {r.stage for r in report.records}
    )
    if tuple(record.stage for record in report.records) != expected_stages:
        raise Phase3RecoveryError("Phase 3 recovery records are not topological")
    for plan in report.invalidation_plans:
        expected = plan_downstream_invalidation(
            plan.changed_stages, reason=plan.reason
        )
        if expected != plan:
            raise Phase3RecoveryError(
                "Phase 3 recovery invalidation plan disagrees with dependencies"
            )
    if root is not None:
        root = root.expanduser().resolve()
        if (
            (root / "report.json").read_bytes() != canonical_bytes(report)
            or (root / "report.md").read_bytes() != recovery_markdown(report)
        ):
            raise Phase3RecoveryError(
                "persisted Phase 3 recovery report failed validation"
            )


def load_recovery_report(root: Path) -> Phase3RecoveryReport:
    root = root.expanduser().resolve(strict=True)
    report = load_contract(
        (root / "report.json").read_bytes(), Phase3RecoveryReport
    )
    validate_recovery_report(report, root=root)
    return report
