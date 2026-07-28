"""Provider-independent Phase 3 diarization boundary."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from .phase3_contracts import (
    DiarizationCapability,
    DiarizationProviderCapabilities,
    DiarizationProviderIdentity,
    DiarizationProviderResponse,
    DiarizationRequest,
)


class DiarizationProviderError(RuntimeError):
    """Typed failure before authoritative Phase 3 persistence."""


class DiarizationProviderUnavailable(DiarizationProviderError):
    pass


class MalformedDiarizationProviderOutput(DiarizationProviderError):
    pass


class DiarizationProvider(ABC):
    @property
    @abstractmethod
    def capabilities(self) -> DiarizationProviderCapabilities: ...

    @abstractmethod
    def diarize(
        self,
        request: DiarizationRequest,
        normalized_audio: Path,
        *,
        evidence_root: Path | None = None,
    ) -> DiarizationProviderResponse: ...


class UnconfiguredDiarizationProvider(DiarizationProvider):
    """Visible refusal boundary until a local provider is qualified."""

    @property
    def capabilities(self) -> DiarizationProviderCapabilities:
        return DiarizationProviderCapabilities(
            identity=DiarizationProviderIdentity(
                provider_id="unconfigured.diarization",
                display_name="Unconfigured local diarization provider",
                provider_version="0.1.0",
                local=True,
            ),
            capabilities=(DiarizationCapability.TURN_SEGMENTATION,),
            available=False,
            limitations=(
                "Provider boundary only; no diarization model is configured.",
                "No speaker cluster or provider label represents a person.",
            ),
        )

    def diarize(
        self,
        request: DiarizationRequest,
        normalized_audio: Path,
        *,
        evidence_root: Path | None = None,
    ) -> DiarizationProviderResponse:
        raise DiarizationProviderUnavailable(
            "no diarization provider is configured"
        )


class DiarizationProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, DiarizationProvider] = {}

    def register(self, provider: DiarizationProvider) -> None:
        provider_id = provider.capabilities.identity.provider_id
        if provider_id in self._providers:
            raise ValueError(
                f"duplicate diarization provider identity: {provider_id}"
            )
        self._providers[provider_id] = provider

    def list(self) -> tuple[DiarizationProviderCapabilities, ...]:
        return tuple(
            sorted(
                (provider.capabilities for provider in self._providers.values()),
                key=lambda item: item.identity.provider_id,
            )
        )

    def get(self, provider_id: str) -> DiarizationProvider:
        try:
            return self._providers[provider_id]
        except KeyError as exc:
            raise DiarizationProviderUnavailable(
                f"unknown diarization provider: {provider_id}"
            ) from exc

    @classmethod
    def with_boundaries(cls) -> "DiarizationProviderRegistry":
        registry = cls()
        registry.register(UnconfiguredDiarizationProvider())
        return registry
