"""Audio normalization, derivative integrity, and cache contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .addressing_contracts import IntervalMapping
from .contracts import Contract, Sha256, SourceFingerprint
from .phase1_contracts import ExternalToolIdentity, ToolInvocationRecord

NORMALIZATION_POLICY_VERSION = "1.0.0"
AUDIO_DERIVATIVE_FORMAT_VERSION = "1.0.0"
CACHE_FORMAT_VERSION = "1.0.0"


class CacheDisposition(str, Enum):
    HIT = "hit"
    MISS = "miss"
    INVALID = "invalid"
    STALE = "stale"
    CORRUPTED = "corrupted"
    INCOMPATIBLE = "incompatible"
    BYPASSED = "bypassed"
    REBUILT = "rebuilt"


class NormalizationPolicy(Contract):
    policy_version: Literal["1.0.0"] = NORMALIZATION_POLICY_VERSION
    preserve_timeline_content: bool = True
    remove_silence: Literal[False] = False
    denoise: Literal[False] = False
    enhance_voice: Literal[False] = False
    dynamic_range_compression: Literal[False] = False
    change_tempo_or_pitch: Literal[False] = False


class AudioNormalizationPolicy(NormalizationPolicy):
    output_format: Literal["flac"] = "flac"
    codec: Literal["flac"] = "flac"
    sample_rate: int = Field(default=16_000, ge=8_000, le=96_000)
    channels: Literal[1] = 1
    sample_format: Literal["s16"] = "s16"
    downmix_policy: Literal["equal_weight_average_no_gain"] = (
        "equal_weight_average_no_gain"
    )
    resampler: Literal["ffmpeg-libswresample"] = "ffmpeg-libswresample"
    compression_level: int = Field(default=5, ge=0, le=12)
    duration_tolerance_microseconds: int = Field(
        default=100_000, ge=0, le=2_000_000
    )
    timeout_seconds: int = Field(default=3600, ge=1, le=86_400)
    invalid_cache_action: Literal["rebuild", "refuse"] = "rebuild"


class DerivativeIntegrityRecord(Contract):
    derivative_sha256: Sha256
    byte_size: int = Field(gt=0)
    decodable: bool
    duration_agrees: bool
    sample_rate_agrees: bool
    channel_count_agrees: bool
    sample_format_agrees: bool
    valid: bool
    findings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validity_matches_checks(self) -> "DerivativeIntegrityRecord":
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
            raise ValueError("derivative integrity validity is inconsistent")
        return self


class WorkingDerivative(Contract):
    format_version: Literal["1.0.0"] = AUDIO_DERIVATIVE_FORMAT_VERSION
    derivative_id: str = Field(pattern=r"^derivative_[a-f0-9]{32}$")
    source_id: str = Field(pattern=r"^src_[a-f0-9]{32}$")
    source_stream_id: str = Field(pattern=r"^stream_[a-f0-9]{32}$")
    relative_path: str = Field(min_length=1)
    content_sha256: Sha256
    byte_size: int = Field(gt=0)
    duration_microseconds: int = Field(gt=0)
    interval_mapping: IntervalMapping
    integrity: DerivativeIntegrityRecord
    tool: ExternalToolIdentity
    invocation: ToolInvocationRecord


class AudioDerivative(WorkingDerivative):
    media_type: Literal["audio"] = "audio"
    output_format: Literal["flac"] = "flac"
    codec: Literal["flac"] = "flac"
    sample_rate: int = Field(gt=0)
    sample_count: int | None = Field(default=None, gt=0)
    channels: Literal[1] = 1
    sample_format: Literal["s16"] = "s16"
    original_channel_layout: str | None = None
    original_channel_count: int = Field(gt=0)
    downmix_policy: str
    resampler: str


class CacheKey(Contract):
    format_version: Literal["1.0.0"] = CACHE_FORMAT_VERSION
    cache_id: str = Field(pattern=r"^cache_[a-f0-9]{32}$")
    digest: Sha256
    operation: Literal["audio.normalize"] = "audio.normalize"
    operation_version: Literal["1.0.0"] = NORMALIZATION_POLICY_VERSION
    source_fingerprint: SourceFingerprint
    source_stream_id: str = Field(pattern=r"^stream_[a-f0-9]{32}$")
    configuration_hash: Sha256
    provider_identity: str
    external_tool_identity_hash: Sha256
    artifact_format_version: Literal["1.0.0"] = AUDIO_DERIVATIVE_FORMAT_VERSION


class CacheEntry(Contract):
    format_version: Literal["1.0.0"] = CACHE_FORMAT_VERSION
    key: CacheKey
    created_at: datetime
    derivative: AudioDerivative
    complete: bool = True


class AudioNormalizationResult(Contract):
    policy: AudioNormalizationPolicy
    cache_disposition: CacheDisposition
    cache_key: CacheKey
    cache_entry_path: str
    derivative: AudioDerivative


NORMALIZATION_CONTRACT_MODELS = (
    NormalizationPolicy,
    AudioNormalizationPolicy,
    DerivativeIntegrityRecord,
    WorkingDerivative,
    AudioDerivative,
    CacheKey,
    CacheEntry,
    AudioNormalizationResult,
)
