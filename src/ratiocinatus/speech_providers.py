"""Provider-independent Phase 2 speech activity and transcription boundaries."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from .media import ToolUnavailableError

from .phase2_contracts import (
    SpeechActivityRequest,
    SpeechActivityRun,
    SpeechEvidenceCapability,
    SpeechEvidenceProviderCapabilities,
    SpeechEvidenceProviderIdentity,
    TranscriptionProviderResponse,
    TranscriptionRequest,
)


class SpeechProviderError(RuntimeError):
    """A typed provider-boundary failure before authoritative persistence."""


class SpeechProviderUnavailable(SpeechProviderError):
    pass


class MalformedSpeechProviderOutput(SpeechProviderError):
    pass


class SpeechEvidenceProvider(ABC):
    @property
    @abstractmethod
    def capabilities(self) -> SpeechEvidenceProviderCapabilities: ...


class SpeechActivityProvider(SpeechEvidenceProvider):
    @abstractmethod
    def detect(
        self,
        request: SpeechActivityRequest,
        normalized_audio: Path,
    ) -> SpeechActivityRun: ...


class TranscriptionProvider(SpeechEvidenceProvider):
    @abstractmethod
    def transcribe(
        self,
        request: TranscriptionRequest,
        normalized_audio: Path,
        *,
        evidence_root: Path | None = None,
    ) -> TranscriptionProviderResponse: ...


class UnconfiguredSpeechActivityProvider(SpeechActivityProvider):
    """Visible placeholder until the initial local provider is selected."""

    @property
    def capabilities(self) -> SpeechEvidenceProviderCapabilities:
        return SpeechEvidenceProviderCapabilities(
            identity=SpeechEvidenceProviderIdentity(
                provider_id="unconfigured.speech_activity",
                display_name="Unconfigured local speech activity provider",
                provider_version="0.1.0",
                local=True,
            ),
            capabilities=(SpeechEvidenceCapability.SPEECH_ACTIVITY,),
            available=False,
            limitations=(
                "Provider boundary only; no speech activity model is configured.",
            ),
        )

    def detect(
        self,
        request: SpeechActivityRequest,
        normalized_audio: Path,
    ) -> SpeechActivityRun:
        raise SpeechProviderUnavailable(
            "no speech activity provider is configured"
        )


class UnconfiguredTranscriptionProvider(TranscriptionProvider):
    """Visible placeholder that cannot produce invented transcript text."""

    @property
    def capabilities(self) -> SpeechEvidenceProviderCapabilities:
        return SpeechEvidenceProviderCapabilities(
            identity=SpeechEvidenceProviderIdentity(
                provider_id="unconfigured.transcription",
                display_name="Unconfigured local transcription provider",
                provider_version="0.1.0",
                local=True,
            ),
            capabilities=(SpeechEvidenceCapability.TRANSCRIPTION,),
            available=False,
            limitations=(
                "Provider boundary only; no transcription model is configured.",
            ),
        )

    def transcribe(
        self,
        request: TranscriptionRequest,
        normalized_audio: Path,
        *,
        evidence_root: Path | None = None,
    ) -> TranscriptionProviderResponse:
        raise SpeechProviderUnavailable(
            "no transcription provider is configured"
        )


class SpeechProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, SpeechEvidenceProvider] = {}

    def register(self, provider: SpeechEvidenceProvider) -> None:
        provider_id = provider.capabilities.identity.provider_id
        if provider_id in self._providers:
            raise ValueError(f"duplicate speech provider identity: {provider_id}")
        self._providers[provider_id] = provider

    def list(
        self,
        capability: SpeechEvidenceCapability | None = None,
    ) -> tuple[SpeechEvidenceProviderCapabilities, ...]:
        providers = (
            provider.capabilities for provider in self._providers.values()
        )
        return tuple(
            sorted(
                (
                    item
                    for item in providers
                    if capability is None or capability in item.capabilities
                ),
                key=lambda item: item.identity.provider_id,
            )
        )

    def get(self, provider_id: str) -> SpeechEvidenceProvider:
        try:
            return self._providers[provider_id]
        except KeyError as exc:
            raise SpeechProviderUnavailable(
                f"unknown speech provider: {provider_id}"
            ) from exc

    @classmethod
    def with_boundaries(cls) -> "SpeechProviderRegistry":
        registry = cls()
        registry.register(UnconfiguredSpeechActivityProvider())
        try:
            from .activity import FFmpegEnergySpeechActivityProvider

            registry.register(FFmpegEnergySpeechActivityProvider())
            from .silero_activity import SileroSpeechActivityProvider

            registry.register(SileroSpeechActivityProvider())
        except (ImportError, ToolUnavailableError):
            pass
        registry.register(UnconfiguredTranscriptionProvider())
        try:
            from .whisper_transcription import (
                OpenAIWhisperTranscriptionProvider,
            )

            registry.register(OpenAIWhisperTranscriptionProvider())
        except (ImportError, FileNotFoundError, ToolUnavailableError):
            pass
        return registry
