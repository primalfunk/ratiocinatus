from __future__ import annotations

import json
from pathlib import Path

import pytest

from ratiocinatus.phase4_recovery import (
    Phase4RecoveryTask,
    downstream_stages,
    run_phase4_recovery,
)
from ratiocinatus.phase4_recovery_contracts import (
    Phase4NegativeProof,
    Phase4NegativeProofKind,
    Phase4RecoveryAction,
    Phase4RecoveryRecord,
    Phase4RecoveryStage,
)

from test_phase3_speaker_transcript import NOW


def _proofs() -> tuple[Phase4NegativeProof, ...]:
    return tuple(
        Phase4NegativeProof(
            kind=kind,
            passed=True,
            failure_type="ControlledTypedRefusal",
            message=(
                "Controlled negative fixture produced a typed refusal without "
                "mutating source evidence."
            ),
            typed_refusal=(
                kind != Phase4NegativeProofKind.OPTIONAL_ANALYZER_FAILURE
            ),
            conservative_degradation=(
                kind == Phase4NegativeProofKind.OPTIONAL_ANALYZER_FAILURE
            ),
            source_evidence_preserved=True,
            evidence_references=(f"negative:{kind.value}",),
        )
        for kind in Phase4NegativeProofKind
    )


def test_recovery_quarantines_corruption_resumes_missing_and_reuses_valid(
    tmp_path: Path,
) -> None:
    root = tmp_path / "recovery"
    root.mkdir()
    protected = tmp_path / "protected.json"
    protected.write_text('{"immutable":true}', encoding="utf-8")
    tasks = []
    for stage in Phase4RecoveryStage:
        artifact = root / stage.value
        if stage != Phase4RecoveryStage.CORPUS_EXPORT:
            artifact.mkdir()
            (artifact / "value.json").write_text(
                json.dumps({"stage": stage.value}), encoding="utf-8"
            )
        if stage == Phase4RecoveryStage.QUOTATION:
            (artifact / "value.json").write_text("{broken", encoding="utf-8")

        def validate(path: Path, expected=stage.value):
            payload = json.loads((path / "value.json").read_text("utf-8"))
            if payload["stage"] != expected:
                raise ValueError("stage payload mismatch")

        def rebuild(path=artifact, expected=stage.value):
            path.mkdir(parents=True, exist_ok=True)
            (path / "value.json").write_text(
                json.dumps({"stage": expected}), encoding="utf-8"
            )
            return path

        tasks.append(
            Phase4RecoveryTask(
                stage=stage,
                artifact_root=artifact,
                artifact_id=f"artifact:{stage.value}",
                validate=validate,
                rebuild=rebuild,
            )
        )
    report = run_phase4_recovery(
        tuple(tasks),
        root,
        protected_paths=(("prior-phase", protected),),
        negative_proofs=_proofs(),
        generated_at=NOW,
    )
    actions = {item.stage: item.action for item in report.records}
    assert actions[Phase4RecoveryStage.QUOTATION] == (
        Phase4RecoveryAction.QUARANTINED_AND_REBUILT
    )
    assert actions[Phase4RecoveryStage.CORPUS_EXPORT] == (
        Phase4RecoveryAction.RESUMED_MISSING
    )
    assert actions[Phase4RecoveryStage.UTTERANCE_SEGMENTATION] == (
        Phase4RecoveryAction.REUSED_VALID
    )
    assert report.protected_before == report.protected_after
    assert report.status == "passed"
    assert (root / "invalid").exists() or any(root.rglob("invalid"))


def test_recovery_invalidation_is_transitive_and_downstream_only() -> None:
    affected = downstream_stages(
        (Phase4RecoveryStage.ATTRIBUTED_TRANSCRIPT,)
    )
    assert affected == (
        Phase4RecoveryStage.CONTEXT_WINDOWS,
        Phase4RecoveryStage.CORRECTION_PROPAGATION,
        Phase4RecoveryStage.CORPUS_EXPORT,
    )
    assert Phase4RecoveryStage.QUOTATION not in affected


def test_recovery_report_refuses_an_incomplete_negative_inventory(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="every required negative proof"):
        from ratiocinatus.phase4_recovery_contracts import (
            Phase4RecoveryReport,
            Phase4RecoveryPolicy,
        )

        Phase4RecoveryReport(
            report_id="phase4recovery_" + "0" * 32,
            generated_at=NOW,
            policy=Phase4RecoveryPolicy(),
            records=(
                Phase4RecoveryRecord(
                    stage=Phase4RecoveryStage.INITIAL_ALIGNMENT,
                    artifact_id="controlled",
                    action=Phase4RecoveryAction.REUSED_VALID,
                    optional_analyzer_invoked=False,
                    validated_after_recovery=True,
                ),
            ),
            protected_before=(),
            protected_after=(),
            interruption_boundaries=tuple(Phase4RecoveryStage),
            negative_proofs=_proofs()[:-1],
            findings=(),
            status="failed",
            integrity_sha256="0" * 64,
        )
