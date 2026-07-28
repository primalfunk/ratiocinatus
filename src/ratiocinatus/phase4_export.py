"""Provider-free portable Phase 4 corpus export."""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime
from pathlib import Path

from .context_window_contracts import ContextWindowBundle
from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase4_contracts import UtteranceAnalysisRun, UtteranceCorpus, UtteranceRun
from .phase4_evaluation_contracts import (
    Phase4ControlledReference,
    Phase4UtteranceEvaluation,
)
from .phase4_export_contracts import (
    Phase4ExportEntry,
    Phase4ExportManifest,
    Phase4ExportPolicy,
    Phase4ExportValidationReport,
)
from .phase4_propagation import (
    Phase4ArtifactSet,
    validate_phase4_artifact_set,
)
from .phase4_review_contracts import (
    Phase4PropagationRun,
    ReviewQueueReport,
    UtteranceReviewLedger,
)
from .quotation_contracts import QuotationEvidenceRun
from .turn_repair_contracts import TurnRepairRun
from .utterance_relation_contracts import UtteranceRelationRun
from .utterance_view_contracts import SpeakerAttributedTranscriptBundle
from .version import __version__
from .contracts import CONTRACT_VERSION


class Phase4ExportIntegrityError(RuntimeError):
    """Portable export is corrupt, incomplete, or incompatible."""


_ARTIFACT_TYPES = {
    "UtteranceRun": UtteranceRun,
    "UtteranceCorpus": UtteranceCorpus,
    "UtteranceAnalysisRun": UtteranceAnalysisRun,
    "UtteranceRelationRun": UtteranceRelationRun,
    "TurnRepairRun": TurnRepairRun,
    "QuotationEvidenceRun": QuotationEvidenceRun,
    "SpeakerAttributedTranscriptBundle": SpeakerAttributedTranscriptBundle,
    "ContextWindowBundle": ContextWindowBundle,
    "Phase4PropagationRun": Phase4PropagationRun,
    "UtteranceReviewLedger": UtteranceReviewLedger,
    "ReviewQueueReport": ReviewQueueReport,
    "Phase4ControlledReference": Phase4ControlledReference,
    "Phase4UtteranceEvaluation": Phase4UtteranceEvaluation,
}


def _atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.partial-{uuid.uuid4().hex}")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _seal(model, payload: dict):
    provisional = model(**payload, integrity_sha256="0" * 64)
    integrity = canonical_hash(
        provisional.model_dump(mode="json", exclude={"integrity_sha256"})
    )
    return model(**payload, integrity_sha256=integrity)


def _verify_seal(item, label: str) -> None:
    payload = item.model_dump(mode="json", exclude={"integrity_sha256"})
    if canonical_hash(payload) != item.integrity_sha256:
        raise Phase4ExportIntegrityError(f"{label} integrity is invalid")


def _artifact_inventory(
    artifacts: Phase4ArtifactSet,
    *,
    propagation: Phase4PropagationRun | None,
    review_ledger: UtteranceReviewLedger | None,
    review_queue: ReviewQueueReport | None,
    reference: Phase4ControlledReference | None,
    evaluation: Phase4UtteranceEvaluation | None,
) -> tuple[tuple[str, object], ...]:
    values: list[tuple[str, object]] = [
        ("utterance-run", artifacts.utterance_run),
        ("utterance-corpus", artifacts.corpus),
        ("utterance-analysis", artifacts.analysis),
        ("utterance-relations", artifacts.relations),
        ("turn-repair", artifacts.repair),
        ("quotation-evidence", artifacts.quotation),
        ("transcript-views", artifacts.transcript_views),
        ("context-windows", artifacts.context_windows),
    ]
    for name, item in (
        ("propagation", propagation),
        ("review-ledger", review_ledger),
        ("review-queue", review_queue),
        ("controlled-reference", reference),
        ("evaluation", evaluation),
    ):
        if item is not None:
            values.append((name, item))
    return tuple(values)


def export_phase4_corpus(
    artifacts: Phase4ArtifactSet,
    destination: Path,
    schemas_root: Path,
    *,
    propagation: Phase4PropagationRun | None = None,
    review_ledger: UtteranceReviewLedger | None = None,
    review_queue: ReviewQueueReport | None = None,
    reference: Phase4ControlledReference | None = None,
    evaluation: Phase4UtteranceEvaluation | None = None,
    prior_phase_relative_references: tuple[str, ...] = (
        "../phase-2/transcript-assembly.json",
        "../phase-3/diarization-run.json",
        "../phase-3/identity-view.json",
    ),
    policy: Phase4ExportPolicy | None = None,
    created_at: datetime | None = None,
) -> tuple[
    Phase4ExportManifest,
    Phase4ExportValidationReport,
    Path,
    bool,
]:
    """Export a fully inspectable corpus without invoking any provider."""
    validate_phase4_artifact_set(artifacts)
    policy = policy or Phase4ExportPolicy()
    inventory = _artifact_inventory(
        artifacts,
        propagation=propagation,
        review_ledger=review_ledger,
        review_queue=review_queue,
        reference=reference,
        evaluation=evaluation,
    )
    for _, item in inventory:
        _verify_seal(item, type(item).__name__)
    schemas_root = schemas_root.expanduser().resolve(strict=True)
    schema_paths = tuple(
        sorted(schemas_root.glob("*.schema.json"), key=lambda item: item.name)
    )
    if policy.include_schema_inventory and not schema_paths:
        raise Phase4ExportIntegrityError("schema inventory is empty")
    artifact_payloads = tuple(
        (
            f"artifacts/{name}.json",
            type(item).__name__,
            canonical_bytes(item),
        )
        for name, item in inventory
    )
    schema_payloads = tuple(
        (
            f"schemas/{path.name}",
            path.name.removesuffix(".schema.json"),
            path.read_bytes(),
        )
        for path in schema_paths
    )
    fingerprint = tuple(
        (path, schema, _sha(data))
        for path, schema, data in (*artifact_payloads, *schema_payloads)
    )
    export_id = typed_id(
        "phase4export",
        artifacts.corpus.corpus_id,
        artifacts.transcript_views.bundle_id,
        artifacts.context_windows.context_bundle_id,
        fingerprint,
        policy.model_dump(mode="json"),
    )
    root = destination.expanduser().resolve() / "phase4-export" / export_id
    entries = tuple(
        Phase4ExportEntry(
            relative_path=path,
            artifact_kind=(
                "schema" if path.startswith("schemas/") else "phase4_artifact"
            ),
            sha256=_sha(data),
            byte_size=len(data),
            schema_name=schema,
        )
        for path, schema, data in (*artifact_payloads, *schema_payloads)
    )
    manifest = _seal(
        Phase4ExportManifest,
        {
            "export_id": export_id,
            "utterance_corpus_id": artifacts.corpus.corpus_id,
            "transcript_view_bundle_id": artifacts.transcript_views.bundle_id,
            "context_bundle_id": (
                artifacts.context_windows.context_bundle_id
            ),
            "policy": policy,
            "prior_phase_relative_references": (
                prior_phase_relative_references
            ),
            "entries": entries,
            "application_version": __version__,
            "contract_version": CONTRACT_VERSION,
            "created_at": created_at or artifacts.context_windows.created_at,
        },
    )
    manifest_path = root / "manifest.json"
    validation_path = root / "validation-report.json"
    if manifest_path.exists() or validation_path.exists():
        if not (manifest_path.exists() and validation_path.exists()):
            raise Phase4ExportIntegrityError("portable export is incomplete")
        stored = load_contract(
            manifest_path.read_bytes(), Phase4ExportManifest
        )
        report = validate_phase4_export(root)
        if stored != manifest or report.status != "valid":
            raise Phase4ExportIntegrityError(
                "portable export cache is incompatible"
            )
        return stored, report, root, True
    for path, _, data in (*artifact_payloads, *schema_payloads):
        _atomic(root / Path(path), data)
    _atomic(manifest_path, canonical_bytes(manifest))
    report = validate_phase4_export(
        root, validated_at=manifest.created_at
    )
    _atomic(validation_path, canonical_bytes(report))
    return manifest, report, root, False


def validate_phase4_export(
    root: Path,
    *,
    validated_at: datetime | None = None,
) -> Phase4ExportValidationReport:
    """Strict-load and digest-check an export without provider execution."""
    root = root.expanduser().resolve(strict=True)
    manifest = load_contract(
        (root / "manifest.json").read_bytes(), Phase4ExportManifest
    )
    _verify_seal(manifest, "Phase 4 export manifest")
    missing = []
    mismatches = []
    failures = []
    for entry in manifest.entries:
        path = root / Path(entry.relative_path)
        if not path.exists():
            missing.append(entry.relative_path)
            continue
        data = path.read_bytes()
        if len(data) != entry.byte_size or _sha(data) != entry.sha256:
            mismatches.append(entry.relative_path)
            continue
        if entry.artifact_kind == "phase4_artifact":
            model = _ARTIFACT_TYPES.get(entry.schema_name)
            if model is None:
                failures.append(entry.relative_path)
                continue
            try:
                loaded = load_contract(data, model)
                _verify_seal(loaded, entry.schema_name)
            except Exception:
                failures.append(entry.relative_path)
        else:
            try:
                __import__("json").loads(data)
            except Exception:
                failures.append(entry.relative_path)
    status = "invalid" if missing or mismatches or failures else "valid"
    return _seal(
        Phase4ExportValidationReport,
        {
            "report_id": typed_id(
                "phase4exportreport",
                manifest.export_id,
                tuple(missing),
                tuple(mismatches),
                tuple(failures),
            ),
            "export_id": manifest.export_id,
            "validated_at": validated_at or manifest.created_at,
            "artifact_count": sum(
                item.artifact_kind == "phase4_artifact"
                for item in manifest.entries
            ),
            "schema_count": sum(
                item.artifact_kind == "schema"
                for item in manifest.entries
            ),
            "missing_paths": tuple(missing),
            "digest_mismatch_paths": tuple(mismatches),
            "strict_load_failures": tuple(failures),
            "status": status,
        },
    )


def load_phase4_export(
    root: Path,
) -> tuple[Phase4ExportManifest, Phase4ExportValidationReport]:
    root = root.expanduser().resolve(strict=True)
    manifest = load_contract(
        (root / "manifest.json").read_bytes(), Phase4ExportManifest
    )
    report = load_contract(
        (root / "validation-report.json").read_bytes(),
        Phase4ExportValidationReport,
    )
    _verify_seal(manifest, "Phase 4 export manifest")
    _verify_seal(report, "Phase 4 export validation report")
    current = validate_phase4_export(root, validated_at=report.validated_at)
    if current != report:
        raise Phase4ExportIntegrityError("portable export validation is stale")
    return manifest, report
