"""Aggregate qualified Phase 5 artifacts into twenty-four exit gates."""

from __future__ import annotations

import hashlib
import os
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path

from .contracts import CONTRACT_VERSION
from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase5_completion_contracts import (
    Phase5CompletionEvidence,
    Phase5CompletionGate,
    Phase5CompletionMeasurements,
    Phase5CompletionPolicy,
    Phase5CompletionReport,
    Phase5EvidenceClass,
    Phase5GateStatus,
    Phase5LongRecordingQualification,
)
from .phase5_export import Phase5PortableArtifactSet
from .phase5_recovery_contracts import Phase5RecoveryReport
from .version import __version__


class Phase5CompletionIntegrityError(RuntimeError):
    """Completion evidence is corrupt, incomplete, or inconsistent."""


QUALIFICATIONS = {
    "foundation": "phase-5-foundation",
    "baseline": "phase-5-deterministic-baseline",
    "provider": "phase-5-provider-analysis",
    "consolidation": "phase-5-candidate-consolidation",
    "question_answer": "phase-5-question-answer",
    "argument": "phase-5-argument-relations",
    "lexical": "phase-5-lexical-example-quotation",
    "procedural": "phase-5-procedural-state",
    "review": "phase-5-review-propagation",
    "evaluation": "phase-5-controlled-evaluation",
    "recovery": "phase-5-cache-recovery",
    "export": "phase-5-portable-export",
    "long": "phase-5-long-recording",
    "regression": "phase-5-regression-boundary",
}

GATES = (
    (1, "Immutable discourse corpus", ("foundation",)),
    (2, "Stable discourse-act observations", ("foundation",)),
    (3, "Controlled vocabulary", ("foundation",)),
    (4, "Multi-label representation", ("consolidation",)),
    (5, "Evidence spans", ("foundation", "consolidation")),
    (6, "Assertions", ("baseline",)),
    (7, "Questions", ("question_answer",)),
    (8, "Answers", ("question_answer",)),
    (9, "Objections", ("argument",)),
    (10, "Rebuttals", ("argument",)),
    (11, "Concessions", ("argument",)),
    (12, "Qualifications", ("argument",)),
    (13, "Definitions", ("lexical",)),
    (14, "Examples", ("lexical",)),
    (15, "Quotations", ("lexical",)),
    (16, "Procedural speech", ("procedural",)),
    (17, "Alternatives and confidence", ("consolidation", "provider")),
    (18, "Correction propagation", ("review",)),
    (19, "Append-only review", ("review",)),
    (20, "Controlled evaluation", ("evaluation",)),
    (21, "Cache and recovery", ("recovery",)),
    (22, "Portable export and integrity", ("export",)),
    (23, "Long-recording operation", ("long",)),
    (24, "Regression and boundary", ("regression",)),
)


def make_completion_evidence(
    qualification: str,
    evidence_reference: str,
    payload: bytes,
    evidence_class: Phase5EvidenceClass,
    *,
    assertion_count: int = 1,
) -> Phase5CompletionEvidence:
    return Phase5CompletionEvidence(
        qualification=qualification,
        evidence_reference=evidence_reference,
        evidence_sha256=hashlib.sha256(payload).hexdigest(),
        evidence_byte_size=len(payload),
        evidence_class=evidence_class,
        assertion_count=assertion_count,
    )


def _measurements(
    artifacts,
    recovery,
    long_recording,
    current_test_count,
    current_schema_count,
):
    corpus = artifacts.corpus
    family = Counter(item.act_family.value for item in corpus.selected_acts)
    act_type = Counter(item.act_type.value for item in corpus.selected_acts)
    utterance_counts = Counter(
        item.utterance_id for item in corpus.selected_acts
    )
    question_types = Counter(
        item.question_type.value for item in artifacts.question_answers.questions
    )
    confidence = {"low": 0, "medium": 0, "high": 0, "unavailable": 0}
    for item in corpus.selected_acts:
        value = item.confidence.selection.value
        bucket = (
            "unavailable"
            if value is None
            else ("low" if value < 0.5 else ("medium" if value < 0.8 else "high"))
        )
        confidence[bucket] += 1
    alternative_count = sum(
        candidate.disposition.value != "selected"
        for candidate_set in corpus.candidate_sets
        for candidate in candidate_set.candidates
    )
    return Phase5CompletionMeasurements(
        discourse_corpus_id=corpus.corpus_id,
        configuration_hash=artifacts.consolidation.configuration_hash,
        phase4_utterance_corpus_id=corpus.phase4_utterance_corpus_id,
        act_family_counts=tuple(
            f"{key}={family[key]}" for key in sorted(family)
        ),
        act_type_counts=tuple(
            f"{key}={act_type[key]}" for key in sorted(act_type)
        ),
        multi_label_utterance_count=sum(
            value > 1 for value in utterance_counts.values()
        ),
        unclassified_utterance_count=len(corpus.unclassified_utterance_ids),
        evidence_span_count=sum(
            len(item.evidence_spans) for item in corpus.selected_acts
        ),
        question_count=len(artifacts.question_answers.questions),
        question_type_counts=tuple(
            f"{key}={question_types[key]}" for key in sorted(question_types)
        ),
        answer_relation_count=len(
            artifacts.question_answers.answer_relations
        ),
        unresolved_answer_count=(
            artifacts.question_answer_report.unresolved_answer_count
        ),
        objection_count=(
            artifacts.argument_relation_report.objection_relation_count
        ),
        rebuttal_count=(
            artifacts.argument_relation_report.rebuttal_relation_count
        ),
        concession_count=len(artifacts.argument_relations.concessions),
        qualification_count=len(artifacts.argument_relations.qualifications),
        definition_count=len(artifacts.lexical_structures.definitions),
        example_count=len(artifacts.lexical_structures.examples),
        quotation_use_count=len(
            artifacts.lexical_structures.quotation_uses
        ),
        procedural_act_count=len(artifacts.procedural_state.events),
        alternative_candidate_count=alternative_count,
        confidence_distribution=tuple(
            f"{key}={confidence[key]}" for key in sorted(confidence)
        ),
        manual_review_action_count=len(artifacts.review_ledger.actions),
        correction_affected_act_count=len(
            artifacts.propagation.invalidated_act_ids
        ),
        measured_evaluation_metric_count=(
            artifacts.evaluation_report.measured_metric_count
        ),
        long_recording_duration_microseconds=(
            long_recording.duration_microseconds
        ),
        recovery_stage_count=len(recovery.records),
        negative_proof_count=len(recovery.negative_proofs),
        peak_memory_bytes=long_recording.peak_memory_bytes,
        full_regression_test_count=current_test_count,
        runtime_schema_count=current_schema_count,
    )


def _seal(report):
    empty = report.model_copy(update={"integrity_sha256": "0" * 64})
    return report.model_copy(
        update={"integrity_sha256": canonical_hash(empty)}
    )


def assemble_phase5_completion(
    artifacts: Phase5PortableArtifactSet,
    recovery: Phase5RecoveryReport,
    long_recording: Phase5LongRecordingQualification,
    evidence: tuple[Phase5CompletionEvidence, ...],
    *,
    repository_branch: str,
    starting_repository_head: str,
    final_repository_head: str,
    phase_changes_committed_at_audit: bool,
    current_test_count: int,
    current_schema_count: int,
    generated_at: datetime,
    predecessor_report_id: str | None = None,
):
    available = {item.qualification for item in evidence}
    gates = []
    for number, name, keys in GATES:
        required = tuple(QUALIFICATIONS[key] for key in keys)
        missing = tuple(item for item in required if item not in available)
        regression_shortfall = number == 24 and current_test_count < 320
        if not missing and not regression_shortfall:
            gates.append(
                Phase5CompletionGate(
                    gate_number=number,
                    gate_name=name,
                    status=Phase5GateStatus.COMPLETE,
                    evidence_qualifications=required,
                    basis="Required qualified evidence is present and valid.",
                )
            )
        else:
            blockers = tuple(
                [*(f"Pending: {item}." for item in missing)]
                + (
                    ["Full regression count is below the qualified baseline."]
                    if regression_shortfall
                    else []
                )
            )
            gates.append(
                Phase5CompletionGate(
                    gate_number=number,
                    gate_name=name,
                    status=Phase5GateStatus.PENDING,
                    evidence_qualifications=tuple(
                        item for item in required if item in available
                    ),
                    basis="Completion awaits required evidence.",
                    blocking_findings=blockers,
                )
            )
    status = (
        "complete"
        if all(item.status == Phase5GateStatus.COMPLETE for item in gates)
        else "in_progress"
    )
    report = Phase5CompletionReport(
        report_id=typed_id(
            "phase5completion",
            tuple(item.model_dump(mode="json") for item in evidence),
            tuple(item.model_dump(mode="json") for item in gates),
            starting_repository_head,
            final_repository_head,
            predecessor_report_id,
        ),
        predecessor_report_id=predecessor_report_id,
        generated_at=generated_at,
        application_version=__version__,
        contract_version_reported=CONTRACT_VERSION,
        repository_branch=repository_branch,
        starting_repository_head=starting_repository_head,
        final_repository_head=final_repository_head,
        phase_changes_committed_at_audit=phase_changes_committed_at_audit,
        policy=Phase5CompletionPolicy(),
        evidence=evidence,
        measurements=_measurements(
            artifacts,
            recovery,
            long_recording,
            current_test_count,
            current_schema_count,
        ),
        gates=tuple(gates),
        boundary_statements=(
            "An assertion label does not establish truth.",
            "An answer label does not establish adequacy or responsiveness.",
            "A rebuttal label does not establish argumentative success.",
            "Procedural speech does not establish violation, fault, or blame.",
            "Discourse function does not establish speaker intent or credibility.",
            "Unknown and unclassified discourse functions are valid outcomes.",
            "Synthetic mechanics do not establish natural-conversation accuracy.",
        ),
        known_limitations=(
            "Controlled fixtures do not establish general performance.",
            "Long-recording evidence qualifies mechanics, not discourse quality.",
            "Confidence values remain uncalibrated ranking aids.",
        ),
        unresolved_concerns=(),
        status=status,
        integrity_sha256="0" * 64,
    )
    return _seal(report)


def completion_markdown(report):
    lines = [
        "# Phase 5 integrity and completion report",
        "",
        f"Status: **{report.status.upper()}**",
        "",
        "## Exit gates",
        "",
        "| Gate | Status | Evidence |",
        "|---|---|---|",
    ]
    for gate in report.gates:
        lines.append(
            f"| {gate.gate_number}. {gate.gate_name} | "
            f"{gate.status.value} | "
            f"{', '.join(gate.evidence_qualifications) or 'pending'} |"
        )
    lines.extend(
        [
            "",
            "## Evidence boundary",
            "",
            *[f"- {item}" for item in report.boundary_statements],
            "",
            "Measured evaluation, synthetic mechanics, provider proposals, "
            "deterministic rules, and human review remain separate.",
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def validate_phase5_completion(report):
    if _seal(
        report.model_copy(update={"integrity_sha256": "0" * 64})
    ) != report:
        raise Phase5CompletionIntegrityError(
            "completion report integrity is invalid"
        )


def _atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.partial-{uuid.uuid4().hex}")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def persist_phase5_completion(report, reports_root: Path):
    validate_phase5_completion(report)
    root = reports_root.expanduser().resolve()
    machine = root / "phase-5-completion-report.json"
    human = root / "phase-5-completion-report.md"
    if machine.exists() or human.exists():
        if not (machine.exists() and human.exists()):
            raise Phase5CompletionIntegrityError(
                "persisted completion pair is incomplete"
            )
        stored = load_contract(machine.read_bytes(), Phase5CompletionReport)
        if stored == report and human.read_bytes() == completion_markdown(stored):
            return machine, human
        raise Phase5CompletionIntegrityError(
            "persisted completion report conflicts"
        )
    _atomic(machine, canonical_bytes(report))
    _atomic(human, completion_markdown(report))
    return machine, human


def load_phase5_completion(reports_root: Path):
    root = reports_root.expanduser().resolve(strict=True)
    report = load_contract(
        (root / "phase-5-completion-report.json").read_bytes(),
        Phase5CompletionReport,
    )
    validate_phase5_completion(report)
    if (
        root / "phase-5-completion-report.md"
    ).read_bytes() != completion_markdown(report):
        raise Phase5CompletionIntegrityError("completion markdown is stale")
    return report
