"""Provider-independent Phase 5 discourse-analysis boundary."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .phase5_contracts import (
    DiscourseProviderCapabilities,
    DiscourseProviderCapability,
    DiscourseProviderIdentity,
)
from .phase5_provider_analysis_contracts import (
    BoundedDiscourseProviderRequest,
    ProviderAnalysisResponse,
)


class DiscourseProviderError(RuntimeError):
    """Typed failure before authoritative discourse persistence."""


class DiscourseProviderUnavailable(DiscourseProviderError):
    pass


class DiscourseModelUnavailable(DiscourseProviderError):
    pass


class DiscourseProviderTimeout(DiscourseProviderError):
    pass


class MalformedDiscourseProviderOutput(DiscourseProviderError):
    pass


class DiscourseProvider(ABC):
    @property
    @abstractmethod
    def capabilities(self) -> DiscourseProviderCapabilities: ...

    @abstractmethod
    def analyze(
        self, request: BoundedDiscourseProviderRequest
    ) -> ProviderAnalysisResponse: ...


class UnconfiguredDiscourseProvider(DiscourseProvider):
    """Visible refusal boundary until a local provider is qualified."""

    @property
    def capabilities(self) -> DiscourseProviderCapabilities:
        return DiscourseProviderCapabilities(
            identity=DiscourseProviderIdentity(
                provider_id="unconfigured.discourse",
                display_name="Unconfigured local discourse provider",
                provider_version="0.1.0",
                local=True,
            ),
            capabilities=(
                DiscourseProviderCapability.MULTI_LABEL_CLASSIFICATION,
                DiscourseProviderCapability.EVIDENCE_SPANS,
                DiscourseProviderCapability.STRUCTURED_OUTPUT,
            ),
            available=False,
            deterministic=False,
            limitations=(
                "Provider boundary only; no discourse model is configured.",
                "Provider proposals never become authoritative without "
                "normalization, validation, and selection.",
            ),
        )

    def analyze(
        self, request: BoundedDiscourseProviderRequest
    ) -> ProviderAnalysisResponse:
        raise DiscourseProviderUnavailable(
            "no discourse provider is configured"
        )


class DiscourseProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, DiscourseProvider] = {}

    def register(self, provider: DiscourseProvider) -> None:
        provider_id = provider.capabilities.identity.provider_id
        if provider_id in self._providers:
            raise ValueError(
                f"duplicate discourse provider identity: {provider_id}"
            )
        self._providers[provider_id] = provider

    def list(self) -> tuple[DiscourseProviderCapabilities, ...]:
        return tuple(
            sorted(
                (
                    provider.capabilities
                    for provider in self._providers.values()
                ),
                key=lambda item: item.identity.provider_id,
            )
        )

    def get(self, provider_id: str) -> DiscourseProvider:
        try:
            return self._providers[provider_id]
        except KeyError as exc:
            raise DiscourseProviderUnavailable(
                f"unknown discourse provider: {provider_id}"
            ) from exc

    @classmethod
    def with_boundaries(cls) -> "DiscourseProviderRegistry":
        registry = cls()
        registry.register(UnconfiguredDiscourseProvider())
        return registry
