"""Bounded local energy-activity baseline over Phase 1 normalized audio."""

from __future__ import annotations

import math
import subprocess
import sys
from array import array
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .addressing_contracts import MediaInterval, TimeDomain
from .kernel import canonical_hash, typed_id
from .media import sha256_file
from .phase1_contracts import ToolInvocationRecord
from .phase2_contracts import (
    ConfidenceMeasure,
    ConfidenceOrigin,
    RawEvidenceDisposition,
    RawProviderEvidence,
    SpeechActivityClassification,
    SpeechActivityInterval,
    SpeechActivityRequest,
    SpeechActivityRun,
    SpeechBoundaryEvidence,
    SpeechEvidenceCapability,
    SpeechEvidenceFailureKind,
    SpeechEvidenceProviderCapabilities,
    SpeechEvidenceProviderIdentity,
)
from .qualification import _version, discover_ffmpeg
from .speech_providers import SpeechActivityProvider, SpeechProviderError


@dataclass(frozen=True)
class EnergyActivityConfiguration:
    sample_rate: int = 16_000
    frame_duration_microseconds: int = 30_000
    quiet_rms: float = 0.003
    active_rms: float = 0.02

    def __post_init__(self) -> None:
        if self.sample_rate <= 0:
            raise ValueError("sample rate must be positive")
        samples = self.sample_rate * self.frame_duration_microseconds
        if samples % 1_000_000:
            raise ValueError("frame duration must contain an integer sample count")
        if not 0 <= self.quiet_rms < self.active_rms <= 1:
            raise ValueError("energy thresholds must be ordered within [0, 1]")

    @property
    def samples_per_frame(self) -> int:
        return self.sample_rate * self.frame_duration_microseconds // 1_000_000


class _DecodeFailure(SpeechProviderError):
    def __init__(
        self,
        kind: SpeechEvidenceFailureKind,
        message: str,
        invocation: ToolInvocationRecord,
    ):
        super().__init__(message)
        self.kind = kind
        self.invocation = invocation


def _seconds(microseconds: int) -> str:
    whole, fraction = divmod(microseconds, 1_000_000)
    return f"{whole}.{fraction:06d}"


class FFmpegEnergySpeechActivityProvider(SpeechActivityProvider):
    """Deterministic activity baseline; energy is not semantic speech proof."""

    def __init__(
        self,
        ffmpeg: str | None = None,
        configuration: EnergyActivityConfiguration | None = None,
    ):
        self.configuration = configuration or EnergyActivityConfiguration()
        self.executable = discover_ffmpeg(ffmpeg)
        self.tool = _version(self.executable, 60)
        fingerprint = canonical_hash(
            {
                "configuration": asdict(self.configuration),
                "tool": self.tool.model_dump(
                    mode="json", exclude={"executable"}
                ),
            }
        )
        self._identity = SpeechEvidenceProviderIdentity(
            provider_id="local.ffmpeg_energy_activity",
            display_name="Local FFmpeg PCM energy activity baseline",
            provider_version="1.0.0",
            model_id="ratiocinatus-energy-rms-baseline",
            model_version="1.0.0",
            model_fingerprint=canonical_hash(asdict(self.configuration)),
            runtime_fingerprint=fingerprint,
            local=True,
            license_expression="Apache-2.0",
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
                "Energy is an activity proxy and cannot distinguish speech "
                "from music, noise, or non-lexical vocalization.",
                "Confidence is a deterministic uncalibrated RMS-derived score.",
                "Boundaries are quantized to fixed PCM analysis frames.",
            ),
        )

    def _decode_chunk(
        self,
        source: Path,
        *,
        start_microseconds: int,
        duration_microseconds: int,
        timeout_seconds: int,
    ) -> tuple[array, ToolInvocationRecord]:
        arguments = (
            "-hide_banner",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(source),
            "-ss",
            _seconds(start_microseconds),
            "-t",
            _seconds(duration_microseconds),
            "-map",
            "0:a:0",
            "-ac",
            "1",
            "-ar",
            str(self.configuration.sample_rate),
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-",
        )
        started = datetime.now(timezone.utc)
        try:
            completed = subprocess.run(
                [str(self.executable), *arguments],
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
                shell=False,
            )
            timed_out = False
            exit_code = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr.decode("utf-8", errors="replace")
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            exit_code = -1
            stdout = exc.stdout or b""
            raw_stderr = exc.stderr or b""
            stderr = (
                raw_stderr.decode("utf-8", errors="replace")
                if isinstance(raw_stderr, bytes)
                else raw_stderr
            )
        finished = datetime.now(timezone.utc)
        invocation = ToolInvocationRecord(
            executable=str(self.executable),
            arguments=arguments,
            started_at=started,
            completed_at=finished,
            exit_code=exit_code,
            standard_output="",
            standard_error=stderr,
            timed_out=timed_out,
        )
        if timed_out:
            raise _DecodeFailure(
                SpeechEvidenceFailureKind.TIMEOUT,
                "PCM activity decode timed out",
                invocation,
            )
        if exit_code != 0:
            raise _DecodeFailure(
                SpeechEvidenceFailureKind.PROVIDER_UNAVAILABLE,
                f"FFmpeg PCM activity decode exited with {exit_code}",
                invocation,
            )
        if len(stdout) % 2:
            raise _DecodeFailure(
                SpeechEvidenceFailureKind.MALFORMED_OUTPUT,
                "FFmpeg returned an odd PCM byte count",
                invocation,
            )
        samples = array("h")
        samples.frombytes(stdout)
        if sys.byteorder != "little":
            samples.byteswap()
        return samples, invocation

    def _score(self, samples: array, start: int, end: int) -> float:
        if start >= end:
            return 0.0
        mean_square = sum(
            (sample / 32768.0) ** 2 for sample in samples[start:end]
        ) / (end - start)
        rms = math.sqrt(mean_square)
        return max(
            0.0,
            min(
                1.0,
                (rms - self.configuration.quiet_rms)
                / (
                    self.configuration.active_rms
                    - self.configuration.quiet_rms
                ),
            ),
        )

    def _confidence(self, score: float) -> ConfidenceMeasure:
        return ConfidenceMeasure(
            value=score,
            origin=ConfidenceOrigin.DERIVED,
            basis=(
                "linear normalized RMS between configured quiet and active "
                "energy thresholds"
            ),
        )

    def _raw_evidence_explanation(self) -> str:
        return (
            "Canonical hash of normalized energy observations; transient PCM "
            "was not retained."
        )
    def _boundary_confidence_basis(self) -> str:
        return "energy baseline supplies no boundary probability"
    def _interval_findings(
        self,
        classification: SpeechActivityClassification,
    ) -> tuple[str, ...]:
        if classification == SpeechActivityClassification.PROBABLE_SPEECH:
            return (
                "energy-only activity cannot distinguish speech from music, "
                "noise, or non-lexical vocalization",
            )
        return ()
    @staticmethod
    def _classification(
        score: float,
        request: SpeechActivityRequest,
    ) -> SpeechActivityClassification:
        if score >= request.policy.speech_threshold:
            return SpeechActivityClassification.PROBABLE_SPEECH
        if score <= request.policy.non_speech_threshold:
            return SpeechActivityClassification.PROBABLE_NON_SPEECH
        return SpeechActivityClassification.UNCERTAIN

    def detect(
        self,
        request: SpeechActivityRequest,
        normalized_audio: Path,
    ) -> SpeechActivityRun:
        source = normalized_audio.resolve(strict=True)
        if request.provider != self._identity:
            raise ValueError("request belongs to a different activity provider")
        if sha256_file(source) != request.normalized_audio_sha256:
            raise ValueError("normalized audio hash does not match request")
        started = datetime.now(timezone.utc)
        spans: list[
            tuple[
                str,
                SpeechActivityClassification,
                int,
                int,
                float,
            ]
        ] = []
        invocations: list[ToolInvocationRecord] = []
        try:
            for chunk in request.chunks:
                samples, invocation = self._decode_chunk(
                    source,
                    start_microseconds=(
                        chunk.corpus_interval.start_microseconds
                    ),
                    duration_microseconds=(
                        chunk.corpus_interval.duration_microseconds
                    ),
                    timeout_seconds=request.policy.timeout_seconds,
                )
                invocations.append(invocation)
                ownership = chunk.ownership_interval
                ownership_start = ownership.start_microseconds
                ownership_end = (
                    ownership_start + ownership.duration_microseconds
                )
                frame_samples = self.configuration.samples_per_frame
                owned_end = ownership_start
                for sample_start in range(0, len(samples), frame_samples):
                    sample_end = min(
                        sample_start + frame_samples, len(samples)
                    )
                    frame_start = (
                        chunk.corpus_interval.start_microseconds
                        + sample_start
                        * 1_000_000
                        // self.configuration.sample_rate
                    )
                    frame_end = (
                        chunk.corpus_interval.start_microseconds
                        + sample_end
                        * 1_000_000
                        // self.configuration.sample_rate
                    )
                    clipped_start = max(frame_start, ownership_start)
                    clipped_end = min(frame_end, ownership_end)
                    if clipped_end <= clipped_start:
                        continue
                    score = self._score(samples, sample_start, sample_end)
                    spans.append(
                        (
                            chunk.chunk_id,
                            self._classification(score, request),
                            clipped_start,
                            clipped_end,
                            score,
                        )
                    )
                    owned_end = max(owned_end, clipped_end)
                remainder = ownership_end - owned_end
                if remainder > self.configuration.frame_duration_microseconds:
                    raise _DecodeFailure(
                        SpeechEvidenceFailureKind.MALFORMED_OUTPUT,
                        "PCM decode leaves more than one analysis frame "
                        "without samples",
                        invocation,
                    )
                if remainder > 0:
                    spans.append(
                        (
                            chunk.chunk_id,
                            SpeechActivityClassification.UNCERTAIN,
                            owned_end,
                            ownership_end,
                            (
                                request.policy.speech_threshold
                                + request.policy.non_speech_threshold
                            )
                            / 2,
                        )
                    )
        except _DecodeFailure as exc:
            if not invocations or invocations[-1] != exc.invocation:
                invocations.append(exc.invocation)
            return SpeechActivityRun(
                run_id=typed_id(
                    "sarun", request.request_id, exc.kind.value, str(exc)
                ),
                request=request,
                provider=self._identity,
                started_at=started,
                completed_at=datetime.now(timezone.utc),
                intervals=(),
                boundaries=(),
                raw_evidence=RawProviderEvidence(
                    disposition=RawEvidenceDisposition.UNAVAILABLE,
                    explanation=str(exc),
                ),
                invocations=tuple(invocations),
                failure=exc.kind,
                failure_message=str(exc),
                complete=False,
            )
        if not spans:
            return SpeechActivityRun(
                run_id=typed_id("sarun", request.request_id, "no-output"),
                request=request,
                provider=self._identity,
                started_at=started,
                completed_at=datetime.now(timezone.utc),
                intervals=(),
                boundaries=(),
                raw_evidence=RawProviderEvidence(
                    disposition=RawEvidenceDisposition.UNAVAILABLE,
                    explanation="PCM activity analysis produced no frames",
                ),
                invocations=tuple(invocations),
                failure=SpeechEvidenceFailureKind.MALFORMED_OUTPUT,
                failure_message="PCM activity analysis produced no frames",
                complete=False,
            )

        grouped: list[
            tuple[
                str,
                SpeechActivityClassification,
                int,
                int,
                list[float],
            ]
        ] = []
        for chunk_id, classification, start_us, end_us, score in spans:
            if (
                grouped
                and grouped[-1][0] == chunk_id
                and grouped[-1][1] == classification
                and grouped[-1][3] == start_us
            ):
                previous = grouped[-1]
                grouped[-1] = (
                    previous[0],
                    previous[1],
                    previous[2],
                    end_us,
                    [*previous[4], score],
                )
            else:
                grouped.append(
                    (chunk_id, classification, start_us, end_us, [score])
                )

        adjusted = []
        for chunk_id, classification, start_us, end_us, scores in grouped:
            duration = end_us - start_us
            if (
                classification
                == SpeechActivityClassification.PROBABLE_SPEECH
                and duration < request.policy.minimum_speech_microseconds
            ) or (
                classification
                == SpeechActivityClassification.PROBABLE_NON_SPEECH
                and duration < request.policy.minimum_silence_microseconds
            ):
                classification = SpeechActivityClassification.UNCERTAIN
            adjusted.append(
                (chunk_id, classification, start_us, end_us, scores)
            )

        boundaries: dict[int, SpeechBoundaryEvidence] = {}
        intervals = []
        for chunk_id, classification, start_us, end_us, scores in adjusted:
            for position in (start_us, end_us):
                boundaries.setdefault(
                    position,
                    SpeechBoundaryEvidence(
                        boundary_id=typed_id(
                            "boundary", request.request_id, position
                        ),
                        normalized_audio_microseconds=position,
                        source_microseconds=(
                            position
                            + request.source_mapping_offset_microseconds
                        ),
                        uncertainty_microseconds=(
                            self.configuration.frame_duration_microseconds
                        ),
                        confidence=ConfidenceMeasure(
                            origin=ConfidenceOrigin.UNAVAILABLE,
                            basis=self._boundary_confidence_basis(),
                        ),
                    ),
                )
            average_score = sum(scores) / len(scores)
            findings = self._interval_findings(classification)
            intervals.append(
                SpeechActivityInterval(
                    interval_id=typed_id(
                        "speech",
                        request.request_id,
                        chunk_id,
                        classification.value,
                        start_us,
                        end_us,
                        round(average_score, 12),
                    ),
                    corpus_id=request.corpus_id,
                    source_interval=MediaInterval(
                        domain=TimeDomain.SOURCE_MEDIA,
                        start_microseconds=(
                            start_us
                            + request.source_mapping_offset_microseconds
                        ),
                        duration_microseconds=end_us - start_us,
                    ),
                    normalized_audio_interval=MediaInterval(
                        domain=TimeDomain.NORMALIZED_CORPUS,
                        start_microseconds=start_us,
                        duration_microseconds=end_us - start_us,
                    ),
                    processing_chunk_id=chunk_id,
                    classification=classification,
                    speech_presence_confidence=self._confidence(
                        average_score
                    ),
                    start_boundary_id=boundaries[start_us].boundary_id,
                    end_boundary_id=boundaries[end_us].boundary_id,
                    canonical_owner=True,
                    findings=findings,
                )
            )
        evidence_hash = canonical_hash(
            {
                "request_id": request.request_id,
                "provider": self._identity.model_dump(mode="json"),
                "intervals": [
                    item.model_dump(mode="json") for item in intervals
                ],
            }
        )
        run_id = typed_id("sarun", request.request_id, evidence_hash)
        return SpeechActivityRun(
            run_id=run_id,
            request=request,
            provider=self._identity,
            started_at=started,
            completed_at=datetime.now(timezone.utc),
            intervals=tuple(intervals),
            boundaries=tuple(
                boundaries[key] for key in sorted(boundaries)
            ),
            raw_evidence=RawProviderEvidence(
                disposition=RawEvidenceDisposition.HASH_ONLY,
                content_sha256=evidence_hash,
                explanation=self._raw_evidence_explanation(),
            ),
            invocations=tuple(invocations),
            complete=True,
        )
