"""Append-only, attributable manual participant-identity binding contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract, Sha256
from .phase3_contracts import ManualIdentityBinding

IDENTITY_BINDING_FORMAT_VERSION = "1.0.0"
IDENTITY_BINDING_POLICY_VERSION = "1.0.0"


class IdentityBindingPolicy(Contract):
    policy_version: Literal["1.0.0"] = IDENTITY_BINDING_POLICY_VERSION
    automatic_binding: Literal["disabled"] = "disabled"
    append_only_history: Literal["required"] = "required"
    attributable_author: Literal["required"] = "required"
    explicit_scope: Literal["required"] = "required"
    silent_conflict_resolution: Literal["prohibited"] = "prohibited"
    source_diarization_mutation: Literal["prohibited"] = "prohibited"
    manual_labels_visibly_distinct: Literal["required"] = "required"


class IdentityBindingRun(Contract):
    format_version: Literal["1.0.0"] = IDENTITY_BINDING_FORMAT_VERSION
    run_id: str = Field(pattern=r"^identitybindingrun_[a-f0-9]{32}$")
    predecessor_run_id: str | None = Field(
        default=None, pattern=r"^identitybindingrun_[a-f0-9]{32}$"
    )
    foundation_id: str = Field(
        pattern=r"^identityfoundation_[a-f0-9]{32}$"
    )
    foundation_integrity_sha256: Sha256
    clustering_run_id: str = Field(pattern=r"^clusterrun_[a-f0-9]{32}$")
    diarization_run_id: str = Field(pattern=r"^diarun_[a-f0-9]{32}$")
    corpus_id: str = Field(pattern=r"^corpus_[a-f0-9]{32}$")
    policy: IdentityBindingPolicy
    configuration_hash: Sha256
    bindings: tuple[ManualIdentityBinding, ...]
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def binding_identifiers_are_unique(self) -> "IdentityBindingRun":
        identifiers = [item.binding_id for item in self.bindings]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("manual identity binding identifiers must be unique")
        if self.run_id == self.predecessor_run_id:
            raise ValueError("identity binding run cannot be its own predecessor")
        return self


class IdentityBindingReport(Contract):
    format_version: Literal["1.0.0"] = IDENTITY_BINDING_FORMAT_VERSION
    report_id: str = Field(pattern=r"^identitybindingreport_[a-f0-9]{32}$")
    run_id: str = Field(pattern=r"^identitybindingrun_[a-f0-9]{32}$")
    foundation_id: str = Field(
        pattern=r"^identityfoundation_[a-f0-9]{32}$"
    )
    generated_at: datetime
    binding_count: int = Field(ge=0)
    active_binding_count: int = Field(ge=0)
    unresolved_conflict_count: int = Field(ge=0)
    action_counts: dict[str, int]
    active_binding_ids: tuple[str, ...]
    conflicting_binding_groups: tuple[tuple[str, ...], ...]
    findings: tuple[str, ...]
    limitations: tuple[str, ...]
    status: Literal["complete", "warning", "blocked"]
    integrity_sha256: Sha256


IDENTITY_BINDING_CONTRACT_MODELS = (
    IdentityBindingPolicy,
    IdentityBindingRun,
    IdentityBindingReport,
)
