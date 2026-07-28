"""Aggregate Phase 4 qualification evidence into nineteen exit gates."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase4_completion_contracts import (
    Phase4CompletionEvidence,
    Phase4CompletionGate,
    Phase4CompletionMetric,
    Phase4CompletionPolicy,
    Phase4CompletionReport,
    Phase4EvidenceClass,
    Phase4GateStatus,
    Phase4CompletionIntegrityFinding,
    Phase4MetricStatus,
)
from .version import __version__, CONTRACT_VERSION


class Phase4CompletionIntegrityError(RuntimeError):
    """Completion evidence is corrupt, incompatible, or inconsistent."""


REQUIRED_EVIDENCE: dict[str, Phase4EvidenceClass] = {
    "phase-4-foundation.json": Phase4EvidenceClass.SYNTHETIC_MECHANICS,
    "phase-4-initial-segmentation.json": (
        Phase4EvidenceClass.SYNTHETIC_MECHANICS
    ),
    "phase-4-completeness-disfluency-qualification.json": (
        Phase4EvidenceClass.SYNTHETIC_MECHANICS
    ),
    "phase-4-interruption-overlap-qualification.json": (
        Phase4EvidenceClass.SYNTHETIC_MECHANICS
    ),
    "phase-4-turn-repair-qualification.json": (
        Phase4EvidenceClass.HUMAN_DECISION_MECHANICS
    ),
    "phase-4-quotation-embedded-speech-qualification.json": (
        Phase4EvidenceClass.SYNTHETIC_MECHANICS
    ),
    "phase-4-speaker-attributed-transcript-qualification.json": (
        Phase4EvidenceClass.SYNTHETIC_MECHANICS
    ),
    "phase-4-context-window-qualification.json": (
        Phase4EvidenceClass.SYNTHETIC_MECHANICS
    ),
    "phase-4-propagation-review-qualification.json": (
        Phase4EvidenceClass.HUMAN_DECISION_MECHANICS
    ),
    "phase-4-evaluation-qualification.json": (
        Phase4EvidenceClass.MEASURED_EVALUATION
    ),
    "phase-4-export-integrity-qualification.json": (
        Phase4EvidenceClass.INTEGRITY_VALIDATION
    ),
    "phase-4-recovery-negative-qualification.json": (
        Phase4EvidenceClass.INTEGRITY_VALIDATION
    ),
    "phase-4-long-recording-qualification.json": (
        Phase4EvidenceClass.SYNTHETIC_MECHANICS
    ),
}

LONG_QUALIFICATION = "phase-4-long-recording-operation"
EVALUATION_QUALIFICATION = "phase-4-controlled-utterance-evaluation"
RECOVERY_QUALIFICATION = "phase-4-recovery-and-negative-proofs"
EXPORT_QUALIFICATION = "phase-4-portable-export-integrity"

GATES: tuple[tuple[int, str, tuple[str, ...]], ...] = (
    (1, "Immutable utterance corpus", (
        "phase-4-contract-and-utterance-boundary-foundation",
        "phase-4-deterministic-initial-utterance-segmentation",
    )),
    (2, "Deterministic segmentation", (
        "phase-4-deterministic-initial-utterance-segmentation",
    )),
    (3, "Source-addressed views", (
        "phase-4-speaker-attributed-transcript",
    )),
    (4, "Completeness and disfluency", (
        "phase-4-completeness-and-disfluency-analysis",
    )),
    (5, "Bounded repair", ("phase-4-bounded-turn-repair",)),
    (6, "Temporal relation graph", (
        "phase-4-interruption-overlap-and-continuation",
    )),
    (7, "Interruption and continuation", (
        "phase-4-interruption-overlap-and-continuation",
    )),
    (8, "Incomplete and unknown preservation", (
        "phase-4-completeness-and-disfluency-analysis",
    )),
    (9, "Overlap projection", (
        "phase-4-interruption-overlap-and-continuation",
    )),
    (10, "Quotation and embedded speech", (
        "phase-4-quotation-and-embedded-speech",
    )),
    (11, "Speaker-attributed transcript", (
        "phase-4-speaker-attributed-transcript",
    )),
    (12, "Bounded context windows", ("phase-4-context-windows",)),
    (13, "Correction propagation", (
        "phase-4-correction-propagation-and-review",
    )),
    (14, "Append-only manual review", (
        "phase-4-correction-propagation-and-review",
    )),
    (15, "Controlled evaluation", (EVALUATION_QUALIFICATION,)),
    (16, "Recovery and negative proofs", (RECOVERY_QUALIFICATION,)),
    (17, "Portable export and integrity", (
        EXPORT_QUALIFICATION,
        RECOVERY_QUALIFICATION,
    )),
    (18, "Long-recording operation", (LONG_QUALIFICATION,)),
    (19, "Regression, schemas, and boundary", tuple()),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _counts(payload: dict, filename: str) -> tuple[int, int, int]:
    assertions = payload.get("assertions")
    if isinstance(assertions, dict):
        if not assertions or not all(value is True for value in assertions.values()):
            raise Phase4CompletionIntegrityError(
                f"qualification assertions failed: {filename}"
            )
        assertion_count = len(assertions)
    elif isinstance(assertions, list) and assertions and all(
        isinstance(item, str) and item for item in assertions
    ):
        assertion_count = len(assertions)
    else:
        raise Phase4CompletionIntegrityError(
            f"qualification assertions are invalid: {filename}"
        )
    tests = payload.get("tests")
    full_tests = (
        tests.get("full_regression")
        if isinstance(tests, dict)
        else payload.get("full_regression_test_count")
    )
    schemas = payload.get("schema_exports")
    schema_count = (
        schemas.get("runtime_contracts")
        if isinstance(schemas, dict)
        else payload.get("runtime_contracts")
    )
    if not isinstance(full_tests, int) or full_tests < 1:
        raise Phase4CompletionIntegrityError(
            f"qualification test count is invalid: {filename}"
        )
    if not isinstance(schema_count, int) or schema_count < 1:
        raise Phase4CompletionIntegrityError(
            f"qualification schema count is invalid: {filename}"
        )
    return assertion_count, full_tests, schema_count


def _load_evidence(
    root: Path, filename: str, evidence_class: Phase4EvidenceClass
) -> tuple[Phase4CompletionEvidence, dict]:
    machine = root / filename
    human = machine.with_suffix(".md")
    try:
        payload = json.loads(machine.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Phase4CompletionIntegrityError(
            f"qualification is unreadable: {filename}"
        ) from exc
    if (
        not isinstance(payload, dict)
        or payload.get("status") != "passed"
        or not isinstance(payload.get("qualification"), str)
        or not human.is_file()
    ):
        raise Phase4CompletionIntegrityError(
            f"qualification lacks required evidence: {filename}"
        )
    assertion_count, tests, schemas = _counts(payload, filename)
    target = payload.get("target_application_version")
    if not isinstance(target, str) or not target:
        raise Phase4CompletionIntegrityError(
            f"qualification target version is invalid: {filename}"
        )
    return (
        Phase4CompletionEvidence(
            qualification=payload["qualification"],
            machine_report_relative_path=machine.name,
            machine_report_sha256=_sha256(machine),
            machine_report_byte_size=machine.stat().st_size,
            human_report_relative_path=human.name,
            human_report_sha256=_sha256(human),
            human_report_byte_size=human.stat().st_size,
            evidence_class=evidence_class,
            target_application_version=target,
            assertion_count=assertion_count,
            full_regression_test_count=tests,
            runtime_schema_count=schemas,
        ),
        payload,
    )


def _inventory(root: Path):
    evidence = []
    payloads: dict[str, dict] = {}
    findings = []
    for filename, evidence_class in REQUIRED_EVIDENCE.items():
        if not (root / filename).is_file():
            findings.append(
                Phase4CompletionIntegrityFinding(
                    finding_code="phase4.evidence.missing",
                    severity="warning",
                    message=f"Required qualification is missing: {filename}",
                    evidence_relative_path=filename,
                )
            )
            continue
        item, payload = _load_evidence(root, filename, evidence_class)
        if item.qualification in payloads:
            raise Phase4CompletionIntegrityError(
                "qualification identifiers are duplicated"
            )
        evidence.append(item)
        payloads[item.qualification] = payload
    evidence.sort(key=lambda item: item.machine_report_relative_path)
    return tuple(evidence), payloads, tuple(findings)


def _metrics(
    payloads: dict[str, dict], current_test_count: int, current_schema_count: int
) -> tuple[Phase4CompletionMetric, ...]:
    available = tuple(sorted(payloads))
    metrics = [
        Phase4CompletionMetric(
            metric_name="regression_test_count",
            status=Phase4MetricStatus.MEASURED,
            value=current_test_count,
            unit="tests",
            evidence_qualifications=available,
            basis="Current complete repository regression run.",
        ),
        Phase4CompletionMetric(
            metric_name="runtime_schema_count",
            status=Phase4MetricStatus.MEASURED,
            value=current_schema_count,
            unit="schemas",
            evidence_qualifications=available,
            basis="Current complete runtime schema export.",
        ),
    ]
    qualified = {
        "utterance_duration_and_completeness": "phase-4-completeness-and-disfluency-analysis",
        "interruption_continuation_and_overlap": "phase-4-interruption-overlap-and-continuation",
        "self_repair_and_disfluency": "phase-4-completeness-and-disfluency-analysis",
        "quotation_and_attribution": "phase-4-quotation-and-embedded-speech",
        "unknown_and_conflicting_attribution": "phase-4-speaker-attributed-transcript",
        "repair_proposals_and_decisions": "phase-4-bounded-turn-repair",
        "review_actions": "phase-4-correction-propagation-and-review",
        "propagation_changed_and_stable": "phase-4-correction-propagation-and-review",
        "context_windows_and_truncation": "phase-4-context-windows",
        "controlled_evaluation_metrics": EVALUATION_QUALIFICATION,
        "negative_proof_inventory": RECOVERY_QUALIFICATION,
        "portable_export_reload": EXPORT_QUALIFICATION,
    }
    for name, qualification in qualified.items():
        present = qualification in payloads
        metrics.append(
            Phase4CompletionMetric(
                metric_name=name,
                status=(
                    Phase4MetricStatus.QUALIFIED_MECHANICS
                    if present else Phase4MetricStatus.PENDING
                ),
                evidence_qualifications=((qualification,) if present else ()),
                basis=(
                    "Checked-in qualification establishes countable mechanics."
                    if present else "Required qualification remains pending."
                ),
            )
        )
    long = payloads.get(LONG_QUALIFICATION, {}).get("measurements")
    for name in (
        "duration_microseconds",
        "processing_chunk_count",
        "utterance_count",
        "context_window_count",
        "peak_memory_bytes",
        "cache_hit_count",
        "recovery_count",
    ):
        value = long.get(name) if isinstance(long, dict) else None
        metrics.append(
            Phase4CompletionMetric(
                metric_name=f"long_recording_{name}",
                status=(
                    Phase4MetricStatus.MEASURED
                    if value is not None else Phase4MetricStatus.PENDING
                ),
                value=value,
                unit=(
                    "microseconds" if name.endswith("microseconds")
                    else ("bytes" if name.endswith("bytes") else "count")
                ),
                evidence_qualifications=(
                    (LONG_QUALIFICATION,) if value is not None else ()
                ),
                basis="Checked-in provider-free long-recording mechanics.",
            )
        )
    return tuple(metrics)


def _gates(payloads: dict[str, dict], current_test_count: int):
    available = set(payloads)
    latest = max(
        (
            count
            for payload in payloads.values()
            for count in [_counts(payload, payload["qualification"])[1]]
        ),
        default=0,
    )
    all_required = len(available) == len(REQUIRED_EVIDENCE)
    result = []
    for number, name, required in GATES:
        missing = [item for item in required if item not in available]
        if number == 16 and not missing:
            proofs = payloads[RECOVERY_QUALIFICATION].get(
                "negative_proof_count"
            )
            boundaries = payloads[RECOVERY_QUALIFICATION].get(
                "recovery_boundary_count"
            )
            if proofs != 22 or boundaries != 10:
                missing.append("all 22 negative proofs and 10 boundaries")
        if number == 18 and not missing:
            measurements = payloads[LONG_QUALIFICATION].get("measurements")
            if (
                not isinstance(measurements, dict)
                or measurements.get("duration_microseconds", 0)
                <= 7_200_000_000
                or measurements.get("duplicate_word_ownership_count") != 0
                or measurements.get("duplicate_utterance_count") != 0
            ):
                missing.append("valid greater-than-two-hour measurements")
        if number == 19:
            if not all_required:
                missing.append("all required qualification evidence")
            if current_test_count < latest:
                missing.append("non-regressing full test count")
        status = (
            Phase4GateStatus.COMPLETE
            if not missing else Phase4GateStatus.PENDING
        )
        evidence = (
            tuple(sorted(available))
            if number == 19 and not missing
            else tuple(item for item in required if item in available)
        )
        result.append(
            Phase4CompletionGate(
                gate_number=number,
                gate_name=name,
                status=status,
                evidence_qualifications=evidence,
                basis=(
                    "Checked-in evidence satisfies the gate."
                    if not missing else "Completion evidence remains pending."
                ),
                blocking_findings=tuple(f"Pending: {item}." for item in missing),
            )
        )
    return tuple(result)


def _seal(report: Phase4CompletionReport) -> Phase4CompletionReport:
    empty = report.model_copy(update={"integrity_sha256": "0" * 64})
    return report.model_copy(
        update={"integrity_sha256": canonical_hash(empty)}
    )


def assemble_phase4_completion(
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
) -> Phase4CompletionReport:
    root = reports_root.expanduser().resolve(strict=True)
    evidence, payloads, findings = _inventory(root)
    metrics = _metrics(payloads, current_test_count, current_schema_count)
    gates = _gates(payloads, current_test_count)
    status = (
        "complete"
        if all(item.status == Phase4GateStatus.COMPLETE for item in gates)
        else "in_progress"
    )
    report = Phase4CompletionReport(
        report_id=typed_id(
            "phase4completion",
            tuple(item.model_dump(mode="json") for item in evidence),
            tuple(item.model_dump(mode="json") for item in metrics),
            tuple(item.model_dump(mode="json") for item in gates),
            repository_branch,
            starting_repository_head,
            final_repository_head,
            predecessor_report_id,
        ),
        predecessor_report_id=predecessor_report_id,
        generated_at=generated_at or datetime.now(timezone.utc),
        application_version=__version__,
        target_application_version="0.6.0",
        contract_version_reported=CONTRACT_VERSION,
        repository_branch=repository_branch,
        starting_repository_head=starting_repository_head,
        final_repository_head=final_repository_head,
        phase_changes_committed_at_audit=phase_changes_committed_at_audit,
        policy=Phase4CompletionPolicy(),
        evidence=evidence,
        metrics=metrics,
        gates=gates,
        integrity_findings=findings,
        boundary_statements=(
            "Utterance evidence does not rewrite source or prior-phase evidence.",
            "Temporal adjacency does not establish intent, blame, or dominance.",
            "Quoted speakers and acoustic speakers remain distinct.",
            "Unknown and conflicting attribution are valid outcomes.",
            "Synthetic mechanics do not establish natural-speech accuracy.",
            "No credibility, psychological, clinical, or participant judgment is made.",
        ),
        known_limitations=(
            "Controlled fixtures do not establish general performance.",
            "Long-recording evidence qualifies mechanics, not accuracy.",
            "No optional analytical provider is selected or required.",
        ),
        unresolved_concerns=tuple(item.message for item in findings),
        status=status,
        integrity_sha256="0" * 64,
    )
    return _seal(report)


def completion_markdown(report: Phase4CompletionReport) -> bytes:
    lines = [
        "# Phase 4 integrity and completion report",
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
            "## Evidence boundary",
            "",
            *[f"- {item}" for item in report.boundary_statements],
            "",
            "The report is complete only when all nineteen gates pass.",
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def validate_phase4_completion(
    report: Phase4CompletionReport, *, reports_root: Path | None = None
) -> None:
    if _seal(
        report.model_copy(update={"integrity_sha256": "0" * 64})
    ) != report:
        raise Phase4CompletionIntegrityError("completion integrity is invalid")
    if reports_root is not None:
        root = reports_root.expanduser().resolve(strict=True)
        for item in report.evidence:
            machine = root / item.machine_report_relative_path
            human = root / item.human_report_relative_path
            if (
                not machine.is_file()
                or not human.is_file()
                or _sha256(machine) != item.machine_report_sha256
                or _sha256(human) != item.human_report_sha256
            ):
                raise Phase4CompletionIntegrityError(
                    f"completion evidence changed: {item.qualification}"
                )


def _atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.partial-{uuid.uuid4().hex}")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def persist_phase4_completion(
    report: Phase4CompletionReport, reports_root: Path
) -> tuple[Path, Path]:
    validate_phase4_completion(report, reports_root=reports_root)
    root = reports_root.expanduser().resolve()
    machine = root / "phase-4-completion.json"
    human = root / "phase-4-completion.md"
    if machine.exists() or human.exists():
        if not (machine.exists() and human.exists()):
            raise Phase4CompletionIntegrityError(
                "persisted completion pair is incomplete"
            )
        stored = load_contract(machine.read_bytes(), Phase4CompletionReport)
        if stored == report and human.read_bytes() == completion_markdown(stored):
            return machine, human
        raise Phase4CompletionIntegrityError(
            "persisted completion report conflicts"
        )
    _atomic(machine, canonical_bytes(report))
    _atomic(human, completion_markdown(report))
    return machine, human



def load_phase4_completion(reports_root: Path) -> Phase4CompletionReport:
    root = reports_root.expanduser().resolve(strict=True)
    machine = root / "phase-4-completion.json"
    human = root / "phase-4-completion.md"
    if not machine.is_file() or not human.is_file():
        raise Phase4CompletionIntegrityError(
            "persisted completion report pair is missing"
        )
    report = load_contract(machine.read_bytes(), Phase4CompletionReport)
    validate_phase4_completion(report, reports_root=root)
    if human.read_bytes() != completion_markdown(report):
        raise Phase4CompletionIntegrityError(
            "completion human report is stale"
        )
    return report