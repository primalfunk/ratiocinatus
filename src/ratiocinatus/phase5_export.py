"""Provider-free portable Phase 5 discourse export and reload."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .argument_relation_construction import validate_argument_relations
from .contracts import CONTRACT_VERSION
from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase5_argument_relation_contracts import (
    ArgumentRelationReport,
    ArgumentRelationRun,
)
from .phase5_consolidation_contracts import (
    DiscourseConsolidationReport,
    DiscourseConsolidationRun,
)
from .phase5_contracts import (
    DiscourseCorpus,
    Phase5IntegrityResult,
)
from .phase5_evaluation_contracts import (
    Phase5ControlledReference,
    Phase5DiscourseEvaluation,
    Phase5EvaluationReport,
)
from .phase5_export_contracts import (
    Phase5ExportEntry,
    Phase5ExportManifest,
    Phase5ExportPolicy,
    Phase5ExportValidationReport,
)
from .phase5_lexical_example_quotation_contracts import (
    LexicalExampleQuotationReport,
    LexicalExampleQuotationRun,
)
from .phase5_procedural_state_contracts import (
    ProceduralStateReport,
    ProceduralStateRun,
)
from .phase5_question_answer_contracts import (
    QuestionAnswerReport,
    QuestionAnswerRun,
)
from .phase5_review_contracts import (
    DiscoursePropagationReport,
    DiscoursePropagationRun,
    DiscourseReviewLedger,
    DiscourseReviewQueue,
)
from .version import __version__


class Phase5ExportIntegrityError(RuntimeError):
    """Portable discourse export is corrupt, incomplete, or incompatible."""


@dataclass(frozen=True)
class Phase5PortableArtifactSet:
    consolidation: DiscourseConsolidationRun
    corpus: DiscourseCorpus
    consolidation_report: DiscourseConsolidationReport
    question_answers: QuestionAnswerRun
    question_answer_report: QuestionAnswerReport
    argument_relations: ArgumentRelationRun
    argument_relation_report: ArgumentRelationReport
    lexical_structures: LexicalExampleQuotationRun
    lexical_structure_report: LexicalExampleQuotationReport
    procedural_state: ProceduralStateRun
    procedural_state_report: ProceduralStateReport
    review_ledger: DiscourseReviewLedger
    review_queue: DiscourseReviewQueue
    propagation: DiscoursePropagationRun
    propagation_report: DiscoursePropagationReport
    controlled_reference: Phase5ControlledReference
    evaluation: Phase5DiscourseEvaluation
    evaluation_report: Phase5EvaluationReport
    integrity_result: Phase5IntegrityResult


_ARTIFACT_TYPES = {
    item.__name__: item
    for item in (
        DiscourseConsolidationRun,
        DiscourseCorpus,
        DiscourseConsolidationReport,
        QuestionAnswerRun,
        QuestionAnswerReport,
        ArgumentRelationRun,
        ArgumentRelationReport,
        LexicalExampleQuotationRun,
        LexicalExampleQuotationReport,
        ProceduralStateRun,
        ProceduralStateReport,
        DiscourseReviewLedger,
        DiscourseReviewQueue,
        DiscoursePropagationRun,
        DiscoursePropagationReport,
        Phase5ControlledReference,
        Phase5DiscourseEvaluation,
        Phase5EvaluationReport,
        Phase5IntegrityResult,
    )
}

_VIEWS = (
    "raw_candidate_view",
    "canonical_machine_view",
    "reviewed_view",
    "alternatives_view",
    "question_answer_view",
    "objection_rebuttal_view",
    "concession_qualification_view",
    "definition_example_view",
    "procedural_view",
    "unresolved_view",
    "source_grounded_reading_view",
)


def _atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.partial-{uuid.uuid4().hex}")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _seal(model, payload):
    provisional = model(**payload, integrity_sha256="0" * 64)
    return provisional.model_copy(
        update={
            "integrity_sha256": canonical_hash(
                provisional.model_dump(
                    mode="json", exclude={"integrity_sha256"}
                )
            )
        }
    )


def _verify(item, label: str) -> None:
    expected_without_field = canonical_hash(
        item.model_dump(mode="json", exclude={"integrity_sha256"})
    )
    expected_zeroed_field = canonical_hash(
        item.model_copy(update={"integrity_sha256": "0" * 64})
    )
    if item.integrity_sha256 not in {
        expected_without_field,
        expected_zeroed_field,
    }:
        raise Phase5ExportIntegrityError(f"{label} integrity is invalid")


def _inventory(artifacts: Phase5PortableArtifactSet):
    return tuple(
        (name.replace("_", "-"), value)
        for name, value in artifacts.__dict__.items()
    )


def _lineage_values(item):
    values = []
    for name in (
        "discourse_corpus_id",
        "predecessor_discourse_corpus_id",
    ):
        value = getattr(item, name, None)
        if value is not None:
            values.append(value)
    return tuple(values)


def validate_phase5_portable_artifacts(
    artifacts: Phase5PortableArtifactSet,
) -> None:
    corpus_id = artifacts.corpus.corpus_id
    phase4_id = artifacts.corpus.phase4_utterance_corpus_id
    for name, item in _inventory(artifacts):
        _verify(item, name)
        values = _lineage_values(item)
        if values and any(value != corpus_id for value in values):
            raise Phase5ExportIntegrityError(
                f"{name} uses a mixed discourse corpus version"
            )
    if (
        artifacts.consolidation.discourse_corpus_id != corpus_id
        or artifacts.review_ledger.discourse_corpus_id != corpus_id
        or artifacts.review_queue.discourse_corpus_id != corpus_id
        or artifacts.evaluation.discourse_corpus_id != corpus_id
        or artifacts.propagation.predecessor_discourse_corpus_id != corpus_id
    ):
        raise Phase5ExportIntegrityError(
            "portable artifacts use mixed discourse corpus versions"
        )
    if any(
        value != phase4_id
        for value in (
            artifacts.consolidation.phase4_utterance_corpus_id,
            artifacts.review_ledger.phase4_utterance_corpus_id,
            artifacts.propagation.predecessor_phase4_corpus_id,
            artifacts.controlled_reference.phase4_utterance_corpus_id,
        )
    ):
        raise Phase5ExportIntegrityError(
            "portable artifacts use mixed Phase 4 corpus versions"
        )
    pairs = (
        (
            artifacts.question_answers.question_answer_run_id,
            artifacts.question_answer_report.question_answer_run_id,
        ),
        (
            artifacts.argument_relations.argument_relation_run_id,
            artifacts.argument_relation_report.argument_relation_run_id,
        ),
        (
            artifacts.lexical_structures.construction_run_id,
            artifacts.lexical_structure_report.construction_run_id,
        ),
        (
            artifacts.procedural_state.procedural_state_run_id,
            artifacts.procedural_state_report.procedural_state_run_id,
        ),
        (
            artifacts.propagation.propagation_run_id,
            artifacts.propagation_report.propagation_run_id,
        ),
        (
            artifacts.evaluation.evaluation_id,
            artifacts.evaluation_report.evaluation_id,
        ),
    )
    if any(left != right for left, right in pairs):
        raise Phase5ExportIntegrityError(
            "portable artifact report lineage is incompatible"
        )
    if artifacts.review_queue.ledger_id != artifacts.review_ledger.ledger_id:
        raise Phase5ExportIntegrityError(
            "review queue does not use the exported ledger"
        )


def export_phase5_corpus(
    artifacts: Phase5PortableArtifactSet,
    destination: Path,
    schemas_root: Path,
    *,
    prior_phase_relative_references: tuple[str, ...] = (
        "../phase-4/utterance-corpus.json",
        "../phase-4/context-windows.json",
        "../phase-4/quotation-evidence.json",
    ),
    policy: Phase5ExportPolicy | None = None,
    created_at: datetime | None = None,
):
    """Export every discourse view without invoking a provider."""
    validate_phase5_portable_artifacts(artifacts)
    policy = policy or Phase5ExportPolicy()
    schemas_root = schemas_root.expanduser().resolve(strict=True)
    schema_paths = tuple(
        sorted(schemas_root.glob("*.schema.json"), key=lambda item: item.name)
    )
    if policy.include_schema_inventory and not schema_paths:
        raise Phase5ExportIntegrityError("schema inventory is empty")
    artifact_payloads = tuple(
        (
            f"artifacts/{name}.json",
            type(item).__name__,
            canonical_bytes(item),
        )
        for name, item in _inventory(artifacts)
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
        "phase5export",
        artifacts.corpus.corpus_id,
        fingerprint,
        policy.model_dump(mode="json"),
    )
    root = destination.expanduser().resolve() / "phase5-export" / export_id
    entries = tuple(
        Phase5ExportEntry(
            relative_path=path,
            artifact_kind=(
                "schema" if path.startswith("schemas/") else "phase5_artifact"
            ),
            sha256=_sha(data),
            byte_size=len(data),
            schema_name=schema,
        )
        for path, schema, data in (*artifact_payloads, *schema_payloads)
    )
    manifest = _seal(
        Phase5ExportManifest,
        {
            "export_id": export_id,
            "discourse_corpus_id": artifacts.corpus.corpus_id,
            "phase4_utterance_corpus_id": (
                artifacts.corpus.phase4_utterance_corpus_id
            ),
            "policy": policy,
            "included_views": _VIEWS,
            "prior_phase_relative_references": (
                prior_phase_relative_references
            ),
            "entries": entries,
            "application_version": __version__,
            "contract_version": CONTRACT_VERSION,
            "created_at": created_at or artifacts.corpus.created_at,
        },
    )
    manifest_path = root / "manifest.json"
    validation_path = root / "validation-report.json"
    if manifest_path.exists() or validation_path.exists():
        if not (manifest_path.exists() and validation_path.exists()):
            raise Phase5ExportIntegrityError("portable export is incomplete")
        stored, report = load_phase5_export(root)
        if stored != manifest or report.status != "valid":
            raise Phase5ExportIntegrityError(
                "portable export cache is incompatible"
            )
        return stored, report, root, True
    for path, _, data in (*artifact_payloads, *schema_payloads):
        _atomic(root / Path(path), data)
    _atomic(manifest_path, canonical_bytes(manifest))
    report = validate_phase5_export(root, validated_at=manifest.created_at)
    _atomic(validation_path, canonical_bytes(report))
    return manifest, report, root, False


def validate_phase5_export(root: Path, *, validated_at: datetime | None = None):
    """Digest-check, strict-load, and lineage-check every exported artifact."""
    root = root.expanduser().resolve(strict=True)
    manifest = load_contract(
        (root / "manifest.json").read_bytes(), Phase5ExportManifest
    )
    _verify(manifest, "Phase 5 export manifest")
    missing, mismatches, failures, mixed = [], [], [], []
    for entry in manifest.entries:
        path = root / Path(entry.relative_path)
        if not path.exists():
            missing.append(entry.relative_path)
            continue
        data = path.read_bytes()
        if len(data) != entry.byte_size or _sha(data) != entry.sha256:
            mismatches.append(entry.relative_path)
            continue
        if entry.artifact_kind == "schema":
            try:
                json.loads(data)
            except Exception:
                failures.append(entry.relative_path)
            continue
        model = _ARTIFACT_TYPES.get(entry.schema_name)
        if model is None:
            failures.append(entry.relative_path)
            continue
        try:
            loaded = load_contract(data, model)
            _verify(loaded, entry.schema_name)
            if any(
                value != manifest.discourse_corpus_id
                for value in _lineage_values(loaded)
            ):
                mixed.append(entry.relative_path)
            phase4_value = getattr(
                loaded, "phase4_utterance_corpus_id", None
            )
            predecessor_phase4 = getattr(
                loaded, "predecessor_phase4_corpus_id", None
            )
            for value in (phase4_value, predecessor_phase4):
                if (
                    value is not None
                    and value != manifest.phase4_utterance_corpus_id
                ):
                    mixed.append(entry.relative_path)
        except Exception:
            failures.append(entry.relative_path)
    missing = tuple(dict.fromkeys(missing))
    mismatches = tuple(dict.fromkeys(mismatches))
    failures = tuple(dict.fromkeys(failures))
    mixed = tuple(dict.fromkeys(mixed))
    status = (
        "invalid"
        if missing or mismatches or failures or mixed
        else "valid"
    )
    return _seal(
        Phase5ExportValidationReport,
        {
            "report_id": typed_id(
                "phase5exportreport",
                manifest.export_id,
                missing,
                mismatches,
                failures,
                mixed,
            ),
            "export_id": manifest.export_id,
            "validated_at": validated_at or manifest.created_at,
            "artifact_count": sum(
                item.artifact_kind == "phase5_artifact"
                for item in manifest.entries
            ),
            "schema_count": sum(
                item.artifact_kind == "schema"
                for item in manifest.entries
            ),
            "missing_paths": missing,
            "digest_mismatch_paths": mismatches,
            "strict_load_failures": failures,
            "mixed_corpus_version_paths": mixed,
            "status": status,
        },
    )


def load_phase5_export(root: Path):
    root = root.expanduser().resolve(strict=True)
    manifest = load_contract(
        (root / "manifest.json").read_bytes(), Phase5ExportManifest
    )
    report = load_contract(
        (root / "validation-report.json").read_bytes(),
        Phase5ExportValidationReport,
    )
    _verify(manifest, "Phase 5 export manifest")
    _verify(report, "Phase 5 export validation report")
    current = validate_phase5_export(root, validated_at=report.validated_at)
    if current != report:
        raise Phase5ExportIntegrityError(
            "portable export validation is stale"
        )
    return manifest, report


def reload_phase5_export(root: Path) -> dict[str, object]:
    """Reload all exported discourse artifacts without provider execution."""
    manifest, report = load_phase5_export(root)
    if report.status != "valid":
        raise Phase5ExportIntegrityError("portable export is invalid")
    resolved = root.expanduser().resolve(strict=True)
    artifacts = {}
    for entry in manifest.entries:
        if entry.artifact_kind != "phase5_artifact":
            continue
        model = _ARTIFACT_TYPES[entry.schema_name]
        artifacts[entry.relative_path] = load_contract(
            (resolved / entry.relative_path).read_bytes(), model
        )
    return artifacts
