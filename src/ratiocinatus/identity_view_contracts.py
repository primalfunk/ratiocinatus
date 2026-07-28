"""Deterministic multi-layer participant identity-view contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract, Sha256

IDENTITY_VIEW_FORMAT_VERSION = "1.0.0"
IDENTITY_VIEW_POLICY_VERSION = "1.0.0"


class IdentityViewKind(str, Enum):
    RAW_PROVIDER_DIARIZATION = "raw_provider_diarization"
    CANONICAL_MACHINE_DIARIZATION = "canonical_machine_diarization"
    CLUSTER_CONSISTENCY = "cluster_consistency"
    UNRESOLVED_SPEAKER = "unresolved_speaker"
    IDENTITY_HYPOTHESIS = "identity_hypothesis"
    REFERENCE_COMPARISON = "reference_comparison"
    MANUALLY_REVIEWED_IDENTITY = "manually_reviewed_identity"
    BINDING_HISTORY = "binding_history"


class IdentityViewDisposition(str, Enum):
    INFORMATIONAL = "informational"
    MACHINE_CLUSTER = "machine_cluster"
    REVIEWED_IDENTITY = "reviewed_identity"
    UNKNOWN = "unknown"
    REJECTED = "rejected"
    CONFLICTED = "conflicted"
    UNRESOLVED_PROPOSAL = "unresolved_proposal"
    INVALID_EVIDENCE = "invalid_evidence"


class IdentityViewPolicy(Contract):
    policy_version: Literal["1.0.0"] = IDENTITY_VIEW_POLICY_VERSION
    layer_count: Literal[8] = 8
    manual_label_prefix: Literal["REVIEWED: "] = "REVIEWED: "
    unknown_label: Literal["REVIEWED: UNKNOWN"] = "REVIEWED: UNKNOWN"
    conflict_label: Literal["REVIEWED: CONFLICT"] = "REVIEWED: CONFLICT"
    preserve_machine_label: Literal[True] = True
    silent_conflict_resolution: Literal["prohibited"] = "prohibited"
    source_artifact_mutation: Literal["prohibited"] = "prohibited"


class IdentityViewEntry(Contract):
    entry_id: str = Field(pattern=r"^identityviewentry_[a-f0-9]{32}$")
    target_artifact_id: str = Field(min_length=1)
    target_kind: Literal[
        "provider_observation",
        "observation",
        "speaker_turn",
        "cluster",
        "identity_hypothesis",
        "reference_comparison",
        "manual_binding",
    ]
    disposition: IdentityViewDisposition
    original_machine_label: str | None = None
    reviewed_label: str | None = None
    identity_ids: tuple[str, ...] = ()
    evidence_references: tuple[str, ...] = ()
    binding_ids: tuple[str, ...] = ()
    findings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def reviewed_labels_are_visibly_distinct(self) -> "IdentityViewEntry":
        if (
            self.reviewed_label is not None
            and not self.reviewed_label.startswith("REVIEWED: ")
        ):
            raise ValueError("reviewed identity labels require visible prefix")
        if len(self.identity_ids) != len(set(self.identity_ids)):
            raise ValueError("identity-view identities must be unique")
        if len(self.binding_ids) != len(set(self.binding_ids)):
            raise ValueError("identity-view bindings must be unique")
        return self


class IdentityView(Contract):
    format_version: Literal["1.0.0"] = IDENTITY_VIEW_FORMAT_VERSION
    view_id: str = Field(pattern=r"^identityview_[a-f0-9]{32}$")
    kind: IdentityViewKind
    entries: tuple[IdentityViewEntry, ...]
    findings: tuple[str, ...] = ()
    blocking_findings: tuple[str, ...] = ()
    trusted_for_participant_rendering: bool

    @model_validator(mode="after")
    def blocking_findings_prevent_trust(self) -> "IdentityView":
        if self.blocking_findings and self.trusted_for_participant_rendering:
            raise ValueError(
                "blocked identity view cannot be trusted for rendering"
            )
        identifiers = [item.entry_id for item in self.entries]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("identity-view entry identifiers must be unique")
        return self


class IdentityViewAssembly(Contract):
    format_version: Literal["1.0.0"] = IDENTITY_VIEW_FORMAT_VERSION
    assembly_id: str = Field(pattern=r"^identityviewassembly_[a-f0-9]{32}$")
    corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    provider_response_id: str = Field(pattern=r"^diaresponse_[a-f0-9]{32}$")
    provider_response_sha256: Sha256
    diarization_run_id: str = Field(pattern=r"^diarun_[a-f0-9]{32}$")
    clustering_run_id: str = Field(pattern=r"^clusterrun_[a-f0-9]{32}$")
    foundation_id: str = Field(
        pattern=r"^identityfoundation_[a-f0-9]{32}$"
    )
    binding_run_id: str = Field(
        pattern=r"^identitybindingrun_[a-f0-9]{32}$"
    )
    comparison_run_id: str | None = Field(
        default=None, pattern=r"^voicecomparisonrun_[a-f0-9]{32}$"
    )
    policy: IdentityViewPolicy
    configuration_hash: Sha256
    views: tuple[IdentityView, ...] = Field(min_length=8, max_length=8)
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def every_required_view_occurs_once(self) -> "IdentityViewAssembly":
        kinds = [item.kind for item in self.views]
        if set(kinds) != set(IdentityViewKind) or len(kinds) != len(set(kinds)):
            raise ValueError("identity-view assembly requires all eight views")
        return self


class IdentityViewReport(Contract):
    format_version: Literal["1.0.0"] = IDENTITY_VIEW_FORMAT_VERSION
    report_id: str = Field(pattern=r"^identityviewreport_[a-f0-9]{32}$")
    assembly_id: str = Field(pattern=r"^identityviewassembly_[a-f0-9]{32}$")
    reviewed_view_id: str = Field(pattern=r"^identityview_[a-f0-9]{32}$")
    generated_at: datetime
    view_count: Literal[8] = 8
    entry_count: int = Field(ge=0)
    reviewed_identity_count: int = Field(ge=0)
    unknown_count: int = Field(ge=0)
    conflict_count: int = Field(ge=0)
    blocking_finding_count: int = Field(ge=0)
    findings: tuple[str, ...]
    limitations: tuple[str, ...]
    status: Literal["complete", "warning", "blocked"]
    integrity_sha256: Sha256


IDENTITY_VIEW_CONTRACT_MODELS = (
    IdentityViewPolicy,
    IdentityViewEntry,
    IdentityView,
    IdentityViewAssembly,
    IdentityViewReport,
)
