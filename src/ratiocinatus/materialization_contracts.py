"""Contracts for explicit materialization of otherwise virtual chunks."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from .addressing_contracts import MediaInterval
from .contracts import Contract, Sha256
from .normalization_contracts import CacheDisposition
from .phase1_contracts import ExternalToolIdentity, ToolInvocationRecord

CHUNK_MATERIALIZATION_POLICY_VERSION = "1.0.0"
MATERIALIZED_CHUNK_FORMAT_VERSION = "1.0.0"


class ChunkMaterializationPolicy(Contract):
    policy_version: Literal["1.0.0"] = CHUNK_MATERIALIZATION_POLICY_VERSION
    output_format: Literal["flac"] = "flac"
    codec: Literal["flac"] = "flac"
    preserve_normalized_audio_format: Literal[True] = True
    compression_level: int = Field(default=5, ge=0, le=12)
    duration_tolerance_microseconds: int = Field(
        default=100_000, ge=0, le=2_000_000
    )
    timeout_seconds: int = Field(default=3600, ge=1, le=86_400)
    invalid_cache_action: Literal["rebuild", "refuse"] = "rebuild"


class ChunkMaterializationKey(Contract):
    format_version: Literal["1.0.0"] = MATERIALIZED_CHUNK_FORMAT_VERSION
    cache_id: str = Field(pattern=r"^chunkcache_[a-f0-9]{32}$")
    digest: Sha256
    operation: Literal["chunk.materialize.audio"] = "chunk.materialize.audio"
    operation_version: Literal["1.0.0"] = CHUNK_MATERIALIZATION_POLICY_VERSION
    chunk_id: str = Field(pattern=r"^chunk_[a-f0-9]{32}$")
    source_derivative_id: str = Field(pattern=r"^derivative_[a-f0-9]{32}$")
    source_derivative_sha256: Sha256
    configuration_hash: Sha256
    provider_identity: str
    external_tool_identity_hash: Sha256
    artifact_format_version: Literal["1.0.0"] = MATERIALIZED_CHUNK_FORMAT_VERSION


class MaterializedChunkIntegrity(Contract):
    content_sha256: Sha256
    byte_size: int = Field(gt=0)
    decodable: bool
    duration_agrees: bool
    sample_rate_agrees: bool
    channel_count_agrees: bool
    sample_format_agrees: bool
    valid: bool
    findings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validity_matches_checks(self) -> "MaterializedChunkIntegrity":
        expected = all(
            (
                self.decodable,
                self.duration_agrees,
                self.sample_rate_agrees,
                self.channel_count_agrees,
                self.sample_format_agrees,
            )
        )
        if self.valid != expected:
            raise ValueError("materialized chunk validity is inconsistent")
        return self


class MaterializedChunk(Contract):
    format_version: Literal["1.0.0"] = MATERIALIZED_CHUNK_FORMAT_VERSION
    materialized_chunk_id: str = Field(
        pattern=r"^materialized_[a-f0-9]{32}$"
    )
    chunk_id: str = Field(pattern=r"^chunk_[a-f0-9]{32}$")
    ordinal: int = Field(ge=0)
    source_derivative_id: str = Field(pattern=r"^derivative_[a-f0-9]{32}$")
    source_derivative_sha256: Sha256
    relative_path: str = Field(min_length=1)
    reason: Literal["provider_required", "manual_export", "qualification"]
    corpus_interval: MediaInterval
    source_interval: MediaInterval
    derivative_local_interval: MediaInterval
    output_format: Literal["flac"] = "flac"
    codec: Literal["flac"] = "flac"
    sample_rate: int = Field(gt=0)
    channels: int = Field(gt=0)
    sample_format: str = Field(min_length=1)
    expected_duration_microseconds: int = Field(gt=0)
    actual_duration_microseconds: int = Field(gt=0)
    integrity: MaterializedChunkIntegrity
    tool: ExternalToolIdentity
    invocation: ToolInvocationRecord


class MaterializedChunkEntry(Contract):
    format_version: Literal["1.0.0"] = MATERIALIZED_CHUNK_FORMAT_VERSION
    key: ChunkMaterializationKey
    created_at: datetime
    materialized_chunk: MaterializedChunk
    complete: bool = True


class ChunkMaterializationResult(Contract):
    policy: ChunkMaterializationPolicy
    cache_disposition: CacheDisposition
    cache_key: ChunkMaterializationKey
    cache_entry_path: str
    materialized_chunk: MaterializedChunk


MATERIALIZATION_CONTRACT_MODELS = (
    ChunkMaterializationPolicy,
    ChunkMaterializationKey,
    MaterializedChunkIntegrity,
    MaterializedChunk,
    MaterializedChunkEntry,
    ChunkMaterializationResult,
)
