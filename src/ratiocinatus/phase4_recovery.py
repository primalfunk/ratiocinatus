"""Safe stage-local Phase 4 cache recovery and negative-proof evidence."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase4_recovery_contracts import (
    Phase4NegativeProof,
    Phase4RecoveryAction,
    Phase4RecoveryFingerprint,
    Phase4RecoveryPolicy,
    Phase4RecoveryRecord,
    Phase4RecoveryReport,
    Phase4RecoveryStage,
)


class Phase4RecoveryError(RuntimeError):
    """Safe Phase 4 stage-local recovery could not be completed."""


STAGE_ORDER = tuple(Phase4RecoveryStage)
DIRECT_DEPENDENTS = {
    Phase4RecoveryStage.INITIAL_ALIGNMENT: (
        Phase4RecoveryStage.UTTERANCE_SEGMENTATION,
    ),
    Phase4RecoveryStage.UTTERANCE_SEGMENTATION: (
        Phase4RecoveryStage.COMPLETENESS_ANALYSIS,
        Phase4RecoveryStage.TEMPORAL_RELATIONS,
        Phase4RecoveryStage.TURN_REPAIR,
        Phase4RecoveryStage.QUOTATION,
    ),
    Phase4RecoveryStage.COMPLETENESS_ANALYSIS: (
        Phase4RecoveryStage.TEMPORAL_RELATIONS,
        Phase4RecoveryStage.ATTRIBUTED_TRANSCRIPT,
    ),
    Phase4RecoveryStage.TEMPORAL_RELATIONS: (
        Phase4RecoveryStage.TURN_REPAIR,
        Phase4RecoveryStage.ATTRIBUTED_TRANSCRIPT,
    ),
    Phase4RecoveryStage.TURN_REPAIR: (
        Phase4RecoveryStage.ATTRIBUTED_TRANSCRIPT,
    ),
    Phase4RecoveryStage.QUOTATION: (
        Phase4RecoveryStage.ATTRIBUTED_TRANSCRIPT,
    ),
    Phase4RecoveryStage.ATTRIBUTED_TRANSCRIPT: (
        Phase4RecoveryStage.CONTEXT_WINDOWS,
    ),
    Phase4RecoveryStage.CONTEXT_WINDOWS: (
        Phase4RecoveryStage.CORRECTION_PROPAGATION,
        Phase4RecoveryStage.CORPUS_EXPORT,
    ),
    Phase4RecoveryStage.CORRECTION_PROPAGATION: (
        Phase4RecoveryStage.CORPUS_EXPORT,
    ),
    Phase4RecoveryStage.CORPUS_EXPORT: (),
}


@dataclass(frozen=True)
class Phase4RecoveryTask:
    stage: Phase4RecoveryStage
    artifact_root: Path
    artifact_id: str
    validate: Callable[[Path], None]
    rebuild: Callable[[], Path]
    upstream_artifact_ids: tuple[str, ...] = ()
    optional_analyzer_invoked_on_rebuild: bool = False


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


def fingerprint(label: str, path: Path) -> Phase4RecoveryFingerprint:
    return Phase4RecoveryFingerprint(
        label=label, content_sha256=tree_hash(path)
    )


def downstream_stages(
    changed: tuple[Phase4RecoveryStage, ...],
) -> tuple[Phase4RecoveryStage, ...]:
    pending = list(changed)
    result: set[Phase4RecoveryStage] = set()
    changed_set = set(changed)
    while pending:
        current = pending.pop()
        for item in DIRECT_DEPENDENTS[current]:
            if item not in changed_set and item not in result:
                result.add(item)
                pending.append(item)
    return tuple(item for item in STAGE_ORDER if item in result)


def _scoped(path: Path, root: Path) -> Path:
    value = path.expanduser().resolve()
    base = root.expanduser().resolve()
    if value == base or base not in value.parents:
        raise Phase4RecoveryError(
            "recovery artifacts must remain below the recovery root"
        )
    return value


def _quarantine(path: Path, root: Path) -> Path:
    path = _scoped(path, root)
    if not path.exists():
        raise Phase4RecoveryError("cannot quarantine a missing artifact")
    invalid = path.parent / "invalid"
    invalid.mkdir(parents=True, exist_ok=True)
    target = invalid / f"{path.name}-{tree_hash(path)[:16]}"
    sequence = 1
    while target.exists():
        sequence += 1
        target = invalid / f"{path.name}-{tree_hash(path)[:16]}-{sequence}"
    os.replace(path, target)
    return _scoped(target, root)


def _recover(
    task: Phase4RecoveryTask,
    root: Path,
    invalidated: bool,
) -> Phase4RecoveryRecord:
    artifact = _scoped(task.artifact_root, root)
    failure = None
    quarantine = None
    if invalidated and artifact.exists():
        failure = "upstream lineage changed"
        quarantine = _quarantine(artifact, root)
        action = Phase4RecoveryAction.INVALIDATED_AND_REBUILT
    elif artifact.exists():
        try:
            task.validate(artifact)
            return Phase4RecoveryRecord(
                stage=task.stage,
                artifact_id=task.artifact_id,
                action=Phase4RecoveryAction.REUSED_VALID,
                upstream_artifact_ids=task.upstream_artifact_ids,
                optional_analyzer_invoked=False,
                validated_after_recovery=True,
            )
        except Exception as exc:
            failure = f"{type(exc).__name__}: {exc}"
            quarantine = _quarantine(artifact, root)
            action = Phase4RecoveryAction.QUARANTINED_AND_REBUILT
    else:
        failure = "artifact missing at persisted stage boundary"
        action = Phase4RecoveryAction.RESUMED_MISSING
    try:
        rebuilt = task.rebuild().expanduser().resolve(strict=True)
        if rebuilt != artifact:
            raise Phase4RecoveryError("rebuild returned unexpected path")
        task.validate(rebuilt)
    except Exception as exc:
        raise Phase4RecoveryError(
            f"{task.stage.value} recovery failed after {failure}: {exc}"
        ) from exc
    return Phase4RecoveryRecord(
        stage=task.stage,
        artifact_id=task.artifact_id,
        action=action,
        detected_failure=failure,
        quarantine_relative_path=(
            quarantine.relative_to(root.expanduser().resolve()).as_posix()
            if quarantine is not None
            else None
        ),
        upstream_artifact_ids=task.upstream_artifact_ids,
        optional_analyzer_invoked=(
            task.optional_analyzer_invoked_on_rebuild
        ),
        validated_after_recovery=True,
    )


def _seal(report: Phase4RecoveryReport) -> Phase4RecoveryReport:
    return report.model_copy(
        update={
            "integrity_sha256": canonical_hash(
                report.model_copy(update={"integrity_sha256": "0" * 64})
            )
        }
    )


def run_phase4_recovery(
    tasks: tuple[Phase4RecoveryTask, ...],
    recovery_root: Path,
    *,
    changed_stages: tuple[Phase4RecoveryStage, ...] = (),
    protected_paths: tuple[tuple[str, Path], ...] = (),
    negative_proofs: tuple[Phase4NegativeProof, ...],
    policy: Phase4RecoveryPolicy | None = None,
    generated_at: datetime,
) -> Phase4RecoveryReport:
    """Reuse, resume, or quarantine/rebuild each persisted Phase 4 stage."""
    if {item.stage for item in tasks} != set(Phase4RecoveryStage):
        raise Phase4RecoveryError("recovery requires exactly every stage task")
    if len(changed_stages) != len(set(changed_stages)):
        raise Phase4RecoveryError("changed stages must be unique")
    recovery_root = recovery_root.expanduser().resolve(strict=True)
    before = tuple(
        fingerprint(label, path) for label, path in protected_paths
    )
    invalidated = set(downstream_stages(changed_stages))
    records = tuple(
        _recover(
            next(value for value in tasks if value.stage == stage),
            recovery_root,
            stage in invalidated,
        )
        for stage in STAGE_ORDER
    )
    after = tuple(
        fingerprint(label, path) for label, path in protected_paths
    )
    findings = []
    if before != after:
        findings.append("Protected source or prior-phase evidence changed.")
    if not all(item.passed for item in negative_proofs):
        findings.append("One or more required negative proofs failed.")
    status = (
        "passed"
        if before == after
        and all(item.passed for item in negative_proofs)
        and set(item.stage for item in records) == set(Phase4RecoveryStage)
        else "failed"
    )
    report = Phase4RecoveryReport(
        report_id=typed_id(
            "phase4recovery",
            tuple(item.model_dump(mode="json") for item in records),
            tuple(item.model_dump(mode="json") for item in negative_proofs),
            tuple(item.model_dump(mode="json") for item in before),
            tuple(item.model_dump(mode="json") for item in after),
        ),
        generated_at=generated_at,
        policy=policy or Phase4RecoveryPolicy(),
        records=records,
        protected_before=before,
        protected_after=after,
        interruption_boundaries=STAGE_ORDER,
        negative_proofs=negative_proofs,
        findings=tuple(findings),
        status=status,
        integrity_sha256="0" * 64,
    )
    return _seal(report)


def persist_phase4_recovery(
    report: Phase4RecoveryReport, destination: Path
) -> Path:
    expected = _seal(
        report.model_copy(update={"integrity_sha256": "0" * 64})
    )
    if expected != report:
        raise Phase4RecoveryError("recovery report integrity is invalid")
    path = destination.expanduser().resolve() / "recovery-report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        stored = load_contract(path.read_bytes(), Phase4RecoveryReport)
        if stored != report:
            raise Phase4RecoveryError("persisted recovery report conflicts")
        return path
    path.write_bytes(canonical_bytes(report))
    return path
