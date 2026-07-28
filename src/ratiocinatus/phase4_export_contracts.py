"""Portable Phase 4 corpus export contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract, Sha256
from .phase4_contracts import PHASE4_FORMAT_VERSION

PHASE4_EXPORT_POLICY_VERSION = "1.0.0"


class Phase4ExportPolicy(Contract):
    policy_version: Literal["1.0.0"] = PHASE4_EXPORT_POLICY_VERSION
    canonical_json: Literal[True] = True
    relative_paths_only: Literal[True] = True
    include_schema_inventory: Literal[True] = True
    provider_execution_required_for_inspection: Literal[False] = False
    source_media_redistributed: Literal[False] = False
    validate_every_artifact_before_export: Literal[True] = True


class Phase4ExportEntry(Contract):
    relative_path: str = Field(
        pattern=r"^(artifacts|schemas)/[A-Za-z0-9_.-]+\.json$"
    )
    artifact_kind: str = Field(min_length=1)
    sha256: Sha256
    byte_size: int = Field(gt=0)
    schema_name: str = Field(min_length=1)


class Phase4ExportManifest(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    export_id: str = Field(pattern=r"^phase4export_[a-f0-9]{32}$")
    utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    transcript_view_bundle_id: str = Field(
        pattern=r"^utteranceviewbundle_[a-f0-9]{32}$"
    )
    context_bundle_id: str = Field(pattern=r"^contextbundle_[a-f0-9]{32}$")
    policy: Phase4ExportPolicy
    prior_phase_relative_references: tuple[str, ...] = Field(min_length=1)
    entries: tuple[Phase4ExportEntry, ...] = Field(min_length=1)
    application_version: str = Field(min_length=1)
    contract_version: str = Field(min_length=1)
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def export_inventory_is_unique_and_relative(self) -> "Phase4ExportManifest":
        paths = [item.relative_path for item in self.entries]
        if len(paths) != len(set(paths)):
            raise ValueError("export paths must be unique")
        if any(
            value.startswith(("/", "\\"))
            or ":" in value
            for value in self.prior_phase_relative_references
        ):
            raise ValueError("prior-phase export references must be relative")
        return self


class Phase4ExportValidationReport(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    report_id: str = Field(pattern=r"^phase4exportreport_[a-f0-9]{32}$")
    export_id: str = Field(pattern=r"^phase4export_[a-f0-9]{32}$")
    validated_at: datetime
    artifact_count: int = Field(ge=0)
    schema_count: int = Field(ge=0)
    missing_paths: tuple[str, ...] = ()
    digest_mismatch_paths: tuple[str, ...] = ()
    strict_load_failures: tuple[str, ...] = ()
    provider_execution_used: Literal[False] = False
    status: Literal["valid", "invalid"]
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def validation_status_is_coherent(self) -> "Phase4ExportValidationReport":
        failed = bool(
            self.missing_paths
            or self.digest_mismatch_paths
            or self.strict_load_failures
        )
        if (self.status == "invalid") != failed:
            raise ValueError("export validation status disagrees with findings")
        return self


PHASE4_EXPORT_CONTRACT_MODELS = (
    Phase4ExportPolicy,
    Phase4ExportEntry,
    Phase4ExportManifest,
    Phase4ExportValidationReport,
)
