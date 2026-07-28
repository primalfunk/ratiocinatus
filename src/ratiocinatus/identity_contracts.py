"""Minimal scoped participant-identity and hypothesis contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract, Sha256
from .phase3_contracts import IdentityHypothesis, ParticipantIdentity

IDENTITY_FOUNDATION_FORMAT_VERSION = "1.0.0"
IDENTITY_FOUNDATION_POLICY_VERSION = "1.0.0"


class IdentityConflictKind(str, Enum):
    COMPETING_HYPOTHESES = "competing_hypotheses"
    AMBIGUOUS_DISPLAY_LABEL = "ambiguous_display_label"


class IdentityFoundationPolicy(Contract):
    policy_version: Literal["1.0.0"] = IDENTITY_FOUNDATION_POLICY_VERSION
    cluster_identity_separation: Literal["required"] = "required"
    explicit_scope_required: Literal[True] = True
    evidence_dimensions: tuple[
        Literal["acoustic", "contextual", "documentary", "manual"], ...
    ] = ("acoustic", "contextual", "documentary", "manual")
    automatic_binding: Literal["disabled"] = "disabled"
    automatic_conflict_resolution: Literal["disabled"] = "disabled"
    biographical_profile_fields: Literal["prohibited"] = "prohibited"


class IdentityConflict(Contract):
    conflict_id: str = Field(pattern=r"^identityconflict_[a-f0-9]{32}$")
    kind: IdentityConflictKind
    target_artifact_id: str
    identity_ids: tuple[str, ...] = Field(min_length=2)
    hypothesis_ids: tuple[str, ...] = ()
    finding: str = Field(min_length=1)
    resolved: Literal[False] = False
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def conflict_references_are_unique(self) -> "IdentityConflict":
        if len(self.identity_ids) != len(set(self.identity_ids)):
            raise ValueError("identity conflict identities must be unique")
        if len(self.hypothesis_ids) != len(set(self.hypothesis_ids)):
            raise ValueError("identity conflict hypotheses must be unique")
        if (
            self.kind == IdentityConflictKind.COMPETING_HYPOTHESES
            and len(self.hypothesis_ids) < 2
        ):
            raise ValueError(
                "competing-hypothesis conflict requires two hypotheses"
            )
        return self


class IdentityFoundationRun(Contract):
    format_version: Literal["1.0.0"] = IDENTITY_FOUNDATION_FORMAT_VERSION
    foundation_id: str = Field(
        pattern=r"^identityfoundation_[a-f0-9]{32}$"
    )
    predecessor_foundation_id: str | None = Field(
        default=None, pattern=r"^identityfoundation_[a-f0-9]{32}$"
    )
    clustering_run_id: str = Field(pattern=r"^clusterrun_[a-f0-9]{32}$")
    diarization_run_id: str = Field(pattern=r"^diarun_[a-f0-9]{32}$")
    corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    policy: IdentityFoundationPolicy
    configuration_hash: Sha256
    identities: tuple[ParticipantIdentity, ...]
    hypotheses: tuple[IdentityHypothesis, ...]
    conflicts: tuple[IdentityConflict, ...]
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def foundation_references_are_unique(self) -> "IdentityFoundationRun":
        collections = (
            ("participant identity", [item.identity_id for item in self.identities]),
            (
                "identity hypothesis",
                [item.hypothesis_id for item in self.hypotheses],
            ),
            ("identity conflict", [item.conflict_id for item in self.conflicts]),
        )
        for label, identifiers in collections:
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"{label} identifiers must be unique")
        if self.foundation_id == self.predecessor_foundation_id:
            raise ValueError("identity foundation cannot be its own predecessor")
        return self


class ParticipantIdentityReport(Contract):
    format_version: Literal["1.0.0"] = IDENTITY_FOUNDATION_FORMAT_VERSION
    report_id: str = Field(pattern=r"^identityreport_[a-f0-9]{32}$")
    foundation_id: str = Field(
        pattern=r"^identityfoundation_[a-f0-9]{32}$"
    )
    clustering_run_id: str = Field(pattern=r"^clusterrun_[a-f0-9]{32}$")
    corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    generated_at: datetime
    identity_count: int = Field(ge=0)
    hypothesis_count: int = Field(ge=0)
    unresolved_identity_count: int = Field(ge=0)
    unresolved_hypothesis_count: int = Field(ge=0)
    unresolved_conflict_count: int = Field(ge=0)
    findings: tuple[str, ...]
    limitations: tuple[str, ...]
    status: Literal["complete", "warning", "blocked"]
    integrity_sha256: Sha256


IDENTITY_CONTRACT_MODELS = (
    IdentityFoundationPolicy,
    IdentityConflict,
    IdentityFoundationRun,
    ParticipantIdentityReport,
)
