"""Aggregate Phase 3 integrity inventory and completion reporting."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase3_completion_contracts import (
    CompletionEvidenceClass,
    CompletionGateStatus,
    CompletionMetricStatus,
    Phase3CompletionEvidence,
    Phase3CompletionGate,
    Phase3CompletionMetric,
    Phase3CompletionPolicy,
    Phase3CompletionReport,
    Phase3IntegrityFinding,
    Phase3ProviderDisclosure,
)
from .version import (
    __version__,
    CONTRACT_VERSION,
    REPORT_VERSION,
    WORKSPACE_VERSION,
)


class Phase3CompletionIntegrityError(RuntimeError):
    """Phase 3 completion evidence is corrupt, incompatible, or inconsistent."""


REQUIRED_EVIDENCE: dict[str, CompletionEvidenceClass] = {
    "phase-3-foundation.json": CompletionEvidenceClass.SYNTHETIC_MECHANICS,
    "phase-3-diarization-kernel.json": (
        CompletionEvidenceClass.SYNTHETIC_MECHANICS
    ),
    "phase-3-overlap-boundary-qualification.json": (
        CompletionEvidenceClass.SYNTHETIC_MECHANICS
    ),
    "phase-3-provisional-clustering-qualification.json": (
        CompletionEvidenceClass.SYNTHETIC_MECHANICS
    ),
    "phase-3-controlled-clustering-evaluation.json": (
        CompletionEvidenceClass.MEASURED_EVALUATION
    ),
    "phase-3-identity-foundation.json": (
        CompletionEvidenceClass.SYNTHETIC_MECHANICS
    ),
    "phase-3-reference-enrollment-qualification.json": (
        CompletionEvidenceClass.SYNTHETIC_MECHANICS
    ),
    "phase-3-reference-comparison-qualification.json": (
        CompletionEvidenceClass.SYNTHETIC_MECHANICS
    ),
    "phase-3-comparison-hypothesis-integration-qualification.json": (
        CompletionEvidenceClass.SYNTHETIC_MECHANICS
    ),
    "phase-3-manual-identity-binding-qualification.json": (
        CompletionEvidenceClass.HUMAN_DECISION_MECHANICS
    ),
    "phase-3-identity-view-assembly-qualification.json": (
        CompletionEvidenceClass.HUMAN_DECISION_MECHANICS
    ),
    "phase-3-speaker-transcript-integration-qualification.json": (
        CompletionEvidenceClass.PRESENTATION_VALIDATION
    ),
    "phase-3-participant-subtitle-qualification.json": (
        CompletionEvidenceClass.PRESENTATION_VALIDATION
    ),
    "phase-3-cache-recovery-qualification.json": (
        CompletionEvidenceClass.SYNTHETIC_MECHANICS
    ),
    "phase-3-controlled-diarization-evaluation.json": (
        CompletionEvidenceClass.MEASURED_EVALUATION
    ),
}

LONG_RECORDING_FILE = "phase-3-long-recording-qualification.json"
LONG_RECORDING_QUALIFICATION = "phase-3-long-recording-operation"
LONG_REQUIRED_MEASUREMENTS = (
    "duration_microseconds",
    "speaker_observation_count",
    "speaker_turn_count",
    "overlap_count",
    "overlap_duration_microseconds",
    "cluster_count",
    "unclustered_observation_count",
    "identity_hypothesis_count",
    "manual_binding_count",
    "unknown_or_unresolved_count",
    "participant_subtitle_export_count",
    "cache_hit_count",
    "invalidation_count",
    "recovery_count",
    "peak_memory_bytes",
)


GATE_DEFINITIONS: tuple[
    tuple[int, str, tuple[str, ...]], ...
] = (
    (1, "Source-addressed observations", (
        "phase-3-contract-and-evidence-boundary-foundation",
        "phase-3-deterministic-diarization-evidence-kernel",
    )),
    (2, "Speaker turns", (
        "phase-3-deterministic-diarization-evidence-kernel",
    )),
    (3, "Speaker-change evidence", (
        "phase-3-overlap-and-uncertain-boundary",
    )),
    (4, "Overlap", (
        "phase-3-overlap-and-uncertain-boundary",
        "phase-3-controlled-temporal-diarization-evaluation",
    )),
    (5, "Speaker clustering", (
        "phase-3-provisional-acoustic-clustering",
    )),
    (6, "Cluster consistency", (
        "phase-3-provisional-acoustic-clustering",
        "phase-3-controlled-clustering-evaluation",
    )),
    (7, "Merge and split history", (
        "phase-3-provisional-acoustic-clustering",
    )),
    (8, "Identity hypotheses", (
        "phase-3-scoped-participant-identity-foundation",
        "phase-3-comparison-backed-identity-hypotheses",
    )),
    (9, "Reference-voice enrollment", (
        "phase-3-bounded-reference-voice-enrollment",
    )),
    (10, "Reference comparison", (
        "phase-3-compatible-reference-voice-comparison",
    )),
    (11, "Manual identity binding", (
        "phase-3-manual-identity-binding",
    )),
    (12, "Unknown and conflict", (
        "phase-3-reviewed-identity-view-assembly",
    )),
    (13, "Transcript integration", (
        "phase-3-speaker-labeled-transcript-integration",
        "phase-3-participant-labeled-subtitles",
    )),
    (14, "Evaluation", (
        "phase-3-controlled-clustering-evaluation",
        "phase-3-controlled-temporal-diarization-evaluation",
    )),
    (15, "Cache and recovery", (
        "phase-3-cache-resume-recovery",
    )),
    (16, "Integrity", tuple()),
    (17, "Long-recording operation", (
        LONG_RECORDING_QUALIFICATION,
    )),
    (18, "Regression and boundary", (
        "phase-3-contract-and-evidence-boundary-foundation",
    )),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.partial-{uuid.uuid4().hex}")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _load_qualification(
    reports_root: Path,
    filename: str,
    evidence_class: CompletionEvidenceClass,
) -> tuple[Phase3CompletionEvidence, dict]:
    machine = reports_root / filename
    human = machine.with_suffix(".md")
    try:
        payload = json.loads(machine.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Phase3CompletionIntegrityError(
            f"Phase 3 qualification is unreadable: {filename}"
        ) from exc
    if not isinstance(payload, dict):
        raise Phase3CompletionIntegrityError(
            f"Phase 3 qualification is not an object: {filename}"
        )
    required = {
        "application_version",
        "assertions",
        "phase",
        "qualification",
        "schema_exports",
        "status",
        "target_application_version",
        "tests",
        "work_order",
    }
    if not required.issubset(payload):
        raise Phase3CompletionIntegrityError(
            f"Phase 3 qualification lacks common fields: {filename}"
        )
    assertions = payload["assertions"]
    tests = payload["tests"]
    schemas = payload["schema_exports"]
    if (
        payload["phase"] != 3
        or payload["status"] != "passed"
        or payload["work_order"] != "docs/work_orders/phase_03.txt"
        or not isinstance(assertions, dict)
        or not assertions
        or not all(value is True for value in assertions.values())
        or not isinstance(tests, dict)
        or tests.get("status") != "passed"
        or not isinstance(tests.get("full_regression"), int)
        or not isinstance(schemas, dict)
        or not isinstance(schemas.get("runtime_contracts"), int)
    ):
        raise Phase3CompletionIntegrityError(
            f"Phase 3 qualification failed common validation: {filename}"
        )
    if not human.is_file():
        raise Phase3CompletionIntegrityError(
            f"Phase 3 qualification lacks its human report: {filename}"
        )
    return (
        Phase3CompletionEvidence(
            qualification=payload["qualification"],
            machine_report_relative_path=machine.name,
            machine_report_sha256=_sha256(machine),
            machine_report_byte_size=machine.stat().st_size,
            human_report_relative_path=human.name,
            human_report_sha256=_sha256(human),
            human_report_byte_size=human.stat().st_size,
            evidence_class=evidence_class,
            application_version=payload["application_version"],
            target_application_version=payload[
                "target_application_version"
            ],
            assertion_count=len(assertions),
            full_regression_test_count=tests["full_regression"],
            runtime_schema_count=schemas["runtime_contracts"],
            status="passed",
        ),
        payload,
    )


def _inventory(
    reports_root: Path,
) -> tuple[
    tuple[Phase3CompletionEvidence, ...],
    dict[str, dict],
    tuple[Phase3IntegrityFinding, ...],
]:
    evidence = []
    payloads: dict[str, dict] = {}
    findings = []
    for filename, evidence_class in REQUIRED_EVIDENCE.items():
        if not (reports_root / filename).is_file():
            findings.append(
                Phase3IntegrityFinding(
                    finding_code="phase3.evidence.missing",
                    severity="warning",
                    message=f"Required qualification is missing: {filename}",
                    evidence_relative_path=filename,
                )
            )
            continue
        item, payload = _load_qualification(
            reports_root, filename, evidence_class
        )
        if item.qualification in payloads:
            raise Phase3CompletionIntegrityError(
                "Phase 3 qualification identifiers are duplicated"
            )
        evidence.append(item)
        payloads[item.qualification] = payload
    long_path = reports_root / LONG_RECORDING_FILE
    if long_path.is_file():
        item, payload = _load_qualification(
            reports_root,
            LONG_RECORDING_FILE,
            CompletionEvidenceClass.SYNTHETIC_MECHANICS,
        )
        if item.qualification != LONG_RECORDING_QUALIFICATION:
            raise Phase3CompletionIntegrityError(
                "Phase 3 long-recording qualification identity is invalid"
            )
        evidence.append(item)
        payloads[item.qualification] = payload
    else:
        findings.append(
            Phase3IntegrityFinding(
                finding_code="phase3.long_recording.pending",
                severity="warning",
                message=(
                    "Gate 17 remains pending until a checked-in Phase 3 "
                    "long-recording qualification is validated."
                ),
                evidence_relative_path=LONG_RECORDING_FILE,
                gate_numbers=(17,),
            )
        )
    evidence.sort(key=lambda item: item.machine_report_relative_path)
    return tuple(evidence), payloads, tuple(findings)


def _metric(
    name: str,
    qualification: str,
    basis: str,
    *,
    measured: str | int | float | bool | None = None,
    unit: str | None = None,
) -> Phase3CompletionMetric:
    return Phase3CompletionMetric(
        metric_name=name,
        status=(
            CompletionMetricStatus.MEASURED
            if measured is not None
            else CompletionMetricStatus.QUALIFIED_MECHANICS
        ),
        value=measured,
        unit=unit,
        evidence_qualifications=(qualification,),
        basis=basis,
    )


def _metrics(
    payloads: dict[str, dict],
    *,
    current_test_count: int,
    current_schema_count: int,
) -> tuple[Phase3CompletionMetric, ...]:
    metrics = [
        Phase3CompletionMetric(
            metric_name="regression_test_count",
            status=CompletionMetricStatus.MEASURED,
            value=current_test_count,
            unit="tests",
            evidence_qualifications=(
                "phase-3-controlled-temporal-diarization-evaluation",
            ),
            basis="Current complete repository regression run.",
        ),
        Phase3CompletionMetric(
            metric_name="runtime_schema_count",
            status=CompletionMetricStatus.MEASURED,
            value=current_schema_count,
            unit="schemas",
            evidence_qualifications=(
                "phase-3-controlled-temporal-diarization-evaluation",
            ),
            basis="Current runtime schema export.",
        ),
        _metric(
            "speaker_observation_count",
            "phase-3-deterministic-diarization-evidence-kernel",
            "Observation counting is implemented and qualified.",
        ),
        _metric(
            "speaker_turn_count",
            "phase-3-deterministic-diarization-evidence-kernel",
            "Turn counting is implemented and qualified.",
        ),
        _metric(
            "overlap_count_and_duration",
            "phase-3-overlap-and-uncertain-boundary",
            "Overlap count and duration reporting are qualified.",
        ),
        _metric(
            "cluster_and_unclustered_counts",
            "phase-3-provisional-acoustic-clustering",
            "Cluster, membership, and unclustered counts are qualified.",
        ),
        _metric(
            "cluster_consistency_and_proposals",
            "phase-3-controlled-clustering-evaluation",
            "Consistency dispositions and merge/split proposals are qualified.",
        ),
        _metric(
            "identity_hypothesis_count",
            "phase-3-comparison-backed-identity-hypotheses",
            "Bounded identity-hypothesis reporting is qualified.",
        ),
        _metric(
            "reference_enrollment_count",
            "phase-3-bounded-reference-voice-enrollment",
            "Enrollment lifecycle counting is qualified.",
        ),
        _metric(
            "reference_comparison_results",
            "phase-3-compatible-reference-voice-comparison",
            "All six comparison result classes are qualified.",
        ),
        _metric(
            "manual_binding_count",
            "phase-3-manual-identity-binding",
            "Append-only manual binding reporting is qualified.",
        ),
        _metric(
            "unknown_and_unresolved_count",
            "phase-3-reviewed-identity-view-assembly",
            "Unknown, conflict, and unresolved views remain countable.",
        ),
        _metric(
            "participant_subtitle_results",
            "phase-3-participant-labeled-subtitles",
            "WebVTT/SRT cue and loss reporting is qualified.",
        ),
        _metric(
            "controlled_clustering_metrics",
            "phase-3-controlled-clustering-evaluation",
            "Pairwise clustering precision, recall, F1, and coverage.",
            measured="controlled fixture metrics reported",
        ),
        _metric(
            "controlled_diarization_metrics",
            "phase-3-controlled-temporal-diarization-evaluation",
            "DER components, boundaries, overlap, and strata.",
            measured="controlled fixture metrics reported",
        ),
        _metric(
            "cache_invalidation_and_recovery",
            "phase-3-cache-resume-recovery",
            "Cache reuse, invalidation, quarantine, and recovery are qualified.",
        ),
    ]
    long_payload = payloads.get(LONG_RECORDING_QUALIFICATION)
    measurements = (
        long_payload.get("measurements")
        if isinstance(long_payload, dict)
        else None
    )
    for name in LONG_REQUIRED_MEASUREMENTS:
        if isinstance(measurements, dict) and name in measurements:
            metrics.append(
                Phase3CompletionMetric(
                    metric_name=f"long_recording_{name}",
                    status=CompletionMetricStatus.MEASURED,
                    value=measurements[name],
                    unit=(
                        "microseconds"
                        if name.endswith("microseconds")
                        else ("bytes" if name == "peak_memory_bytes" else "count")
                    ),
                    evidence_qualifications=(LONG_RECORDING_QUALIFICATION,),
                    basis="Checked-in Phase 3 long-recording qualification.",
                )
            )
        else:
            metrics.append(
                Phase3CompletionMetric(
                    metric_name=f"long_recording_{name}",
                    status=CompletionMetricStatus.PENDING,
                    evidence_qualifications=(),
                    basis="Pending Phase 3 long-recording qualification.",
                )
            )
    return tuple(metrics)


def _gates(
    payloads: dict[str, dict],
    findings: tuple[Phase3IntegrityFinding, ...],
    *,
    current_test_count: int,
) -> tuple[Phase3CompletionGate, ...]:
    available = set(payloads)
    gates = []
    all_required_present = len(
        available - {LONG_RECORDING_QUALIFICATION}
    ) == len(REQUIRED_EVIDENCE)
    latest_recorded_tests = max(
        (
            payload["tests"]["full_regression"]
            for payload in payloads.values()
            if isinstance(payload.get("tests", {}).get("full_regression"), int)
        ),
        default=0,
    )
    for number, name, qualifications in GATE_DEFINITIONS:
        missing = tuple(item for item in qualifications if item not in available)
        if number == 16:
            missing = () if all_required_present else (
                "one or more required Phase 3 qualifications",
            )
        if number == 17 and not missing:
            measurements = payloads[
                LONG_RECORDING_QUALIFICATION
            ].get("measurements")
            if not isinstance(measurements, dict) or any(
                item not in measurements for item in LONG_REQUIRED_MEASUREMENTS
            ):
                missing = ("complete long-recording measurements",)
            elif measurements["duration_microseconds"] <= 7_200_000_000:
                missing = ("recording duration greater than two hours",)
        if number == 18 and current_test_count < latest_recorded_tests:
            missing = ("current regression count at least latest evidence",)
        status = (
            CompletionGateStatus.COMPLETE
            if not missing
            else CompletionGateStatus.PENDING
        )
        evidence = (
            tuple(sorted(available))
            if number == 16 and not missing
            else tuple(item for item in qualifications if item in available)
        )
        gates.append(
            Phase3CompletionGate(
                gate_number=number,
                gate_name=name,
                status=status,
                evidence_qualifications=evidence,
                basis=(
                    "Checked-in qualification evidence satisfies this gate."
                    if status == CompletionGateStatus.COMPLETE
                    else "Completion evidence is not yet available."
                ),
                blocking_findings=(
                    ()
                    if status == CompletionGateStatus.COMPLETE
                    else tuple(f"Pending: {item}." for item in missing)
                ),
            )
        )
    return tuple(gates)


def _seal(report: Phase3CompletionReport) -> Phase3CompletionReport:
    return report.model_copy(
        update={
            "integrity_sha256": canonical_hash(
                report.model_copy(update={"integrity_sha256": "0" * 64})
            )
        }
    )


def assemble_completion_report(
    reports_root: Path,
    *,
    repository_branch: str,
    starting_repository_head: str,
    final_repository_head: str,
    phase_changes_committed_at_audit: bool,
    current_test_count: int,
    current_schema_count: int,
    generated_at: datetime | None = None,
    predecessor_report_id: str | None = None,
) -> Phase3CompletionReport:
    reports_root = reports_root.expanduser().resolve(strict=True)
    evidence, payloads, findings = _inventory(reports_root)
    metrics = _metrics(
        payloads,
        current_test_count=current_test_count,
        current_schema_count=current_schema_count,
    )
    gates = _gates(
        payloads,
        findings,
        current_test_count=current_test_count,
    )
    report = Phase3CompletionReport(
        report_id=typed_id(
            "phase3completion",
            tuple(item.model_dump(mode="json") for item in evidence),
            tuple(item.model_dump(mode="json") for item in metrics),
            tuple(item.model_dump(mode="json") for item in gates),
            repository_branch,
            starting_repository_head,
            final_repository_head,
            phase_changes_committed_at_audit,
            predecessor_report_id,
        ),
        predecessor_report_id=predecessor_report_id,
        generated_at=generated_at or datetime.now(timezone.utc),
        application_version=__version__,
        target_application_version="0.5.0",
        contract_version_reported=CONTRACT_VERSION,
        workspace_format_version=WORKSPACE_VERSION,
        report_version=REPORT_VERSION,
        repository_branch=repository_branch,
        starting_repository_head=starting_repository_head,
        final_repository_head=final_repository_head,
        phase_changes_committed_at_audit=phase_changes_committed_at_audit,
        policy=Phase3CompletionPolicy(),
        provider=Phase3ProviderDisclosure(
            provider_id="unconfigured.diarization",
            provider_version="1.0.0",
            production_provider_selected=False,
            model_redistributed=False,
            claims=(
                "Synthetic providers qualify deterministic mechanics only.",
            ),
            limitations=(
                "No production diarization, clustering, or reference-"
                "comparison model is selected or qualified.",
                "No model accuracy, biometric identity, or portability claim "
                "is made.",
            ),
        ),
        evidence=evidence,
        metrics=metrics,
        gates=gates,
        integrity_findings=findings,
        privacy_and_export_decisions=(
            "Voice embeddings default to protected references.",
            "Portable embedding export requires explicit authorization.",
            "Embedding values are excluded from reports and logs.",
            "Reference comparison never performs automatic identity binding.",
        ),
        boundary_statements=(
            "A cluster is not a person.",
            "Acoustic similarity is not proof of identity.",
            "Manual binding is a review decision, not a recording change.",
            "Unresolved identity is an acceptable outcome.",
            "No face identification, argument analysis, factual adjudication, "
            "credibility scoring, psychological inference, or participant "
            "judgment is introduced.",
        ),
        known_limitations=(
            "Controlled fixture results do not establish general performance.",
            "Synthetic providers qualify mechanics, not production accuracy.",
            "No production analytical provider or model is selected.",
        ),
        unresolved_concerns=tuple(
            item.message
            for item in findings
            if item.severity in {"warning", "error", "fatal"}
        ),
        status=(
            "complete"
            if all(
                item.status == CompletionGateStatus.COMPLETE for item in gates
            )
            else "in_progress"
        ),
        integrity_sha256="0" * 64,
    )
    return _seal(report)


def completion_markdown(report: Phase3CompletionReport) -> bytes:
    lines = [
        "# Phase 3 integrity and completion report",
        "",
        f"Status: **{report.status.upper()}**",
        "",
        "## Exit gates",
        "",
        "| Gate | Status | Evidence |",
        "|---|---|---|",
    ]
    for gate in report.gates:
        evidence = ", ".join(gate.evidence_qualifications) or "pending"
        lines.append(
            f"| {gate.gate_number}. {gate.gate_name} | "
            f"{gate.status.value} | {evidence} |"
        )
    lines.extend(
        [
            "",
            "## Evidence classes",
            "",
            "Measured evaluation, synthetic mechanics, human review mechanics, "
            "presentation validation, provider claims, and future expectations "
            "remain separate.",
            "",
            "## Boundary",
            "",
            *[f"- {item}" for item in report.boundary_statements],
            "",
            "The report cannot become complete until all eighteen gates pass.",
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def persist_completion_report(
    report: Phase3CompletionReport,
    reports_root: Path,
) -> tuple[Path, Path]:
    reports_root = reports_root.expanduser().resolve()
    machine = reports_root / "phase-3-completion.json"
    human = reports_root / "phase-3-completion.md"
    existing = (machine.exists(), human.exists())
    if any(existing) and not all(existing):
        raise Phase3CompletionIntegrityError(
            "persisted Phase 3 completion report is incomplete"
        )
    if all(existing):
        stored = load_contract(
            machine.read_bytes(), Phase3CompletionReport
        )
        validate_completion_report(stored, reports_root=reports_root)
        if stored == report and human.read_bytes() == completion_markdown(stored):
            return machine, human
        if report.predecessor_report_id != stored.report_id:
            raise Phase3CompletionIntegrityError(
                "replacement completion report does not name its predecessor"
            )
        history = (
            reports_root / "phase-3-completion-history" / stored.report_id
        )
        if history.exists():
            raise Phase3CompletionIntegrityError(
                "completion report predecessor archive already exists"
            )
        history.mkdir(parents=True)
        os.replace(machine, history / machine.name)
        os.replace(human, history / human.name)
    _atomic(machine, canonical_bytes(report))
    _atomic(human, completion_markdown(report))
    validate_completion_report(report, reports_root=reports_root)
    return machine, human


def validate_completion_report(
    report: Phase3CompletionReport,
    *,
    reports_root: Path | None = None,
) -> None:
    if _seal(report).integrity_sha256 != report.integrity_sha256:
        raise Phase3CompletionIntegrityError(
            "Phase 3 completion report integrity seal is invalid"
        )
    if reports_root is None:
        return
    reports_root = reports_root.expanduser().resolve(strict=True)
    for item in report.evidence:
        machine = reports_root / item.machine_report_relative_path
        human = reports_root / item.human_report_relative_path
        if (
            not machine.is_file()
            or not human.is_file()
            or machine.stat().st_size != item.machine_report_byte_size
            or human.stat().st_size != item.human_report_byte_size
            or _sha256(machine) != item.machine_report_sha256
            or _sha256(human) != item.human_report_sha256
        ):
            raise Phase3CompletionIntegrityError(
                "inventoried Phase 3 evidence changed or is missing"
            )
    machine_report = reports_root / "phase-3-completion.json"
    human_report = reports_root / "phase-3-completion.md"
    if machine_report.exists() or human_report.exists():
        if (
            not machine_report.is_file()
            or not human_report.is_file()
            or machine_report.read_bytes() != canonical_bytes(report)
            or human_report.read_bytes() != completion_markdown(report)
        ):
            raise Phase3CompletionIntegrityError(
                "persisted Phase 3 completion report failed validation"
            )


def load_completion_report(
    reports_root: Path,
) -> Phase3CompletionReport:
    reports_root = reports_root.expanduser().resolve(strict=True)
    report = load_contract(
        (reports_root / "phase-3-completion.json").read_bytes(),
        Phase3CompletionReport,
    )
    validate_completion_report(report, reports_root=reports_root)
    return report
