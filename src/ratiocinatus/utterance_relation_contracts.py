"""Phase 4 interruption, overlap, continuation, and adjacency contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .addressing_contracts import MediaInterval, TimeDomain
from .contracts import Contract, Sha256
from .phase2_contracts import ConfidenceMeasure
from .phase3_contracts import OverlapClassification
from .phase4_contracts import (
    PHASE4_FORMAT_VERSION,
    UtteranceReviewStatus,
)

UTTERANCE_RELATION_POLICY_VERSION = "1.0.0"


class UtteranceTemporalRelation(str, Enum):
    BEFORE = "before"
    TOUCHING = "touching"
    OVERLAPPING = "overlapping"
    SIMULTANEOUS_START = "simultaneous_start"


class OverlapAttributionDisposition(str, Enum):
    SEPARATED_UTTERANCES = "separated_utterances"
    MIXED_TRANSCRIPT = "mixed_transcript"
    UNCERTAIN_WORD_ATTRIBUTION = "uncertain_word_attribution"
    UNTRANSCRIBED_OVERLAP = "untranscribed_overlap"


class InterruptionKind(str, Enum):
    ACTUAL_SIMULTANEOUS = "actual_simultaneous_interruption"
    IMMEDIATE_TURN_TAKEOVER = "immediate_turn_takeover"
    SUPPORTIVE_INTERJECTION = "supportive_interjection"
    BACKCHANNEL = "backchannel"
    MODERATOR_CUTOFF = "moderator_cutoff"
    TECHNICAL_CUTOFF = "technical_cutoff"
    AUDIENCE_INTERRUPTION = "audience_interruption"
    UNCERTAIN = "uncertain_interruption"


class ContinuationKind(str, Enum):
    SAME_UTTERANCE_RESUMED = "same_utterance_resumed"
    NEW_UTTERANCE_SAME_TOPIC = "new_utterance_on_same_topic"
    REPEATED_RESTART = "repeated_restart"
    RECAP_AFTER_INTERRUPTION = "recap_after_interruption"
    UNRESOLVED = "unresolved_continuation"


class SpeakerConsistency(str, Enum):
    SAME_ATTRIBUTION = "same_attribution"
    COMPATIBLE_CANDIDATE = "compatible_candidate"
    DIFFERENT_ATTRIBUTION = "different_attribution"
    UNRESOLVED = "unresolved"


class ContinuationDisposition(str, Enum):
    CANDIDATE = "candidate"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    UNRESOLVED = "unresolved"


class UtteranceRelationPolicy(Contract):
    policy_version: Literal["1.0.0"] = UTTERANCE_RELATION_POLICY_VERSION
    immediate_takeover_max_gap_microseconds: int = Field(
        default=250_000, ge=0
    )
    continuation_max_gap_microseconds: int = Field(
        default=8_000_000, ge=1
    )
    continuation_requires_intervening_activity: bool = True
    continuation_requires_same_attribution: bool = True
    simultaneous_interruption_requires_phase3_overlap: bool = True
    supportive_interjection_inference: Literal["prohibited"] = "prohibited"
    backchannel_inference: Literal["prohibited"] = "prohibited"
    semantic_continuation_inference: Literal["prohibited"] = "prohibited"
    intent_or_blame_inference: Literal["prohibited"] = "prohibited"


class UtteranceAdjacencyRelation(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    adjacency_id: str = Field(pattern=r"^utteranceadjacency_[a-f0-9]{32}$")
    utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    preceding_utterance_id: str = Field(pattern=r"^utterance_[a-f0-9]{32}$")
    following_utterance_id: str = Field(pattern=r"^utterance_[a-f0-9]{32}$")
    temporal_relation: UtteranceTemporalRelation
    signed_gap_microseconds: int
    overlap_normalized_audio_interval: MediaInterval | None = None
    evidence_references: tuple[str, ...] = Field(min_length=1)
    policy_version: Literal["1.0.0"] = UTTERANCE_RELATION_POLICY_VERSION
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def temporal_shape_is_coherent(self) -> "UtteranceAdjacencyRelation":
        if self.preceding_utterance_id == self.following_utterance_id:
            raise ValueError("adjacency requires distinct utterances")
        overlapping = self.temporal_relation in {
            UtteranceTemporalRelation.OVERLAPPING,
            UtteranceTemporalRelation.SIMULTANEOUS_START,
        }
        if overlapping != (self.overlap_normalized_audio_interval is not None):
            raise ValueError("overlap adjacency requires one overlap interval")
        if overlapping and self.signed_gap_microseconds >= 0:
            raise ValueError("overlap adjacency requires a negative signed gap")
        if (
            self.overlap_normalized_audio_interval is not None
            and self.overlap_normalized_audio_interval.domain
            != TimeDomain.NORMALIZED_CORPUS
        ):
            raise ValueError("adjacency overlap uses normalized-corpus time")
        return self


class UtteranceOverlapRelation(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    overlap_relation_id: str = Field(
        pattern=r"^utteranceoverlap_[a-f0-9]{32}$"
    )
    utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    phase3_overlap_id: str = Field(pattern=r"^spkoverlap_[a-f0-9]{32}$")
    classification: OverlapClassification
    source_interval: MediaInterval
    normalized_audio_interval: MediaInterval
    affected_utterance_ids: tuple[str, ...]
    candidate_cluster_ids: tuple[str, ...] = ()
    disposition: OverlapAttributionDisposition
    partially_attributed: bool
    evidence_references: tuple[str, ...] = Field(min_length=1)
    confidence: ConfidenceMeasure
    review_status: UtteranceReviewStatus
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def overlap_projection_is_coherent(self) -> "UtteranceOverlapRelation":
        if (
            self.source_interval.domain != TimeDomain.SOURCE_MEDIA
            or self.normalized_audio_interval.domain
            != TimeDomain.NORMALIZED_CORPUS
        ):
            raise ValueError("overlap projection has invalid time domain")
        if len(self.affected_utterance_ids) != len(
            set(self.affected_utterance_ids)
        ):
            raise ValueError("overlap utterance references must be unique")
        if (
            self.disposition
            == OverlapAttributionDisposition.UNTRANSCRIBED_OVERLAP
        ) != (not self.affected_utterance_ids):
            raise ValueError(
                "untranscribed overlap must have no affected utterance"
            )
        return self


class InterruptionRelation(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    interruption_id: str = Field(pattern=r"^interruption_[a-f0-9]{32}$")
    utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    interrupted_utterance_id: str = Field(
        pattern=r"^utterance_[a-f0-9]{32}$"
    )
    interrupting_utterance_id: str | None = Field(
        default=None, pattern=r"^utterance_[a-f0-9]{32}$"
    )
    interruption_onset_normalized_microseconds: int = Field(ge=0)
    interrupting_speaker_target_id: str | None = None
    kind: InterruptionKind
    overlap_relation_id: str | None = Field(
        default=None, pattern=r"^utteranceoverlap_[a-f0-9]{32}$"
    )
    original_speaker_continues_underneath: bool
    original_utterance_resumes: bool
    continuation_relation_id: str | None = Field(
        default=None, pattern=r"^continuation_[a-f0-9]{32}$"
    )
    temporal_evidence_references: tuple[str, ...] = Field(min_length=1)
    confidence: ConfidenceMeasure
    review_status: UtteranceReviewStatus
    policy_version: Literal["1.0.0"] = UTTERANCE_RELATION_POLICY_VERSION
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def interruption_has_temporal_support(self) -> "InterruptionRelation":
        if (
            self.interrupting_utterance_id
            == self.interrupted_utterance_id
        ):
            raise ValueError("utterance cannot interrupt itself")
        if (
            self.kind == InterruptionKind.ACTUAL_SIMULTANEOUS
            and self.overlap_relation_id is None
        ):
            raise ValueError("simultaneous interruption requires overlap")
        if self.original_utterance_resumes != (
            self.continuation_relation_id is not None
        ):
            raise ValueError("resumption requires a continuation relation")
        return self


class ContinuationRelation(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    continuation_id: str = Field(pattern=r"^continuation_[a-f0-9]{32}$")
    utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    predecessor_utterance_id: str = Field(
        pattern=r"^utterance_[a-f0-9]{32}$"
    )
    successor_utterance_id: str = Field(
        pattern=r"^utterance_[a-f0-9]{32}$"
    )
    intervening_utterance_ids: tuple[str, ...] = Field(min_length=1)
    elapsed_gap_microseconds: int = Field(ge=0)
    speaker_consistency: SpeakerConsistency
    kind: ContinuationKind
    lexical_or_syntactic_evidence: tuple[str, ...] = ()
    semantic_continuation_evidence: tuple[str, ...] = ()
    semantic_inference_used: bool = False
    confidence: ConfidenceMeasure
    disposition: ContinuationDisposition
    review_status: UtteranceReviewStatus
    policy_version: Literal["1.0.0"] = UTTERANCE_RELATION_POLICY_VERSION
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def continuation_shape_is_valid(self) -> "ContinuationRelation":
        if self.predecessor_utterance_id == self.successor_utterance_id:
            raise ValueError("continuation requires distinct utterances")
        if len(self.intervening_utterance_ids) != len(
            set(self.intervening_utterance_ids)
        ):
            raise ValueError("intervening utterances must be unique")
        endpoints = {
            self.predecessor_utterance_id,
            self.successor_utterance_id,
        }
        if endpoints.intersection(self.intervening_utterance_ids):
            raise ValueError("continuation endpoints cannot be intervening")
        if self.semantic_inference_used != bool(
            self.semantic_continuation_evidence
        ):
            raise ValueError("semantic evidence use must be explicit")
        return self


class UtteranceRelationRun(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    relation_run_id: str = Field(pattern=r"^utterancerelations_[a-f0-9]{32}$")
    utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    utterance_run_id: str = Field(pattern=r"^utterancerun_[a-f0-9]{32}$")
    utterance_analysis_id: str = Field(
        pattern=r"^utteranceanalysis_[a-f0-9]{32}$"
    )
    phase3_diarization_run_id: str = Field(
        pattern=r"^diarun_[a-f0-9]{32}$"
    )
    policy: UtteranceRelationPolicy
    configuration_hash: Sha256
    adjacencies: tuple[UtteranceAdjacencyRelation, ...]
    overlaps: tuple[UtteranceOverlapRelation, ...]
    interruptions: tuple[InterruptionRelation, ...]
    continuations: tuple[ContinuationRelation, ...]
    created_at: datetime
    complete: bool
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def relation_identifiers_and_graph_are_valid(
        self,
    ) -> "UtteranceRelationRun":
        for values in (
            tuple(item.adjacency_id for item in self.adjacencies),
            tuple(item.overlap_relation_id for item in self.overlaps),
            tuple(item.interruption_id for item in self.interruptions),
            tuple(item.continuation_id for item in self.continuations),
        ):
            if len(values) != len(set(values)):
                raise ValueError("relation identifiers must be unique")
        graph: dict[str, set[str]] = {}
        for item in self.continuations:
            graph.setdefault(item.predecessor_utterance_id, set()).add(
                item.successor_utterance_id
            )

        finished: set[str] = set()

        def visit(node: str, active: set[str]) -> None:
            if node in active:
                raise ValueError("continuation graph contains a cycle")
            if node in finished:
                return
            active.add(node)
            for successor in graph.get(node, set()):
                visit(successor, active)
            active.remove(node)
            finished.add(node)

        for origin in graph:
            visit(origin, set())
        return self


class UtteranceRelationReport(Contract):
    format_version: Literal["1.0.0"] = PHASE4_FORMAT_VERSION
    report_id: str = Field(pattern=r"^utterancerelationreport_[a-f0-9]{32}$")
    relation_run_id: str = Field(pattern=r"^utterancerelations_[a-f0-9]{32}$")
    utterance_corpus_id: str = Field(
        pattern=r"^utterancecorpus_[a-f0-9]{32}$"
    )
    generated_at: datetime
    adjacency_count: int = Field(ge=0)
    overlap_count: int = Field(ge=0)
    overlap_duration_microseconds: int = Field(ge=0)
    interruption_count: int = Field(ge=0)
    continuation_count: int = Field(ge=0)
    unresolved_count: int = Field(ge=0)
    review_required_count: int = Field(ge=0)
    limitations: tuple[str, ...] = ()
    status: Literal["complete", "warning", "failed"]
    integrity_sha256: Sha256


PHASE4_RELATION_CONTRACT_MODELS = (
    UtteranceRelationPolicy,
    UtteranceAdjacencyRelation,
    UtteranceOverlapRelation,
    InterruptionRelation,
    ContinuationRelation,
    UtteranceRelationRun,
    UtteranceRelationReport,
)
