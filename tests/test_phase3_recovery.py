from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from ratiocinatus.cli import main
from ratiocinatus.phase3_recovery import (
    Phase3RecoveryError,
    Phase3RecoveryTask,
    build_recovery_report,
    fingerprint,
    persist_recovery_report,
    plan_downstream_invalidation,
    recover_phase3_pipeline,
    validate_recovery_report,
)
from ratiocinatus.phase3_recovery_contracts import (
    PHASE3_RECOVERY_CONTRACT_MODELS,
    Phase3RecoveryAction,
    Phase3RecoveryStage,
)

NOW = datetime(2000, 1, 1, tzinfo=timezone.utc)


def test_phase3_recovery_contract_schemas_are_closed() -> None:
    for model in PHASE3_RECOVERY_CONTRACT_MODELS:
        schema = model.model_json_schema()
        assert schema["title"] == model.__name__
        assert schema.get("additionalProperties") is False


def test_invalidation_is_transitive_but_preserves_unrelated_evidence() -> None:
    name_change = plan_downstream_invalidation(
        (Phase3RecoveryStage.IDENTITY_BINDINGS,),
        reason="participant display name changed",
    )
    assert name_change.invalidated_stages == (
        Phase3RecoveryStage.IDENTITY_VIEWS,
        Phase3RecoveryStage.SPEAKER_TRANSCRIPT,
        Phase3RecoveryStage.PARTICIPANT_SUBTITLES,
    )
    assert Phase3RecoveryStage.DIARIZATION_PROVIDER_RESPONSE in (
        name_change.preserved_stages
    )
    assert Phase3RecoveryStage.SPEAKER_EMBEDDINGS in name_change.preserved_stages
    assert Phase3RecoveryStage.CLUSTERING in name_change.preserved_stages

    embedding_change = plan_downstream_invalidation(
        (Phase3RecoveryStage.SPEAKER_EMBEDDINGS,),
        reason="embedding model fingerprint changed",
    )
    assert Phase3RecoveryStage.REFERENCE_ENROLLMENTS in (
        embedding_change.invalidated_stages
    )
    assert Phase3RecoveryStage.REFERENCE_COMPARISONS in (
        embedding_change.invalidated_stages
    )
    assert Phase3RecoveryStage.CLUSTERING in (
        embedding_change.invalidated_stages
    )
    assert Phase3RecoveryStage.DIARIZATION_PROVIDER_RESPONSE in (
        embedding_change.preserved_stages
    )
    assert Phase3RecoveryStage.DIARIZATION_NORMALIZED_OBSERVATIONS in (
        embedding_change.preserved_stages
    )


def _task(
    root: Path,
    stage: Phase3RecoveryStage,
    initial: str | None,
    rebuild_counts: dict[Phase3RecoveryStage, int],
    *,
    provider: bool = False,
) -> Phase3RecoveryTask:
    artifact = root / stage.value / "entry"
    if initial is not None:
        artifact.mkdir(parents=True)
        (artifact / "evidence.txt").write_text(initial, encoding="utf-8")

    def validate(path: Path) -> None:
        if (path / "evidence.txt").read_text(encoding="utf-8") != "valid":
            raise ValueError(f"{stage.value} corruption detected")

    def rebuild() -> Path:
        rebuild_counts[stage] = rebuild_counts.get(stage, 0) + 1
        artifact.mkdir(parents=True)
        (artifact / "evidence.txt").write_text("valid", encoding="utf-8")
        return artifact

    return Phase3RecoveryTask(
        stage=stage,
        artifact_root=artifact,
        artifact_id=f"{stage.value}-artifact",
        validate=validate,
        rebuild=rebuild,
        upstream_artifact_ids=("protected-phase2-transcript",),
        provider_invoked_on_rebuild=provider,
    )


def test_corrupt_stage_quarantines_and_rebuilds_only_transitive_dependents(
    tmp_path: Path,
) -> None:
    protected = tmp_path / "phase2" / "transcript.json"
    protected.parent.mkdir()
    protected.write_text("immutable transcript", encoding="utf-8")
    before = fingerprint("phase2-transcript", protected)
    counts: dict[Phase3RecoveryStage, int] = {}
    tasks = (
        _task(
            tmp_path,
            Phase3RecoveryStage.PARTICIPANT_SUBTITLES,
            "valid",
            counts,
        ),
        _task(
            tmp_path,
            Phase3RecoveryStage.DIARIZATION_PROVIDER_RESPONSE,
            "valid",
            counts,
            provider=True,
        ),
        _task(
            tmp_path,
            Phase3RecoveryStage.IDENTITY_VIEWS,
            "valid",
            counts,
        ),
        _task(
            tmp_path,
            Phase3RecoveryStage.CLUSTERING,
            "corrupt",
            counts,
        ),
        _task(
            tmp_path,
            Phase3RecoveryStage.DIARIZATION_NORMALIZED_OBSERVATIONS,
            "valid",
            counts,
        ),
    )

    records, plans = recover_phase3_pipeline(tasks, report_root=tmp_path)
    by_stage = {record.stage: record for record in records}

    assert by_stage[
        Phase3RecoveryStage.DIARIZATION_PROVIDER_RESPONSE
    ].action == Phase3RecoveryAction.REUSED_VALID
    assert not by_stage[
        Phase3RecoveryStage.DIARIZATION_PROVIDER_RESPONSE
    ].provider_invoked
    assert by_stage[
        Phase3RecoveryStage.DIARIZATION_NORMALIZED_OBSERVATIONS
    ].action == Phase3RecoveryAction.REUSED_VALID
    assert by_stage[
        Phase3RecoveryStage.CLUSTERING
    ].action == Phase3RecoveryAction.QUARANTINED_AND_REBUILT
    assert by_stage[
        Phase3RecoveryStage.IDENTITY_VIEWS
    ].action == Phase3RecoveryAction.INVALIDATED_AND_REBUILT
    assert by_stage[
        Phase3RecoveryStage.PARTICIPANT_SUBTITLES
    ].action == Phase3RecoveryAction.INVALIDATED_AND_REBUILT
    assert counts == {
        Phase3RecoveryStage.CLUSTERING: 1,
        Phase3RecoveryStage.IDENTITY_VIEWS: 1,
        Phase3RecoveryStage.PARTICIPANT_SUBTITLES: 1,
    }
    assert plans[0].changed_stages == (Phase3RecoveryStage.CLUSTERING,)
    assert before == fingerprint("phase2-transcript", protected)
    for record in records:
        if record.quarantine_relative_path:
            quarantined = tmp_path / record.quarantine_relative_path
            assert (quarantined / "evidence.txt").is_file()


def test_missing_stage_resumes_and_failed_rebuild_preserves_quarantine(
    tmp_path: Path,
) -> None:
    counts: dict[Phase3RecoveryStage, int] = {}
    missing = _task(
        tmp_path,
        Phase3RecoveryStage.REFERENCE_COMPARISONS,
        None,
        counts,
    )
    records, _ = recover_phase3_pipeline((missing,), report_root=tmp_path)
    assert records[0].action == Phase3RecoveryAction.RESUMED_MISSING
    assert records[0].quarantine_relative_path is None

    broken = tmp_path / "broken" / "entry"
    broken.mkdir(parents=True)
    (broken / "evidence.txt").write_text("corrupt", encoding="utf-8")
    task = Phase3RecoveryTask(
        stage=Phase3RecoveryStage.IDENTITY_BINDINGS,
        artifact_root=broken,
        artifact_id="binding-broken",
        validate=lambda _: (_ for _ in ()).throw(ValueError("still invalid")),
        rebuild=lambda: broken,
    )
    with pytest.raises(Phase3RecoveryError, match="recovery failed"):
        recover_phase3_pipeline((task,), report_root=tmp_path)
    assert any(
        (item / "evidence.txt").is_file()
        for item in (broken.parent / "invalid").iterdir()
    )


def test_recovery_report_persistence_integrity_and_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    counts: dict[Phase3RecoveryStage, int] = {}
    task = _task(
        tmp_path,
        Phase3RecoveryStage.SPEAKER_TRANSCRIPT,
        None,
        counts,
    )
    protected = tmp_path / "phase2" / "assembly.json"
    protected.parent.mkdir()
    protected.write_text("canonical assembly", encoding="utf-8")
    before = (fingerprint("phase2-assembly", protected),)
    records, plans = recover_phase3_pipeline((task,), report_root=tmp_path)
    after = (fingerprint("phase2-assembly", protected),)
    report = build_recovery_report(
        records=records,
        invalidation_plans=plans,
        protected_before=before,
        protected_after=after,
        interruption_boundaries=(Phase3RecoveryStage.SPEAKER_TRANSCRIPT,),
        negative_proofs=(
            ("missing persisted stage resumed", True),
            ("Phase 2 evidence unchanged", before == after),
        ),
        generated_at=NOW,
    )
    root = persist_recovery_report(report, tmp_path)
    validate_recovery_report(report, root=root)
    assert report.status == "passed"

    assert main(["--json", "phase3-recovery", "inspect", str(root)]) == 0
    assert report.report_id in capsys.readouterr().out
    assert main(
        [
            "--json",
            "phase3-recovery",
            "plan",
            Phase3RecoveryStage.IDENTITY_BINDINGS.value,
        ]
    ) == 0
    assert "participant_subtitles" in capsys.readouterr().out

    (root / "report.md").write_text("corrupt", encoding="utf-8")
    assert main(["phase3-recovery", "validate", str(root)]) == 5
    assert "integrity_failure" in capsys.readouterr().err


def test_recovery_refuses_artifact_outside_declared_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-phase3-entry"
    task = Phase3RecoveryTask(
        stage=Phase3RecoveryStage.CLUSTERING,
        artifact_root=outside,
        artifact_id="outside",
        validate=lambda _: None,
        rebuild=lambda: outside,
    )
    with pytest.raises(Phase3RecoveryError, match="below the report root"):
        recover_phase3_pipeline((task,), report_root=tmp_path)
