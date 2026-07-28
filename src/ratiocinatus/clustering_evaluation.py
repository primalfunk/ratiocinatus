"""Controlled partition evaluation and protected embedding qualification."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

from .clustering import validate_clustering_run
from .diarization import validate_diarization_response
from .clustering_contracts import ClusteringRun
from .clustering_evaluation_contracts import (
    ClusteringEvaluationPolicy,
    ClusteringPairwiseMetrics,
    DiarizationEvaluation,
    DiarizationEvaluationReport,
    DiarizationReference,
    EmbeddingModelQualification,
    EmbeddingQualificationDisposition,
    ReferenceSpeakerAssignment,
)
from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .media import sha256_file
from .phase3_contracts import (
    DiarizationProviderResponse,
    DiarizationRequest,
    DiarizationRun,
    EmbeddingStorageDisposition,
)


class ClusteringEvaluationIntegrityError(RuntimeError):
    """Controlled evaluation evidence is incomplete or incompatible."""


def _atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.partial-{uuid.uuid4().hex}")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _seal(model, payload: dict):
    provisional = model(**payload, integrity_sha256="0" * 64)
    integrity = canonical_hash(
        provisional.model_dump(mode="json", exclude={"integrity_sha256"})
    )
    return model(**payload, integrity_sha256=integrity)


def _integrity_payload(item) -> dict:
    payload = item.model_dump(mode="json")
    payload.pop("integrity_sha256", None)
    return payload


def create_diarization_reference(
    diarization: DiarizationRun,
    assignments: dict[str, str],
    *,
    provenance: tuple[str, ...],
    created_at: datetime | None = None,
) -> DiarizationReference:
    """Create an independent controlled label partition, not identities."""

    known = {item.observation_id for item in diarization.observations}
    if len(assignments) < 2:
        raise ValueError("controlled evaluation requires two observations")
    if not set(assignments).issubset(known):
        raise ValueError("reference assigns an unknown observation")
    if not provenance:
        raise ValueError("reference provenance is required")
    ordered = tuple(
        ReferenceSpeakerAssignment(
            observation_id=observation_id,
            reference_speaker_key=assignments[observation_id],
            basis=(
                "Controlled reference label supplied independently of the "
                "clustering output; not a participant identity."
            ),
        )
        for observation_id in sorted(assignments)
    )
    reference_id = typed_id(
        "diaref",
        diarization.run_id,
        [(item.observation_id, item.reference_speaker_key) for item in ordered],
        provenance,
    )
    return _seal(
        DiarizationReference,
        {
            "reference_id": reference_id,
            "corpus_id": diarization.corpus_id,
            "diarization_run_id": diarization.run_id,
            "source_artifact_sha256": diarization.integrity_sha256,
            "assignments": ordered,
            "provenance": provenance,
            "created_at": created_at or datetime.now(timezone.utc),
        },
    )


def validate_diarization_reference(
    reference: DiarizationReference,
    diarization: DiarizationRun,
) -> None:
    if canonical_hash(_integrity_payload(reference)) != (
        reference.integrity_sha256
    ):
        raise ClusteringEvaluationIntegrityError(
            "diarization reference integrity is invalid"
        )
    if (
        reference.diarization_run_id != diarization.run_id
        or reference.corpus_id != diarization.corpus_id
        or reference.source_artifact_sha256
        != diarization.integrity_sha256
    ):
        raise ClusteringEvaluationIntegrityError(
            "diarization reference lineage is incompatible"
        )
    known = {item.observation_id for item in diarization.observations}
    assigned = {item.observation_id for item in reference.assignments}
    if not assigned.issubset(known):
        raise ClusteringEvaluationIntegrityError(
            "diarization reference contains unknown observations"
        )


def _qualify_embeddings(
    response: DiarizationProviderResponse,
    diarization_root: Path,
) -> dict:
    embeddings = response.embeddings
    model_keys = {
        (
            item.model_space_id,
            item.model_fingerprint,
            item.dimension_count,
            item.numeric_format,
        )
        for item in embeddings
    }
    stored = [
        item
        for item in embeddings
        if item.storage_disposition != EmbeddingStorageDisposition.OMITTED
    ]
    verified = 0
    integrity_failures = []
    for embedding in stored:
        relative = Path(embedding.relative_path or "")
        if relative.is_absolute() or ".." in relative.parts:
            integrity_failures.append(
                f"{embedding.embedding_id}: unsafe protected artifact path"
            )
            continue
        artifact = (diarization_root / relative).resolve()
        try:
            artifact.relative_to(diarization_root)
        except ValueError:
            integrity_failures.append(
                f"{embedding.embedding_id}: protected artifact escapes run root"
            )
            continue
        if (
            not artifact.is_file()
            or artifact.stat().st_size != embedding.byte_size
            or sha256_file(artifact) != embedding.content_sha256
        ):
            integrity_failures.append(
                f"{embedding.embedding_id}: protected artifact integrity failed"
            )
            continue
        verified += 1

    if integrity_failures or len(model_keys) > 1:
        disposition = EmbeddingQualificationDisposition.BLOCKED_INTEGRITY
        comparison_eligible = False
    elif len(embeddings) >= 2 and len(stored) == len(embeddings) == verified:
        disposition = (
            EmbeddingQualificationDisposition
            .QUALIFIED_FOR_CONTROLLED_COMPARISON
        )
        comparison_eligible = True
    elif embeddings:
        disposition = (
            EmbeddingQualificationDisposition.QUALIFIED_METADATA_ONLY
        )
        comparison_eligible = False
    else:
        disposition = (
            EmbeddingQualificationDisposition.INSUFFICIENT_EVIDENCE
        )
        comparison_eligible = False

    model_key = next(iter(model_keys)) if len(model_keys) == 1 else None
    findings = list(integrity_failures)
    if len(model_keys) > 1:
        findings.append(
            "Embedding evidence uses incompatible model spaces or formats."
        )
    if embeddings and not stored:
        findings.append(
            "Embedding metadata is retained but vector values are omitted."
        )
    if not embeddings:
        findings.append("The provider produced no embedding evidence.")

    payload = {
        "qualification_id": typed_id(
            "embedqual",
            response.request_id,
            sorted(model_keys),
            [(item.embedding_id, item.content_sha256) for item in embeddings],
        ),
        "diarization_run_id": "",  # supplied by caller
        "provider_id": response.provider.provider_id,
        "model_space_id": model_key[0] if model_key else None,
        "model_fingerprint": model_key[1] if model_key else None,
        "dimension_count": model_key[2] if model_key else None,
        "numeric_format": model_key[3] if model_key else None,
        "embedding_count": len(embeddings),
        "stored_embedding_count": len(stored),
        "omitted_embedding_count": len(embeddings) - len(stored),
        "integrity_verified_count": verified,
        "comparison_eligible": comparison_eligible,
        "portable_export_permitted": bool(embeddings)
        and all(item.portable_export_permitted for item in embeddings),
        "disposition": disposition,
        "findings": tuple(findings),
        "limitations": (
            "Qualification establishes model-space and artifact controls only.",
            "It does not establish biometric identity accuracy or portability.",
            "Embedding values are never included in this report.",
        ),
    }
    return payload


def evaluate_clustering(
    clustering: ClusteringRun,
    diarization: DiarizationRun,
    response: DiarizationProviderResponse,
    reference: DiarizationReference,
    diarization_root: Path,
    *,
    policy: ClusteringEvaluationPolicy | None = None,
    generated_at: datetime | None = None,
) -> DiarizationEvaluation:
    """Evaluate a provisional partition against independent controlled labels."""

    policy = policy or ClusteringEvaluationPolicy()
    validate_clustering_run(clustering, diarization)
    validate_diarization_reference(reference, diarization)
    if (
        response.request_id != diarization.request_id
        or response.response_id != diarization.response_id
        or response.provider != clustering.provider_capabilities.identity
    ):
        raise ClusteringEvaluationIntegrityError(
            "provider response lineage is incompatible"
        )

    labels = {
        item.observation_id: item.reference_speaker_key
        for item in reference.assignments
    }
    predicted = {
        item.observation_id: item.cluster_id
        for item in clustering.memberships
        if item.canonical
    }
    counts = {
        "tp": 0,
        "fp": 0,
        "fn": 0,
        "tn": 0,
    }
    for left, right in combinations(sorted(labels), 2):
        reference_same = labels[left] == labels[right]
        predicted_same = (
            left in predicted
            and right in predicted
            and predicted[left] == predicted[right]
        )
        if reference_same and predicted_same:
            counts["tp"] += 1
        elif not reference_same and predicted_same:
            counts["fp"] += 1
        elif reference_same:
            counts["fn"] += 1
        else:
            counts["tn"] += 1

    precision_denominator = counts["tp"] + counts["fp"]
    recall_denominator = counts["tp"] + counts["fn"]
    precision = (
        counts["tp"] / precision_denominator
        if precision_denominator
        else None
    )
    recall = (
        counts["tp"] / recall_denominator if recall_denominator else None
    )
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None
        and recall is not None
        and precision + recall
        else None
    )
    known_observations = len(diarization.observations)
    evaluated = len(labels)
    clustered_evaluated = sum(item in predicted for item in labels)
    metrics = ClusteringPairwiseMetrics(
        evaluated_observation_count=evaluated,
        reference_speaker_count=len(set(labels.values())),
        predicted_cluster_count=len({predicted[item] for item in labels if item in predicted}),
        evaluated_pair_count=evaluated * (evaluated - 1) // 2,
        same_speaker_same_cluster_pairs=counts["tp"],
        different_speaker_same_cluster_pairs=counts["fp"],
        same_speaker_different_cluster_pairs=counts["fn"],
        different_speaker_different_cluster_pairs=counts["tn"],
        same_speaker_precision=precision,
        same_speaker_recall=recall,
        same_speaker_f1=f1,
        reference_coverage=evaluated / known_observations,
        clustered_reference_coverage=clustered_evaluated / evaluated,
    )
    qualification_payload = _qualify_embeddings(response, diarization_root)
    qualification_payload["diarization_run_id"] = diarization.run_id
    qualification = _seal(
        EmbeddingModelQualification, qualification_payload
    )
    status = "complete"
    findings = []
    if counts["fp"]:
        findings.append(
            f"{counts['fp']} different-speaker reference pair(s) were "
            "placed in the same provisional cluster."
        )
    if counts["fn"]:
        findings.append(
            f"{counts['fn']} same-speaker reference pair(s) were split "
            "between clusters or left unclustered."
        )
    if clustered_evaluated != evaluated:
        findings.append(
            f"{evaluated - clustered_evaluated} referenced observation(s) "
            "remained unclustered."
        )
    if (
        qualification.disposition
        == EmbeddingQualificationDisposition.BLOCKED_INTEGRITY
    ):
        status = "blocked"
    elif findings or not qualification.comparison_eligible:
        status = "warning"

    evaluation_id = typed_id(
        "diaeval",
        clustering.run_id,
        reference.reference_id,
        policy.model_dump(mode="json"),
    )
    return _seal(
        DiarizationEvaluation,
        {
            "evaluation_id": evaluation_id,
            "clustering_run_id": clustering.run_id,
            "diarization_run_id": diarization.run_id,
            "corpus_id": diarization.corpus_id,
            "reference": reference,
            "policy": policy,
            "metrics": metrics,
            "embedding_qualification": qualification,
            "generated_at": generated_at or datetime.now(timezone.utc),
            "findings": tuple(findings),
            "limitations": (
                "Controlled labels measure a fixture partition, not identity.",
                "Pairwise metrics do not establish performance on other audio.",
                "Unclustered observations are treated as predicted-different.",
            ),
            "status": status,
        },
    )


def validate_clustering_evaluation(
    evaluation: DiarizationEvaluation,
    clustering: ClusteringRun,
    diarization: DiarizationRun,
    report: DiarizationEvaluationReport | None = None,
) -> None:
    if canonical_hash(_integrity_payload(evaluation)) != (
        evaluation.integrity_sha256
    ):
        raise ClusteringEvaluationIntegrityError(
            "clustering evaluation integrity is invalid"
        )
    if (
        evaluation.clustering_run_id != clustering.run_id
        or evaluation.diarization_run_id != diarization.run_id
        or evaluation.corpus_id != diarization.corpus_id
    ):
        raise ClusteringEvaluationIntegrityError(
            "clustering evaluation lineage is incompatible"
        )
    validate_clustering_run(clustering, diarization)
    validate_diarization_reference(evaluation.reference, diarization)
    qualification = evaluation.embedding_qualification
    if canonical_hash(_integrity_payload(qualification)) != (
        qualification.integrity_sha256
    ):
        raise ClusteringEvaluationIntegrityError(
            "embedding qualification integrity is invalid"
        )
    if report is not None and (
        canonical_hash(_integrity_payload(report)) != report.integrity_sha256
        or report.evaluation_id != evaluation.evaluation_id
        or report.clustering_run_id != evaluation.clustering_run_id
        or report.reference_id != evaluation.reference.reference_id
    ):
        raise ClusteringEvaluationIntegrityError(
            "clustering evaluation report integrity or lineage is invalid"
        )


def _report(evaluation: DiarizationEvaluation) -> DiarizationEvaluationReport:
    return _seal(
        DiarizationEvaluationReport,
        {
            "report_id": typed_id(
                "diarevalreport", evaluation.evaluation_id
            ),
            "evaluation_id": evaluation.evaluation_id,
            "clustering_run_id": evaluation.clustering_run_id,
            "reference_id": evaluation.reference.reference_id,
            "generated_at": evaluation.generated_at,
            "evaluated_observation_count": (
                evaluation.metrics.evaluated_observation_count
            ),
            "pairwise_f1": evaluation.metrics.same_speaker_f1,
            "embedding_disposition": (
                evaluation.embedding_qualification.disposition
            ),
            "findings": evaluation.findings,
            "limitations": evaluation.limitations,
            "status": evaluation.status,
        },
    )


def evaluation_report_markdown(
    report: DiarizationEvaluationReport,
) -> str:
    f1 = (
        "unavailable"
        if report.pairwise_f1 is None
        else f"{report.pairwise_f1:.6f}"
    )
    return "\n".join(
        [
            "# Phase 3 controlled clustering-evaluation report",
            "",
            f"Status: **{report.status.upper()}**",
            "",
            f"Evaluation: `{report.evaluation_id}`",
            "",
            f"- Evaluated observations: {report.evaluated_observation_count}",
            f"- Same-speaker pairwise F1: {f1}",
            (
                "- Embedding qualification: "
                f"{report.embedding_disposition.value}"
            ),
            "",
            "Reference speaker keys are controlled labels, not identities.",
            "",
        ]
    )


def evaluate_clustering_artifacts(
    clustering_root: Path,
    diarization_root: Path,
    reference_path: Path,
    destination: Path,
    *,
    policy: ClusteringEvaluationPolicy | None = None,
) -> tuple[
    DiarizationEvaluation,
    DiarizationEvaluationReport,
    Path,
    bool,
]:
    clustering_root = clustering_root.expanduser().resolve(strict=True)
    diarization_root = diarization_root.expanduser().resolve(strict=True)
    reference_path = reference_path.expanduser().resolve(strict=True)
    destination = destination.expanduser().resolve()
    protected_roots = (clustering_root, diarization_root)
    if any(
        destination == root or root in destination.parents
        for root in protected_roots
    ):
        raise ValueError("evaluation output must not modify source evidence")

    clustering = load_contract(
        (clustering_root / "clustering.json").read_bytes(), ClusteringRun
    )
    diarization = load_contract(
        (diarization_root / "run.json").read_bytes(), DiarizationRun
    )
    request = load_contract(
        (diarization_root / "request.json").read_bytes(),
        DiarizationRequest,
    )
    response = load_contract(
        (diarization_root / "response.json").read_bytes(),
        DiarizationProviderResponse,
    )
    validate_diarization_response(response, request, diarization_root)
    reference = load_contract(
        reference_path.read_bytes(), DiarizationReference
    )
    expected = evaluate_clustering(
        clustering,
        diarization,
        response,
        reference,
        diarization_root,
        policy=policy,
    )
    root = destination / "clustering-evaluations" / expected.evaluation_id
    evaluation_path = root / "evaluation.json"
    report_path = root / "report.json"
    existing = (evaluation_path.exists(), report_path.exists())
    if any(existing) and not all(existing):
        raise ClusteringEvaluationIntegrityError(
            "cached clustering evaluation is incomplete"
        )
    if all(existing):
        stored = load_contract(
            evaluation_path.read_bytes(), DiarizationEvaluation
        )
        report = load_contract(
            report_path.read_bytes(), DiarizationEvaluationReport
        )
        validate_clustering_evaluation(
            stored, clustering, diarization, report
        )
        if (
            stored.evaluation_id != expected.evaluation_id
            or stored.metrics != expected.metrics
            or stored.embedding_qualification
            != expected.embedding_qualification
            or report.evaluation_id != stored.evaluation_id
        ):
            raise ClusteringEvaluationIntegrityError(
                "cached clustering evaluation is incompatible"
            )
        return stored, report, root, True

    report = _report(expected)
    _atomic(evaluation_path, canonical_bytes(expected))
    _atomic(report_path, canonical_bytes(report))
    _atomic(
        root / "report.md",
        evaluation_report_markdown(report).encode("utf-8"),
    )
    return expected, report, root, False
