"""Stage-local Phase 5 cache recovery and negative-proof qualification."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase5_recovery_contracts import (
    Phase5NegativeProof,
    Phase5RecoveryAction,
    Phase5RecoveryFingerprint,
    Phase5RecoveryPolicy,
    Phase5RecoveryRecord,
    Phase5RecoveryReport,
    Phase5RecoveryStage,
)


class Phase5RecoveryError(RuntimeError):
    """Recovery could not safely validate or rebuild a stage artifact."""


STAGE_ORDER = tuple(Phase5RecoveryStage)
DIRECT_DEPENDENTS = {
    Phase5RecoveryStage.DETERMINISTIC_CLASSIFICATION: (
        Phase5RecoveryStage.EVIDENCE_SPAN_NORMALIZATION,
    ),
    Phase5RecoveryStage.PROVIDER_ANALYSIS: (
        Phase5RecoveryStage.EVIDENCE_SPAN_NORMALIZATION,
    ),
    Phase5RecoveryStage.EVIDENCE_SPAN_NORMALIZATION: (
        Phase5RecoveryStage.CANDIDATE_CONSOLIDATION,
    ),
    Phase5RecoveryStage.CANDIDATE_CONSOLIDATION: (
        Phase5RecoveryStage.QUESTION_CONSTRUCTION,
        Phase5RecoveryStage.OBJECTION_REBUTTAL_LINKING,
        Phase5RecoveryStage.DEFINITION_EXAMPLE,
        Phase5RecoveryStage.PROCEDURAL_STATE,
        Phase5RecoveryStage.REVIEW_ASSEMBLY,
        Phase5RecoveryStage.CORRECTION_PROPAGATION,
    ),
    Phase5RecoveryStage.QUESTION_CONSTRUCTION: (
        Phase5RecoveryStage.ANSWER_LINKING,
    ),
    Phase5RecoveryStage.ANSWER_LINKING: (
        Phase5RecoveryStage.CONTROLLED_EVALUATION,
        Phase5RecoveryStage.CORPUS_EXPORT,
    ),
    Phase5RecoveryStage.OBJECTION_REBUTTAL_LINKING: (
        Phase5RecoveryStage.CONCESSION_QUALIFICATION,
    ),
    Phase5RecoveryStage.CONCESSION_QUALIFICATION: (
        Phase5RecoveryStage.CONTROLLED_EVALUATION,
        Phase5RecoveryStage.CORPUS_EXPORT,
    ),
    Phase5RecoveryStage.DEFINITION_EXAMPLE: (
        Phase5RecoveryStage.CONTROLLED_EVALUATION,
        Phase5RecoveryStage.CORPUS_EXPORT,
    ),
    Phase5RecoveryStage.PROCEDURAL_STATE: (
        Phase5RecoveryStage.CONTROLLED_EVALUATION,
        Phase5RecoveryStage.CORPUS_EXPORT,
    ),
    Phase5RecoveryStage.REVIEW_ASSEMBLY: (
        Phase5RecoveryStage.CONTROLLED_EVALUATION,
        Phase5RecoveryStage.CORPUS_EXPORT,
    ),
    Phase5RecoveryStage.CORRECTION_PROPAGATION: (
        Phase5RecoveryStage.CONTROLLED_EVALUATION,
        Phase5RecoveryStage.CORPUS_EXPORT,
    ),
    Phase5RecoveryStage.CONTROLLED_EVALUATION: (
        Phase5RecoveryStage.CORPUS_EXPORT,
    ),
    Phase5RecoveryStage.CORPUS_EXPORT: (),
}


@dataclass(frozen=True)
class Phase5RecoveryTask:
    stage: Phase5RecoveryStage
    artifact_root: Path
    artifact_id: str
    validate: Callable[[Path], None]
    rebuild: Callable[[], Path]
    upstream_artifact_ids: tuple[str, ...] = ()
    provider_invoked_on_rebuild: bool = False


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


def fingerprint(label: str, path: Path) -> Phase5RecoveryFingerprint:
    return Phase5RecoveryFingerprint(
        label=label, content_sha256=tree_hash(path)
    )


def downstream_stages(changed):
    pending = list(changed)
    result = set()
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
        raise Phase5RecoveryError(
            "recovery artifacts must remain below the recovery root"
        )
    return value


def _quarantine(path: Path, root: Path) -> Path:
    path = _scoped(path, root)
    if not path.exists():
        raise Phase5RecoveryError("cannot quarantine a missing artifact")
    invalid = path.parent / "invalid"
    invalid.mkdir(parents=True, exist_ok=True)
    target = invalid / f"{path.name}-{tree_hash(path)[:16]}"
    sequence = 1
    while target.exists():
        sequence += 1
        target = invalid / f"{path.name}-{tree_hash(path)[:16]}-{sequence}"
    os.replace(path, target)
    return _scoped(target, root)


def _recover(task, root, invalidated):
    artifact = _scoped(task.artifact_root, root)
    failure = None
    quarantine = None
    if invalidated and artifact.exists():
        failure = "upstream lineage changed"
        quarantine = _quarantine(artifact, root)
        action = Phase5RecoveryAction.INVALIDATED_AND_REBUILT
    elif artifact.exists():
        try:
            task.validate(artifact)
            return Phase5RecoveryRecord(
                stage=task.stage,
                artifact_id=task.artifact_id,
                action=Phase5RecoveryAction.REUSED_VALID,
                upstream_artifact_ids=task.upstream_artifact_ids,
                provider_invoked=False,
            )
        except Exception as exc:
            failure = f"{type(exc).__name__}: {exc}"
            quarantine = _quarantine(artifact, root)
            action = Phase5RecoveryAction.QUARANTINED_AND_REBUILT
    else:
        failure = "artifact missing at persisted stage boundary"
        action = Phase5RecoveryAction.RESUMED_MISSING
    try:
        rebuilt = task.rebuild().expanduser().resolve(strict=True)
        if rebuilt != artifact:
            raise Phase5RecoveryError("rebuild returned unexpected path")
        task.validate(rebuilt)
    except Exception as exc:
        raise Phase5RecoveryError(
            f"{task.stage.value} recovery failed after {failure}: {exc}"
        ) from exc
    return Phase5RecoveryRecord(
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
        provider_invoked=task.provider_invoked_on_rebuild,
    )


def _seal(report):
    return report.model_copy(
        update={
            "integrity_sha256": canonical_hash(
                report.model_copy(update={"integrity_sha256": "0" * 64})
            )
        }
    )


def run_phase5_recovery(
    tasks,
    recovery_root,
    *,
    changed_stages=(),
    protected_paths=(),
    negative_proofs: tuple[Phase5NegativeProof, ...],
    policy=None,
    generated_at,
):
    """Reuse, resume, or quarantine/rebuild every persisted Phase 5 stage."""
    if {item.stage for item in tasks} != set(Phase5RecoveryStage):
        raise Phase5RecoveryError("recovery requires exactly every stage task")
    if len(changed_stages) != len(set(changed_stages)):
        raise Phase5RecoveryError("changed stages must be unique")
    recovery_root = recovery_root.expanduser().resolve(strict=True)
    before = tuple(fingerprint(label, path) for label, path in protected_paths)
    invalidated = set(downstream_stages(changed_stages))
    records = tuple(
        _recover(
            next(value for value in tasks if value.stage == stage),
            recovery_root,
            stage in invalidated,
        )
        for stage in STAGE_ORDER
    )
    after = tuple(fingerprint(label, path) for label, path in protected_paths)
    findings = []
    if before != after:
        findings.append("Protected Phase 4 or source evidence changed.")
    if not all(item.passed for item in negative_proofs):
        findings.append("One or more required negative proofs failed.")
    status = (
        "passed"
        if before == after
        and all(item.passed for item in negative_proofs)
        else "failed"
    )
    report = Phase5RecoveryReport(
        report_id=typed_id(
            "phase5recovery",
            tuple(item.model_dump(mode="json") for item in records),
            tuple(item.model_dump(mode="json") for item in negative_proofs),
            tuple(item.model_dump(mode="json") for item in before),
            tuple(item.model_dump(mode="json") for item in after),
        ),
        generated_at=generated_at,
        policy=policy or Phase5RecoveryPolicy(),
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


def persist_phase5_recovery(report, destination):
    expected = _seal(
        report.model_copy(update={"integrity_sha256": "0" * 64})
    )
    if expected != report:
        raise Phase5RecoveryError("recovery report integrity is invalid")
    path = destination.expanduser().resolve() / "recovery-report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        stored = load_contract(path.read_bytes(), Phase5RecoveryReport)
        if stored != report:
            raise Phase5RecoveryError("persisted recovery report conflicts")
        return path
    path.write_bytes(canonical_bytes(report))
    return path


def load_phase5_recovery(path: Path):
    report = load_contract(
        path.expanduser().resolve(strict=True).read_bytes(),
        Phase5RecoveryReport,
    )
    expected = _seal(
        report.model_copy(update={"integrity_sha256": "0" * 64})
    )
    if expected != report:
        raise Phase5RecoveryError("recovery report integrity is invalid")
    return report
