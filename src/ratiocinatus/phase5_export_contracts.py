"""Provider-free portable Phase 5 discourse export contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract, Sha256
from .phase5_contracts import PHASE5_FORMAT_VERSION

PHASE5_EXPORT_POLICY_VERSION = "1.0.0"


class Phase5ExportPolicy(Contract):
    policy_version: Literal["1.0.0"] = PHASE5_EXPORT_POLICY_VERSION
    canonical_json: Literal[True] = True
    relative_paths_only: Literal[True] = True
    include_schema_inventory: Literal[True] = True
    include_all_discourse_views: Literal[True] = True
    provider_execution_required_for_inspection: Literal[False] = False
    source_media_redistributed: Literal[False] = False
    validate_every_artifact_before_export: Literal[True] = True
    mixed_corpus_versions: Literal["prohibited"] = "prohibited"


class Phase5ExportEntry(Contract):
    relative_path: str = Field(
        pattern=r"^(artifacts|schemas)/[A-Za-z0-9_.-]+\.json$"
    )
    artifact_kind: Literal["phase5_artifact", "schema"]
    sha256: Sha256
    byte_size: int = Field(gt=0)
    schema_name: str = Field(min_length=1)


class Phase5ExportManifest(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    export_id: str = Field(pattern=r"^phase5export_[a-f0-9]{32}$")
    discourse_corpus_id: str = Field(pattern=r"^discoursecorpus_[a-f0-9]{32}$")
    phase4_utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    policy: Phase5ExportPolicy
    included_views: tuple[str, ...] = Field(min_length=11)
    prior_phase_relative_references: tuple[str, ...] = Field(min_length=1)
    entries: tuple[Phase5ExportEntry, ...] = Field(min_length=1)
    application_version: str = Field(min_length=1)
    contract_version: str = Field(min_length=1)
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def inventory_is_unique_and_relative(self) -> "Phase5ExportManifest":
        paths = [item.relative_path for item in self.entries]
        if len(paths) != len(set(paths)):
            raise ValueError("export paths must be unique")
        if len(self.included_views) != len(set(self.included_views)):
            raise ValueError("export views must be unique")
        if any(
            value.startswith(("/", "\\")) or ":" in value
            for value in self.prior_phase_relative_references
        ):
            raise ValueError("prior-phase references must be relative")
        return self


class Phase5ExportValidationReport(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    report_id: str = Field(pattern=r"^phase5exportreport_[a-f0-9]{32}$")
    export_id: str = Field(pattern=r"^phase5export_[a-f0-9]{32}$")
    validated_at: datetime
    artifact_count: int = Field(ge=0)
    schema_count: int = Field(ge=0)
    missing_paths: tuple[str, ...] = ()
    digest_mismatch_paths: tuple[str, ...] = ()
    strict_load_failures: tuple[str, ...] = ()
    mixed_corpus_version_paths: tuple[str, ...] = ()
    provider_execution_used: Literal[False] = False
    status: Literal["valid", "invalid"]
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def status_matches_findings(self) -> "Phase5ExportValidationReport":
        failed = bool(
            self.missing_paths
            or self.digest_mismatch_paths
            or self.strict_load_failures
            or self.mixed_corpus_version_paths
        )
        if (self.status == "invalid") != failed:
            raise ValueError("export validation status disagrees with findings")
        return self


PHASE5_EXPORT_CONTRACT_MODELS = (
    Phase5ExportPolicy,
    Phase5ExportEntry,
    Phase5ExportManifest,
    Phase5ExportValidationReport,
)
