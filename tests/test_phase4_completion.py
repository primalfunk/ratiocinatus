import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ratiocinatus.kernel import load_contract
from ratiocinatus.phase4_completion import (
    EVALUATION_QUALIFICATION,
    EXPORT_QUALIFICATION,
    LONG_QUALIFICATION,
    RECOVERY_QUALIFICATION,
    Phase4CompletionIntegrityError,
    assemble_phase4_completion,
    persist_phase4_completion,
    validate_phase4_completion,
)
from ratiocinatus.phase4_completion_contracts import Phase4CompletionReport


NOW = datetime(2026, 7, 27, tzinfo=timezone.utc)
HEAD = "1" * 40


def _copy_existing(root: Path) -> None:
    source = Path("reports")
    for path in source.glob("phase-4-*.json"):
        if path.name in {
            "phase-4-completion.json",
            "phase-4-evaluation-qualification.json",
            "phase-4-export-integrity-qualification.json",
            "phase-4-recovery-negative-qualification.json",
            "phase-4-long-recording-qualification.json",
        }:
            continue
        shutil.copy2(path, root / path.name)
        human = path.with_suffix(".md")
        if human.is_file():
            shutil.copy2(human, root / human.name)


def _evidence(
    root: Path,
    filename: str,
    qualification: str,
    **extra,
) -> None:
    payload = {
        "qualification": qualification,
        "status": "passed",
        "target_application_version": "0.6.0",
        "assertions": ["Qualified."],
        "full_regression_test_count": 250,
        "runtime_contracts": 320,
        **extra,
    }
    (root / filename).write_text(json.dumps(payload), encoding="utf-8")
    (root / filename).with_suffix(".md").write_text(
        f"# {qualification}\n", encoding="utf-8"
    )


def _complete_root(tmp_path: Path) -> Path:
    _copy_existing(tmp_path)
    _evidence(
        tmp_path,
        "phase-4-evaluation-qualification.json",
        EVALUATION_QUALIFICATION,
    )
    _evidence(
        tmp_path,
        "phase-4-export-integrity-qualification.json",
        EXPORT_QUALIFICATION,
    )
    _evidence(
        tmp_path,
        "phase-4-recovery-negative-qualification.json",
        RECOVERY_QUALIFICATION,
        negative_proof_count=22,
        recovery_boundary_count=10,
    )
    _evidence(
        tmp_path,
        "phase-4-long-recording-qualification.json",
        LONG_QUALIFICATION,
        measurements={
            "duration_microseconds": 7_201_000_000,
            "processing_chunk_count": 121,
            "utterance_count": 121,
            "context_window_count": 1089,
            "peak_memory_bytes": 512,
            "cache_hit_count": 1,
            "recovery_count": 1,
            "duplicate_word_ownership_count": 0,
            "duplicate_utterance_count": 0,
        },
    )
    return tmp_path


def _assemble(root: Path, *, tests: int = 250):
    return assemble_phase4_completion(
        root,
        repository_branch="work",
        starting_repository_head=HEAD,
        final_repository_head=HEAD,
        phase_changes_committed_at_audit=False,
        current_test_count=tests,
        current_schema_count=320,
        generated_at=NOW,
    )


def test_completion_reports_missing_stage10_evidence_as_pending(tmp_path):
    _copy_existing(tmp_path)
    report = _assemble(tmp_path)
    assert report.status == "in_progress"
    assert [gate.gate_number for gate in report.gates] == list(range(1, 20))
    assert report.gates[17].status.value == "pending"
    validate_phase4_completion(report, reports_root=tmp_path)


def test_completion_closes_all_nineteen_gates_and_persists(tmp_path):
    root = _complete_root(tmp_path)
    report = _assemble(root)
    assert report.status == "complete"
    assert all(gate.status.value == "complete" for gate in report.gates)
    machine, human = persist_phase4_completion(report, root)
    loaded = load_contract(machine.read_bytes(), Phase4CompletionReport)
    assert loaded == report
    assert human.read_text(encoding="utf-8").startswith(
        "# Phase 4 integrity and completion report"
    )
    assert persist_phase4_completion(report, root) == (machine, human)


def test_completion_refuses_corrupt_evidence(tmp_path):
    root = _complete_root(tmp_path)
    path = root / "phase-4-evaluation-qualification.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["assertions"] = []
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(Phase4CompletionIntegrityError, match="assertions"):
        _assemble(root)


def test_completion_keeps_regression_gate_pending_on_backslide(tmp_path):
    report = _assemble(_complete_root(tmp_path), tests=249)
    assert report.status == "in_progress"
    assert report.gates[18].status.value == "pending"
    assert "non-regressing" in report.gates[18].blocking_findings[0]
