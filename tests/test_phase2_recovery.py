from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ratiocinatus.recovery import (
    build_recovery_report,
    fingerprint,
    persist_recovery_report,
    recover_artifact,
    validate_recovery_report,
)
from ratiocinatus.recovery_contracts import (
    RECOVERY_CONTRACT_MODELS,
    Phase2RecoveryStage,
    RecoveryAction,
)

NOW = datetime(2000, 1, 1, tzinfo=timezone.utc)


def test_recovery_contract_schemas_are_closed():
    for model in RECOVERY_CONTRACT_MODELS:
        schema = model.model_json_schema()
        assert schema["title"] == model.__name__
        assert schema.get("additionalProperties") is False


def test_corrupt_stage_is_quarantined_and_only_that_stage_is_rebuilt(tmp_path):
    protected = tmp_path / "upstream" / "response.json"
    protected.parent.mkdir()
    protected.write_text("validated upstream", encoding="utf-8")
    before = (fingerprint("transcription-response", protected),)
    artifact = tmp_path / "phase2" / "transcript-assemblies" / "assembly-1"
    artifact.mkdir(parents=True)
    (artifact / "assembly.json").write_text("corrupt", encoding="utf-8")

    def validate(root):
        if (root / "assembly.json").read_text(encoding="utf-8") != "valid":
            raise ValueError("assembly corruption detected")

    def rebuild():
        artifact.mkdir(parents=True)
        (artifact / "assembly.json").write_text("valid", encoding="utf-8")
        return artifact

    record, rebuilt = recover_artifact(
        stage=Phase2RecoveryStage.TRANSCRIPT_ASSEMBLY,
        artifact_root=artifact,
        report_root=tmp_path,
        artifact_id="assembly-1",
        validate=validate,
        rebuild=rebuild,
        upstream_artifact_ids=("response-1",),
    )
    after = (fingerprint("transcription-response", protected),)

    assert rebuilt == artifact.resolve()
    assert record.action == RecoveryAction.QUARANTINED_AND_REBUILT
    assert not record.provider_invoked
    quarantine = tmp_path / record.quarantine_relative_path
    assert (quarantine / "assembly.json").read_text(
        encoding="utf-8"
    ) == "corrupt"
    assert before == after

    report = build_recovery_report(
        records=(record,),
        protected_before=before,
        protected_after=after,
        interruption_boundaries=(
            Phase2RecoveryStage.TRANSCRIPT_ASSEMBLY,
        ),
        negative_proofs=(("corrupt assembly quarantined", True),),
        generated_at=NOW,
    )
    root = persist_recovery_report(report, tmp_path)
    validate_recovery_report(report, root=root)
    assert report.status == "passed"


def test_missing_stage_resumes_without_quarantine(tmp_path):
    artifact = tmp_path / "phase2" / "subtitle-exports" / "subtitle-1"

    def validate(root):
        assert (root / "manifest.json").read_text(encoding="utf-8") == "valid"

    def rebuild():
        artifact.mkdir(parents=True)
        (artifact / "manifest.json").write_text("valid", encoding="utf-8")
        return artifact

    record, _ = recover_artifact(
        stage=Phase2RecoveryStage.SUBTITLE_EXPORT,
        artifact_root=artifact,
        report_root=tmp_path,
        artifact_id="subtitle-1",
        validate=validate,
        rebuild=rebuild,
    )

    assert record.action == RecoveryAction.RESUMED_MISSING
    assert record.quarantine_relative_path is None


def test_failed_rebuild_is_typed_and_preserves_quarantine(tmp_path):
    from ratiocinatus.recovery import Phase2RecoveryError

    artifact = tmp_path / "phase2" / "transcript-evaluations" / "evaluation-1"
    artifact.mkdir(parents=True)
    (artifact / "report.json").write_text("corrupt", encoding="utf-8")

    with pytest.raises(Phase2RecoveryError, match="recovery failed"):
        recover_artifact(
            stage=Phase2RecoveryStage.TRANSCRIPT_EVALUATION,
            artifact_root=artifact,
            report_root=tmp_path,
            artifact_id="evaluation-1",
            validate=lambda root: (_ for _ in ()).throw(
                ValueError("invalid")
            ),
            rebuild=lambda: artifact,
        )

    assert any(
        (path / "report.json").is_file()
        for path in (artifact.parent / "invalid").iterdir()
    )
