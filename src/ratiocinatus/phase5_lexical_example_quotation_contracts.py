"""Definition, example, and quotation-use construction contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract, Sha256
from .phase2_contracts import ConfidenceMeasure
from .phase5_contracts import (
    FAMILY_TYPES,
    PHASE5_FORMAT_VERSION,
    DiscourseActFamily,
    DiscourseActType,
    DiscourseReviewStatus,
    DiscourseTargetStatus,
)
from .quotation_contracts import QuotedTextSpan, SpokenQuotationType

LEXICAL_EXAMPLE_QUOTATION_POLICY_VERSION = "1.0.0"


class DefinitionScope(str, Enum):
    SOURCE_UTTERANCE = "source_utterance"
    DECLARED_CONTEXT = "declared_context"
    BOUNDED_DISCOURSE_CONTEXT = "bounded_discourse_context"
    UNRESOLVED = "unresolved"


class ExampleRealityStatus(str, Enum):
    REAL = "real"
    HYPOTHETICAL = "hypothetical"
    QUOTED = "quoted"
    UNCERTAIN = "uncertain"


class LexicalExampleQuotationPolicy(Contract):
    policy_version: Literal["1.0.0"] = (
        LEXICAL_EXAMPLE_QUOTATION_POLICY_VERSION
    )
    definitions_local_by_default: Literal[True] = True
    nearest_prior_generalization_is_probable: Literal[True] = True
    preserve_generalization_ambiguity: Literal[True] = True
    quotation_evidence_authority: Literal["phase4"] = "phase4"
    acoustic_attribution_mutation: Literal["prohibited"] = "prohibited"
    example_proves_generalization: Literal[False] = False
    definition_global_reuse_without_evidence: Literal[False] = False
    factual_adjudication: Literal[False] = False


class DefinitionRecord(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    definition_id: str = Field(pattern=r"^definition_[a-f0-9]{32}$")
    discourse_corpus_id: str = Field(
        pattern=r"^discoursecorpus_[a-f0-9]{32}$"
    )
    source_act_id: str = Field(pattern=r"^discourseact_[a-f0-9]{32}$")
    utterance_id: str = Field(pattern=r"^utterance_[a-f0-9]{32}$")
    definition_type: DiscourseActType
    defined_expression: str | None = None
    defining_text: tuple[str, ...] = Field(min_length=1)
    scope: DefinitionScope
    applicable_context_text: tuple[str, ...] = ()
    context_window_id: str | None = Field(
        default=None, pattern=r"^contextwindow_[a-f0-9]{32}$"
    )
    explicit_exclusions: tuple[str, ...] = ()
    competing_definition_ids: tuple[str, ...] = ()
    definition_challenge_act_ids: tuple[str, ...] = ()
    evidence_span_ids: tuple[str, ...] = Field(min_length=1)
    confidence: ConfidenceMeasure
    review_status: DiscourseReviewStatus
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def definition_is_coherent(self) -> "DefinitionRecord":
        if self.definition_type not in FAMILY_TYPES[
            DiscourseActFamily.DEFINITION
        ]:
            raise ValueError("definition record requires definition act")
        for values in (
            self.defining_text,
            self.applicable_context_text,
            self.explicit_exclusions,
            self.competing_definition_ids,
            self.definition_challenge_act_ids,
            self.evidence_span_ids,
        ):
            if len(values) != len(set(values)):
                raise ValueError("definition references must be unique")
        return self


class ExampleRecord(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    example_id: str = Field(pattern=r"^example_[a-f0-9]{32}$")
    discourse_corpus_id: str = Field(
        pattern=r"^discoursecorpus_[a-f0-9]{32}$"
    )
    source_act_id: str = Field(pattern=r"^discourseact_[a-f0-9]{32}$")
    utterance_id: str = Field(pattern=r"^utterance_[a-f0-9]{32}$")
    example_type: DiscourseActType
    example_span_ids: tuple[str, ...] = Field(min_length=1)
    example_text: tuple[str, ...] = Field(min_length=1)
    reality_status: ExampleRealityStatus
    target_status: DiscourseTargetStatus
    generalization_act_ids: tuple[str, ...]
    alternative_generalization_act_ids: tuple[str, ...] = ()
    temporal_references: tuple[str, ...] = ()
    participant_references: tuple[str, ...] = ()
    context_window_id: str | None = Field(
        default=None, pattern=r"^contextwindow_[a-f0-9]{32}$"
    )
    confidence: ConfidenceMeasure
    review_status: DiscourseReviewStatus
    representativeness_assessed: Literal[False] = False
    proves_generalization: Literal[False] = False
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def example_is_coherent(self) -> "ExampleRecord":
        if self.example_type not in FAMILY_TYPES[DiscourseActFamily.EXAMPLE]:
            raise ValueError("example record requires example act")
        if (
            self.target_status
            == DiscourseTargetStatus.MULTIPLE_CANDIDATES
            and len(self.alternative_generalization_act_ids) < 2
        ):
            raise ValueError("ambiguous example requires alternatives")
        return self


class QuotationUseRecord(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    quotation_use_id: str = Field(
        pattern=r"^quotationuse_[a-f0-9]{32}$"
    )
    discourse_corpus_id: str = Field(
        pattern=r"^discoursecorpus_[a-f0-9]{32}$"
    )
    source_act_id: str = Field(pattern=r"^discourseact_[a-f0-9]{32}$")
    utterance_id: str = Field(pattern=r"^utterance_[a-f0-9]{32}$")
    quotation_use_type: DiscourseActType
    phase4_quotation_id: str | None = Field(
        default=None, pattern=r"^quotation_[a-f0-9]{32}$"
    )
    phase4_quotation_type: SpokenQuotationType | None = None
    quoted_span: QuotedTextSpan | None = None
    acoustic_attribution_id: str | None = Field(
        default=None, pattern=r"^utteranceattr_[a-f0-9]{32}$"
    )
    acoustic_speaker_target_id: str | None = None
    quoting_speaker_target_id: str | None = None
    attributed_speaker_target_id: str | None = None
    original_source_reference: str | None = None
    attribution_text: str | None = None
    embedded_source_ids: tuple[str, ...] = ()
    evidence_span_ids: tuple[str, ...] = Field(min_length=1)
    confidence: ConfidenceMeasure
    review_status: DiscourseReviewStatus
    acoustic_attribution_preserved: Literal[True] = True
    acoustic_attribution_mutated: Literal[False] = False
    created_at: datetime
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def quotation_use_is_coherent(self) -> "QuotationUseRecord":
        if self.quotation_use_type not in FAMILY_TYPES[
            DiscourseActFamily.QUOTATION
        ]:
            raise ValueError("quotation use requires quotation act")
        phase4_fields = (
            self.phase4_quotation_type,
            self.quoted_span,
            self.acoustic_attribution_id,
        )
        if self.phase4_quotation_id is None and any(
            item is not None for item in phase4_fields
        ):
            raise ValueError("unmatched quotation cannot claim Phase 4 fields")
        if self.phase4_quotation_id is not None and any(
            item is None for item in phase4_fields
        ):
            raise ValueError("matched quotation requires Phase 4 provenance")
        return self


class LexicalExampleQuotationRun(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    construction_run_id: str = Field(
        pattern=r"^lexicalconstruction_[a-f0-9]{32}$"
    )
    discourse_corpus_id: str = Field(
        pattern=r"^discoursecorpus_[a-f0-9]{32}$"
    )
    discourse_corpus_sha256: Sha256
    context_bundle_id: str = Field(pattern=r"^contextbundle_[a-f0-9]{32}$")
    context_bundle_sha256: Sha256
    phase4_quotation_run_id: str | None = Field(
        default=None, pattern=r"^quotationrun_[a-f0-9]{32}$"
    )
    phase4_quotation_run_sha256: Sha256 | None = None
    policy: LexicalExampleQuotationPolicy
    configuration_hash: Sha256
    definitions: tuple[DefinitionRecord, ...]
    examples: tuple[ExampleRecord, ...]
    quotation_uses: tuple[QuotationUseRecord, ...]
    unresolved_source_act_ids: tuple[str, ...]
    created_at: datetime
    complete: bool
    integrity_sha256: Sha256


class LexicalExampleQuotationReport(Contract):
    format_version: Literal["1.0.0"] = PHASE5_FORMAT_VERSION
    report_id: str = Field(
        pattern=r"^lexicalconstructionreport_[a-f0-9]{32}$"
    )
    construction_run_id: str = Field(
        pattern=r"^lexicalconstruction_[a-f0-9]{32}$"
    )
    generated_at: datetime
    definition_count: int = Field(ge=0)
    unresolved_definition_expression_count: int = Field(ge=0)
    competing_definition_count: int = Field(ge=0)
    definition_challenge_link_count: int = Field(ge=0)
    example_count: int = Field(ge=0)
    probable_example_target_count: int = Field(ge=0)
    ambiguous_example_target_count: int = Field(ge=0)
    unresolved_example_target_count: int = Field(ge=0)
    quotation_use_count: int = Field(ge=0)
    phase4_matched_quotation_use_count: int = Field(ge=0)
    unresolved_quotation_use_count: int = Field(ge=0)
    limitations: tuple[str, ...] = Field(min_length=1)
    status: Literal["complete", "warning", "failed"]
    integrity_sha256: Sha256


PHASE5_LEXICAL_EXAMPLE_QUOTATION_CONTRACT_MODELS = (
    LexicalExampleQuotationPolicy,
    DefinitionRecord,
    ExampleRecord,
    QuotationUseRecord,
    LexicalExampleQuotationRun,
    LexicalExampleQuotationReport,
)
