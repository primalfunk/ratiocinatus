from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ratiocinatus.cli import EXIT_INTEGRITY, EXIT_SUCCESS, main
from ratiocinatus.phase3_completion import (
    LONG_RECORDING_FILE,
    REQUIRED_EVIDENCE,
    Phase3CompletionIntegrityError,
    assemble_completion_report,
    load_completion_report,
    persist_completion_report,
    validate_completion_report,
)
from ratiocinatus.phase3_completion_contracts import (
    PHASE3_COMPLETION_CONTRACT_MODELS,
    CompletionGateStatus,
    CompletionMetricStatus,
)

NOW = datetime(2000, 1, 1, tzinfo=timezone.utc)
HEAD = "a" * 40


def test_phase3_completion_contract_schemas_are_closed() -> None:
    assert len(PHASE3_COMPLETION_CONTRACT_MODELS) == 7
    for model in PHASE3_COMPLETION_CONTRACT_MODELS:
        schema = model.model_json_schema()
        assert schema["title"] == model.__name__
        assert schema.get("additionalProperties") is False


def _copy_evidence(destination: Path) -> None:
    source = Path("reports")
    destination.mkdir()
    for filename in REQUIRED_EVIDENCE:
        machine = source / filename
        human = machine.with_suffix(".md")
        shutil.copy2(machine, destination / machine.name)
        shutil.copy2(human, destination / human.name)


def _assemble(root: Path, *, tests: int = 184):
    return assemble_completion_report(
        root,
        repository_branch="master",
        starting_repository_head=HEAD,
        final_repository_head=HEAD,
        phase_changes_committed_at_audit=False,
        current_test_count=tests,
        current_schema_count=230,
        generated_at=NOW,
    )


def test_current_evidence_is_inventoried_and_only_long_gate_is_pending(
    tmp_path: Path,
) -> None:
    root = tmp_path / "reports"
    _copy_evidence(root)
    report = _assemble(root)

    assert report.status == "in_progress"
    assert len(report.evidence) == 15
    assert {item.evidence_class.value for item in report.evidence} >= {
        "measured_evaluation",
        "synthetic_mechanics",
        "human_decision_mechanics",
        "presentation_validation",
    }
    pending = [
        item.gate_number
        for item in report.gates
        if item.status == CompletionGateStatus.PENDING
    ]
    assert pending == [17]
    assert all(
        item.status == CompletionMetricStatus.PENDING
        for item in report.metrics
        if item.metric_name.startswith("long_recording_")
    )
    assert report.provider.provider_id == "unconfigured.diarization"
    assert not report.provider.production_provider_selected
    assert "A cluster is not a person." in report.boundary_statements
    validate_completion_report(report, reports_root=root)


def test_missing_evidence_degrades_but_corrupt_evidence_refuses(
    tmp_path: Path,
) -> None:
    root = tmp_path / "reports"
    _copy_evidence(root)
    missing = root / "phase-3-reference-comparison-qualification.json"
    missing.unlink()
    report = _assemble(root)
    assert report.status == "in_progress"
    assert report.gates[9].status == CompletionGateStatus.PENDING
    assert any(
        item.finding_code == "phase3.evidence.missing"
        for item in report.integrity_findings
    )

    missing.write_text("{not-json", encoding="utf-8")
    with pytest.raises(
        Phase3CompletionIntegrityError, match="unreadable"
    ):
        _assemble(root)


def test_long_recording_requires_complete_measurements_before_completion(
    tmp_path: Path,
) -> None:
    root = tmp_path / "reports"
    _copy_evidence(root)
    machine = root / LONG_RECORDING_FILE
    human = machine.with_suffix(".md")
    payload = {
        "application_version": "0.4.0",
        "assertions": {
            "bounded_memory": True,
            "cache_replay": True,
            "cross_chunk_continuity": True,
        },
        "measurements": {
            "duration_microseconds": 7_201_000_000,
            "speaker_observation_count": 13,
            "speaker_turn_count": 13,
            "overlap_count": 12,
            "overlap_duration_microseconds": 5_000_000,
            "cluster_count": 3,
            "unclustered_observation_count": 0,
            "identity_hypothesis_count": 3,
            "manual_binding_count": 3,
            "unknown_or_unresolved_count": 0,
            "participant_subtitle_export_count": 2,
            "cache_hit_count": 11,
            "invalidation_count": 1,
            "recovery_count": 1,
            "peak_memory_bytes": 4_000_000,
        },
        "phase": 3,
        "qualification": "phase-3-long-recording-operation",
        "schema_exports": {
            "fixture_contracts": 20,
            "runtime_contracts": 230,
        },
        "status": "passed",
        "target_application_version": "0.5.0",
        "tests": {
            "focused_long_recording": 1,
            "full_regression": 184,
            "status": "passed",
        },
        "work_order": "docs/work_orders/phase_03.txt",
    }
    machine.write_text(json.dumps(payload), encoding="utf-8")
    human.write_text("# Controlled long recording\n", encoding="utf-8")

    report = _assemble(root)
    assert report.status == "complete"
    assert all(
        item.status == CompletionGateStatus.COMPLETE for item in report.gates
    )
    assert all(
        item.status == CompletionMetricStatus.MEASURED
        for item in report.metrics
        if item.metric_name.startswith("long_recording_")
    )

    payload["measurements"].pop("peak_memory_bytes")
    machine.write_text(json.dumps(payload), encoding="utf-8")
    incomplete = _assemble(root)
    assert incomplete.status == "in_progress"
    assert incomplete.gates[16].status == CompletionGateStatus.PENDING


def test_persistence_cli_and_inventoried_mutation_refusal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "reports"
    _copy_evidence(root)
    report = _assemble(root)
    machine, human = persist_completion_report(report, root)
    assert machine.is_file()
    assert human.is_file()
    assert load_completion_report(root) == report

    assert main(
        [
            "--json",
            "phase3-report",
            "build",
            str(root),
            "--repository-branch",
            "master",
            "--starting-head",
            HEAD,
            "--final-head",
            HEAD,
            "--test-count",
            "184",
            "--schema-count",
            "230",
        ]
    ) == EXIT_SUCCESS
    capsys.readouterr()
    assert main(
        ["--json", "phase3-report", "list-gates", str(root)]
    ) == EXIT_SUCCESS
    assert "Long-recording operation" in capsys.readouterr().out
    assert main(
        ["--json", "phase3-report", "list-evidence", str(root)]
    ) == EXIT_SUCCESS
    assert "phase-3-cache-resume-recovery" in capsys.readouterr().out

    source_human = root / "phase-3-cache-recovery-qualification.md"
    source_human.write_text("corrupt", encoding="utf-8")
    assert main(["phase3-report", "validate", str(root)]) == EXIT_INTEGRITY
    assert "integrity_failure" in capsys.readouterr().err


def test_regression_count_cannot_move_backwards(tmp_path: Path) -> None:
    root = tmp_path / "reports"
    _copy_evidence(root)
    report = _assemble(root, tests=100)
    assert report.status == "in_progress"
    assert report.gates[17].status == CompletionGateStatus.PENDING
    assert "latest evidence" in report.gates[17].blocking_findings[0]
