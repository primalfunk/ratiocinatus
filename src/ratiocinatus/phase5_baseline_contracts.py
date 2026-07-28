"""Contracts for the conservative deterministic Phase 5 baseline."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract, Sha256
from .phase5_contracts import (
    PHASE5_FORMAT_VERSION,
    DiscourseActObservation,
)

DETERMINISTIC_DISCOURSE_POLICY_VERSION = "1.0.0"


class DeterministicDiscoursePolicy(Contract):
    policy_version: Literal["1.0.0"] = (
        DETERMINISTIC_DISCOURSE_POLICY_VERSION
    )
    rule_version: Literal["1.0.0"] = "1.0.0"
    require_explicit_lexical_or_structural_cue: Literal[True] = True
    punctuation_alone_sufficient: Literal[False] = False
    generic_declarative_fallback: Literal[False] = False
    maximum_observations_per_utterance: int = Field(
        default=12, ge=1, le=100
    )
    preserve_unknown: Literal[True] = True
    provider_invocation: Literal["prohibited"] = "prohibited"
    semantic_claim_extraction: Literal["prohibited"] = "prohibited"
    truth_assignment: Literal["prohibited"] = "prohibited"
    adequacy_scoring: Literal["prohibited"] = "prohibited"
    intent_inference: Literal["prohibited"] = "prohibited"
    confidence_basis: Literal["uncalibrated_rule_strength"] = (
        "uncalibrated_rule_strength"
    )


class DeterministicDiscourseRun(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    baseline_run_id: str = Field(
        pattern=r"^discoursebaseline_[a-f0-9]{32}$"
    )
    discourse_run_id: str = Field(pattern=r"^discourserun_[a-f0-9]{32}$")
    phase4_utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    phase4_utterance_corpus_sha256: Sha256
    phase4_quotation_run_id: str | None = Field(
        default=None, pattern=r"^quotationrun_[a-f0-9]{32}$"
    )
    policy: DeterministicDiscoursePolicy
    configuration_hash: Sha256
    observations: tuple[DiscourseActObservation, ...]
    unclassified_utterance_ids: tuple[str, ...]
    matched_rule_ids: tuple[str, ...]
    created_at: datetime
    complete: bool
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def baseline_children_are_coherent(self) -> "DeterministicDiscourseRun":
        ids = [item.observation_id for item in self.observations]
        if len(ids) != len(set(ids)):
            raise ValueError("baseline observation ids must be unique")
        if any(
            item.discourse_run_id != self.discourse_run_id
            or item.phase4_utterance_corpus_id
            != self.phase4_utterance_corpus_id
            for item in self.observations
        ):
            raise ValueError("baseline observation lineage is incompatible")
        classified = {item.utterance_id for item in self.observations}
        if classified.intersection(self.unclassified_utterance_ids):
            raise ValueError(
                "utterance cannot be classified and unclassified"
            )
        if len(self.unclassified_utterance_ids) != len(
            set(self.unclassified_utterance_ids)
        ):
            raise ValueError("unclassified utterance ids must be unique")
        return self


class DeterministicDiscourseReport(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    report_id: str = Field(
        pattern=r"^discoursebaselinereport_[a-f0-9]{32}$"
    )
    baseline_run_id: str = Field(
        pattern=r"^discoursebaseline_[a-f0-9]{32}$"
    )
    phase4_utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    generated_at: datetime
    utterance_count: int = Field(ge=0)
    observation_count: int = Field(ge=0)
    multi_label_utterance_count: int = Field(ge=0)
    unclassified_utterance_count: int = Field(ge=0)
    assertive_count: int = Field(ge=0)
    question_count: int = Field(ge=0)
    concession_count: int = Field(ge=0)
    qualification_count: int = Field(ge=0)
    definition_count: int = Field(ge=0)
    example_count: int = Field(ge=0)
    quotation_count: int = Field(ge=0)
    procedural_count: int = Field(ge=0)
    limitations: tuple[str, ...] = Field(min_length=1)
    status: Literal["complete", "warning", "failed"]
    integrity_sha256: Sha256


PHASE5_BASELINE_CONTRACT_MODELS = (
    DeterministicDiscoursePolicy,
    DeterministicDiscourseRun,
    DeterministicDiscourseReport,
)
