"""Stable operational chunk-plan contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .addressing_contracts import MediaInterval, TimeDomain
from .contracts import Contract

CHUNK_POLICY_VERSION = "1.0.0"
CHUNK_PLAN_FORMAT_VERSION = "1.0.0"


class ChunkPolicy(Contract):
    policy_version: Literal["1.0.0"] = CHUNK_POLICY_VERSION
    target_duration_microseconds: int = Field(
        default=600_000_000, gt=0
    )
    overlap_microseconds: int = Field(default=5_000_000, ge=0)
    minimum_duration_microseconds: int = Field(default=30_000_000, gt=0)
    maximum_duration_microseconds: int = Field(
        default=900_000_000, gt=0
    )
    ownership_policy: Literal["earliest_chunk_owns_overlap"] = (
        "earliest_chunk_owns_overlap"
    )

    @model_validator(mode="after")
    def durations_are_consistent(self) -> "ChunkPolicy":
        if self.overlap_microseconds >= self.target_duration_microseconds:
            raise ValueError("chunk overlap must be shorter than target duration")
        if not (
            self.minimum_duration_microseconds
            <= self.target_duration_microseconds
            <= self.maximum_duration_microseconds
        ):
            raise ValueError("chunk target must be within minimum and maximum")
        return self


class ProcessingChunk(Contract):
    chunk_id: str = Field(pattern=r"^chunk_[a-f0-9]{32}$")
    ordinal: int = Field(ge=0)
    corpus_interval: MediaInterval
    source_interval: MediaInterval
    ownership_interval: MediaInterval
    overlap_before_microseconds: int = Field(ge=0)
    overlap_after_microseconds: int = Field(ge=0)
    terminal_short_chunk: bool = False
    virtual: bool = True

    @model_validator(mode="after")
    def domains_are_correct(self) -> "ProcessingChunk":
        if self.corpus_interval.domain != TimeDomain.NORMALIZED_CORPUS:
            raise ValueError("chunk corpus interval has the wrong domain")
        if self.source_interval.domain != TimeDomain.SOURCE_MEDIA:
            raise ValueError("chunk source interval has the wrong domain")
        if self.ownership_interval.domain != TimeDomain.NORMALIZED_CORPUS:
            raise ValueError("chunk ownership interval has the wrong domain")
        return self


class ProcessingChunkPlan(Contract):
    format_version: Literal["1.0.0"] = CHUNK_PLAN_FORMAT_VERSION
    plan_id: str = Field(pattern=r"^chunkplan_[a-f0-9]{32}$")
    source_id: str = Field(pattern=r"^src_[a-f0-9]{32}$")
    policy: ChunkPolicy
    corpus_duration_microseconds: int = Field(gt=0)
    chunks: tuple[ProcessingChunk, ...]
    coverage_complete: bool
    maximum_coverage_multiplicity: int = Field(ge=1)

    @model_validator(mode="after")
    def plan_shape_is_valid(self) -> "ProcessingChunkPlan":
        if not self.chunks:
            raise ValueError("chunk plan must contain at least one chunk")
        if [item.ordinal for item in self.chunks] != list(range(len(self.chunks))):
            raise ValueError("chunk ordinals must be contiguous")
        if self.chunks[0].corpus_interval.start_microseconds != 0:
            raise ValueError("first chunk must begin at zero")
        final = self.chunks[-1].corpus_interval
        if final.start_microseconds + final.duration_microseconds != (
            self.corpus_duration_microseconds
        ):
            raise ValueError("final chunk must reach corpus end")
        if not self.coverage_complete:
            raise ValueError("canonical chunk plan must declare complete coverage")
        for index, chunk in enumerate(self.chunks):
            interval = chunk.corpus_interval
            end = interval.start_microseconds + interval.duration_microseconds
            if end > self.corpus_duration_microseconds:
                raise ValueError("chunk exceeds corpus bounds")
            if chunk.source_interval.duration_microseconds != interval.duration_microseconds:
                raise ValueError("source and corpus chunk durations must agree")
            if index:
                previous = self.chunks[index - 1].corpus_interval
                previous_end = (
                    previous.start_microseconds + previous.duration_microseconds
                )
                actual_overlap = previous_end - interval.start_microseconds
                if actual_overlap != self.policy.overlap_microseconds:
                    raise ValueError("adjacent chunk overlap does not match policy")
                previous_ownership = self.chunks[index - 1].ownership_interval
                previous_ownership_end = (
                    previous_ownership.start_microseconds
                    + previous_ownership.duration_microseconds
                )
                if chunk.ownership_interval.start_microseconds != previous_ownership_end:
                    raise ValueError("chunk ownership intervals must be contiguous")
            expected_short = (
                index == len(self.chunks) - 1
                and interval.duration_microseconds
                < self.policy.minimum_duration_microseconds
            )
            if chunk.terminal_short_chunk != expected_short:
                raise ValueError("terminal-short-chunk flag is inconsistent")
        owned_final = self.chunks[-1].ownership_interval
        if owned_final.start_microseconds + owned_final.duration_microseconds != (
            self.corpus_duration_microseconds
        ):
            raise ValueError("ownership intervals must cover the corpus")
        return self


CHUNK_CONTRACT_MODELS = (
    ChunkPolicy,
    ProcessingChunk,
    ProcessingChunkPlan,
)
