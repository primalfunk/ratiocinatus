"""Optional local Silero semantic voice-activity provider."""

from __future__ import annotations

from array import array
from dataclasses import asdict, dataclass
from importlib.metadata import version
from pathlib import Path

from .activity import FFmpegEnergySpeechActivityProvider
from .contracts import Sha256
from .kernel import canonical_hash
from .media import sha256_file
from .phase2_contracts import (
    ConfidenceMeasure,
    ConfidenceOrigin,
    SpeechActivityClassification,
    SpeechEvidenceCapability,
    SpeechEvidenceProviderCapabilities,
    SpeechEvidenceProviderIdentity,
)
from .qualification import _version, discover_ffmpeg
from .speech_providers import SpeechProviderUnavailable


@dataclass(frozen=True)
class SileroActivityConfiguration:
    sample_rate: int = 16_000
    frame_duration_microseconds: int = 32_000

    def __post_init__(self) -> None:
        if self.sample_rate != 16_000:
            raise ValueError("the initial Silero provider requires 16 kHz audio")
        if self.frame_duration_microseconds != 32_000:
            raise ValueError(
                "the initial Silero provider requires 512-sample frames"
            )

    @property
    def samples_per_frame(self) -> int:
        return self.sample_rate * self.frame_duration_microseconds // 1_000_000


class SileroSpeechActivityProvider(FFmpegEnergySpeechActivityProvider):
    """Silero VAD 6.2.1 with Ratiocinatus-owned mapping and persistence."""

    INTEGRATION_VERSION = "1.0.0"
    EXPECTED_PACKAGE_VERSION = "6.2.1"
    EXPECTED_MODEL_SHA256: Sha256 = (
        "e1122837f4154c511485fe0b9c64455f7b929c96fbb8d79fbdb336383ebd3720"
    )

    def __init__(
        self,
        ffmpeg: str | None = None,
        configuration: SileroActivityConfiguration | None = None,
    ):
        import silero_vad
        import torch
        from silero_vad import load_silero_vad

        package_version = version("silero-vad")
        if package_version != self.EXPECTED_PACKAGE_VERSION:
            raise SpeechProviderUnavailable(
                f"unsupported silero-vad {package_version}; "
                f"expected {self.EXPECTED_PACKAGE_VERSION}"
            )
        self.configuration = configuration or SileroActivityConfiguration()
        self.executable = discover_ffmpeg(ffmpeg)
        self.tool = _version(self.executable, 60)
        self._torch = torch
        model_path = (
            Path(silero_vad.__file__).resolve().parent
            / "data"
            / "silero_vad.jit"
        )
        model_hash = sha256_file(model_path)
        if model_hash != self.EXPECTED_MODEL_SHA256:
            raise SpeechProviderUnavailable(
                "Silero model artifact hash does not match the qualified pin"
            )
        self.model = load_silero_vad(onnx=False)

        runtime_fingerprint = canonical_hash(
            {
                "integration_version": self.INTEGRATION_VERSION,
                "package": {
                    "name": "silero-vad",
                    "version": package_version,
                },
                "model_sha256": model_hash,
                "torch_version": torch.__version__,
                "configuration": asdict(self.configuration),
                "ffmpeg": self.tool.model_dump(
                    mode="json", exclude={"executable"}
                ),
            }
        )
        self._identity = SpeechEvidenceProviderIdentity(
            provider_id="local.silero_vad",
            display_name="Local Silero semantic voice activity detector",
            provider_version=self.INTEGRATION_VERSION,
            model_id="snakers4/silero-vad",
            model_version=package_version,
            model_fingerprint=model_hash,
            runtime_fingerprint=runtime_fingerprint,
            local=True,
            license_expression="MIT",
            model_redistributed=False,
        )

    @property
    def capabilities(self) -> SpeechEvidenceProviderCapabilities:
        return SpeechEvidenceProviderCapabilities(
            identity=self._identity,
            capabilities=(SpeechEvidenceCapability.SPEECH_ACTIVITY,),
            available=True,
            speech_confidence=True,
            raw_response_retention=False,
            cancellation_boundaries=("between_phase1_chunks",),
            limitations=(
                "Provider-native probabilities are not calibrated by "
                "Ratiocinatus for this corpus.",
                "Boundaries are quantized to 512-sample model frames before "
                "Phase 2 interval assembly.",
                "The optional MIT-licensed model package is installed "
                "separately and is not redistributed by this repository.",
            ),
        )

    def _decode_chunk(self, *args, **kwargs):
        samples, invocation = super()._decode_chunk(*args, **kwargs)
        self.model.reset_states()
        return samples, invocation

    def _score(self, samples: array, start: int, end: int) -> float:
        frame = self._torch.tensor(
            samples[start:end], dtype=self._torch.float32
        ) / 32768.0
        missing = self.configuration.samples_per_frame - frame.numel()
        if missing:
            frame = self._torch.nn.functional.pad(frame, (0, missing))
        with self._torch.inference_mode():
            return float(
                self.model(frame, self.configuration.sample_rate).item()
            )

    def _confidence(self, score: float) -> ConfidenceMeasure:
        return ConfidenceMeasure(
            value=score,
            origin=ConfidenceOrigin.PROVIDER_NATIVE,
            basis=(
                "mean Silero VAD frame speech probability over the assembled "
                "interval"
            ),
        )

    def _interval_findings(
        self,
        classification: SpeechActivityClassification,
    ) -> tuple[str, ...]:
        return ()

    def _boundary_confidence_basis(self) -> str:
        return (
            "Silero supplies frame speech probabilities but no independently "
            "calibrated boundary probability"
        )
    def _raw_evidence_explanation(self) -> str:
        return (
            "Canonical hash of normalized Silero frame observations; "
            "transient PCM and model tensors were not retained."
        )
