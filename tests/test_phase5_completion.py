from pathlib import Path

import pytest

from ratiocinatus.phase5_completion import (
    QUALIFICATIONS,
    Phase5CompletionIntegrityError,
    assemble_phase5_completion,
    load_phase5_completion,
    make_completion_evidence,
    persist_phase5_completion,
    validate_phase5_completion,
)
from ratiocinatus.phase5_completion_contracts import Phase5EvidenceClass
from ratiocinatus.phase5_long_recording import (
    qualify_phase5_long_recording,
)
from ratiocinatus.phase5_recovery_contracts import (
    Phase5NegativeProof,
    Phase5NegativeProofKind,
    Phase5RecoveryAction,
    Phase5RecoveryPolicy,
    Phase5RecoveryRecord,
    Phase5RecoveryReport,
    Phase5RecoveryStage,
)
from ratiocinatus.kernel import canonical_hash, typed_id

from test_phase5_export_recovery import _portable
from test_phase5_foundation import NOW

HEAD = "1" * 40


def _seal_recovery(report):
    return report.model_copy(
        update={
            "integrity_sha256": canonical_hash(
                report.model_copy(update={"integrity_sha256": "0" * 64})
            )
        }
    )


def _recovery():
    proofs = tuple(
        Phase5NegativeProof(
            kind=kind,
            passed=True,
            failure_type="ControlledTypedRefusal",
            message="Controlled negative proof passed.",
            typed_refusal=True,
            conservative_degradation=False,
            source_evidence_preserved=True,
            evidence_references=(f"negative:{kind.value}",),
        )
        for kind in Phase5NegativeProofKind
    )
    report = Phase5RecoveryReport(
        report_id=typed_id("phase5recovery", "completion-fixture"),
        generated_at=NOW,
        policy=Phase5RecoveryPolicy(),
        records=tuple(
            Phase5RecoveryRecord(
                stage=stage,
                artifact_id=f"artifact:{stage.value}",
                action=Phase5RecoveryAction.REUSED_VALID,
                provider_invoked=False,
            )
            for stage in Phase5RecoveryStage
        ),
        protected_before=(),
        protected_after=(),
        interruption_boundaries=tuple(Phase5RecoveryStage),
        negative_proofs=proofs,
        findings=(),
        status="passed",
        integrity_sha256="0" * 64,
    )
    return _seal_recovery(report)


def _evidence():
    classes = {
        "provider": Phase5EvidenceClass.PROVIDER_PROPOSALS,
        "review": Phase5EvidenceClass.HUMAN_REVIEW,
        "evaluation": Phase5EvidenceClass.MEASURED_EVALUATION,
        "recovery": Phase5EvidenceClass.INTEGRITY_VALIDATION,
        "export": Phase5EvidenceClass.INTEGRITY_VALIDATION,
        "long": Phase5EvidenceClass.SYNTHETIC_MECHANICS,
        "regression": Phase5EvidenceClass.INTEGRITY_VALIDATION,
    }
    return tuple(
        make_completion_evidence(
            qualification,
            f"controlled:{key}",
            f"{key}:passed".encode(),
            classes.get(
                key, Phase5EvidenceClass.SELECTED_MACHINE_ANALYSIS
            ),
        )
        for key, qualification in QUALIFICATIONS.items()
    )


def _assemble(*, evidence=None, tests=320):
    _, artifacts = _portable()
    return assemble_phase5_completion(
        artifacts,
        _recovery(),
        qualify_phase5_long_recording(generated_at=NOW),
        evidence if evidence is not None else _evidence(),
        repository_branch="work",
        starting_repository_head=HEAD,
        final_repository_head=HEAD,
        phase_changes_committed_at_audit=False,
        current_test_count=tests,
        current_schema_count=407,
        generated_at=NOW,
    )


def test_completion_closes_all_twenty_four_gates_and_measures_inventory(
    tmp_path: Path,
):
    report = _assemble()
    assert report.status == "complete"
    assert [item.gate_number for item in report.gates] == list(range(1, 25))
    assert all(item.status.value == "complete" for item in report.gates)
    assert report.measurements.full_regression_test_count == 320
    assert report.measurements.runtime_schema_count == 407
    assert report.measurements.recovery_stage_count == 14
    assert report.measurements.negative_proof_count == 25
    assert report.measurements.long_recording_duration_microseconds > (
        7_200_000_000
    )
    assert len(report.boundary_statements) >= 7
    validate_phase5_completion(report)
    machine, human = persist_phase5_completion(report, tmp_path)
    assert machine.is_file() and human.is_file()
    assert load_phase5_completion(tmp_path) == report
    assert persist_phase5_completion(report, tmp_path) == (machine, human)


def test_missing_evidence_and_regression_backslide_remain_pending():
    without_long = tuple(
        item
        for item in _evidence()
        if item.qualification != QUALIFICATIONS["long"]
    )
    report = _assemble(evidence=without_long)
    assert report.status == "in_progress"
    assert report.gates[22].status.value == "pending"
    regression = _assemble(tests=319)
    assert regression.status == "in_progress"
    assert regression.gates[23].status.value == "pending"


def test_completion_refuses_tampering():
    report = _assemble()
    tampered = report.model_copy(
        update={"phase_changes_committed_at_audit": True}
    )
    with pytest.raises(Phase5CompletionIntegrityError, match="integrity"):
        validate_phase5_completion(tampered)


def test_cli_exposes_long_recording_and_completion_reports():
    from ratiocinatus.cli import build_parser

    parser = build_parser()
    long_args = parser.parse_args(
        ["phase5-long", "build", "long.json"]
    )
    report_args = parser.parse_args(
        ["phase5-report", "list-gates", "reports"]
    )
    assert long_args.command == "phase5-long"
    assert report_args.command == "phase5-report"
