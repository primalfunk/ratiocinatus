"""Pinned local OpenAI Whisper transcription observation provider."""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any

from .addressing_contracts import MediaInterval, TimeDomain
from .kernel import canonical_bytes, canonical_hash, typed_id
from .media import sha256_file
from .phase1_contracts import ToolInvocationRecord
from .phase2_contracts import (
    ConfidenceMeasure,
    ConfidenceOrigin,
    LanguageMode,
    ProviderTranscriptCandidate,
    ProviderTranscriptObservation,
    ProviderWordObservation,
    RawEvidenceDisposition,
    RawProviderEvidence,
    SpeechEvidenceCapability,
    SpeechEvidenceFailureKind,
    SpeechEvidenceProviderCapabilities,
    SpeechEvidenceProviderIdentity,
    TimestampOrigin,
    TranscriptionProviderResponse,
    TranscriptionRequest,
    WordTimestampPolicy,
)
from .qualification import _version, discover_ffmpeg
from .speech_providers import (
    SpeechProviderUnavailable,
    TranscriptionProvider,
)


@dataclass(frozen=True)
class WhisperTranscriptionConfiguration:
    model_name: str = "small"
    device: str = "auto"


@dataclass(frozen=True)
class _Clip:
    start_microseconds: int
    end_microseconds: int
    speech_interval_ids: tuple[str, ...]
    processing_chunk_ids: tuple[str, ...]


class OpenAIWhisperTranscriptionProvider(TranscriptionProvider):
    INTEGRATION_VERSION = "1.0.0"
    EXPECTED_PACKAGE_VERSION = "20250625"
    EXPECTED_MODEL_SHA256 = (
        "9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794"
    )

    def __init__(
        self,
        *,
        model_path: Path | None = None,
        configuration: WhisperTranscriptionConfiguration | None = None,
        ffmpeg: str | None = None,
    ):
        import torch
        import whisper

        package_version = version("openai-whisper")
        if package_version != self.EXPECTED_PACKAGE_VERSION:
            raise SpeechProviderUnavailable(
                f"unsupported openai-whisper {package_version}; "
                f"expected {self.EXPECTED_PACKAGE_VERSION}"
            )
        self.configuration = configuration or WhisperTranscriptionConfiguration()
        if self.configuration.model_name != "small":
            raise ValueError("the initial provider is qualified only for small")
        self.model_path = (
            model_path
            or Path.home() / ".cache" / "whisper" / "small.pt"
        ).expanduser().resolve(strict=True)
        model_hash = sha256_file(self.model_path)
        if model_hash != self.EXPECTED_MODEL_SHA256:
            raise SpeechProviderUnavailable(
                "Whisper model artifact hash does not match the qualified pin"
            )
        requested_device = self.configuration.device
        if requested_device == "auto":
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        elif requested_device in {"cpu", "cuda"}:
            self.device = requested_device
        else:
            raise ValueError("Whisper device must be auto, cpu, or cuda")
        if self.device == "cuda" and not torch.cuda.is_available():
            raise SpeechProviderUnavailable(
                "CUDA was requested but is unavailable"
            )
        self.executable = discover_ffmpeg(ffmpeg)
        self.tool = _version(self.executable, 60)
        runtime_fingerprint = canonical_hash(
            {
                "integration_version": self.INTEGRATION_VERSION,
                "package_version": package_version,
                "model_sha256": model_hash,
                "configuration": asdict(self.configuration),
                "resolved_device": self.device,
                "torch_version": torch.__version__,
                "ffmpeg": self.tool.model_dump(
                    mode="json", exclude={"executable"}
                ),
            }
        )
        self._identity = SpeechEvidenceProviderIdentity(
            provider_id="local.openai_whisper",
            display_name="Local OpenAI Whisper transcription provider",
            provider_version=self.INTEGRATION_VERSION,
            model_id="openai/whisper-small",
            model_version="small",
            model_fingerprint=model_hash,
            runtime_fingerprint=runtime_fingerprint,
            local=True,
            license_expression="MIT",
            model_redistributed=False,
        )
        self._languages = tuple(sorted(whisper.tokenizer.LANGUAGES))

    @property
    def capabilities(self) -> SpeechEvidenceProviderCapabilities:
        return SpeechEvidenceProviderCapabilities(
            identity=self._identity,
            capabilities=(SpeechEvidenceCapability.TRANSCRIPTION,),
            available=True,
            supported_languages=self._languages,
            automatic_language_proposal=True,
            segment_timestamps=True,
            word_timestamps=True,
            alternative_candidates=False,
            text_confidence=True,
            timing_confidence=False,
            maximum_candidate_count=1,
            raw_response_retention=True,
            cancellation_boundaries=("provider_process",),
            limitations=(
                "The initial provider exposes one decoding candidate only.",
                "Exponentiated average log probability is derived and "
                "uncalibrated; it is not a correctness probability.",
                "Provider-native timestamps have no independent timing score.",
                "The optional MIT-licensed package and model are installed "
                "separately and are not redistributed by this repository.",
            ),
        )

    @staticmethod
    def _clips(request: TranscriptionRequest) -> tuple[_Clip, ...]:
        ordered = sorted(
            request.speech_intervals,
            key=lambda item: item.normalized_audio_interval.start_microseconds,
        )
        merged: list[_Clip] = []
        for item in ordered:
            start = item.normalized_audio_interval.start_microseconds
            end = start + item.normalized_audio_interval.duration_microseconds
            if (
                merged
                and start - merged[-1].end_microseconds
                <= request.policy.merge_gap_microseconds
                and end - merged[-1].start_microseconds
                <= request.policy.maximum_segment_microseconds
            ):
                previous = merged[-1]
                merged[-1] = _Clip(
                    previous.start_microseconds,
                    max(previous.end_microseconds, end),
                    (*previous.speech_interval_ids, item.interval_id),
                    tuple(
                        dict.fromkeys(
                            (
                                *previous.processing_chunk_ids,
                                item.processing_chunk_id,
                            )
                        )
                    ),
                )
            else:
                merged.append(
                    _Clip(
                        start,
                        end,
                        (item.interval_id,),
                        (item.processing_chunk_id,),
                    )
                )
        split: list[_Clip] = []
        maximum = request.policy.maximum_segment_microseconds
        for item in merged:
            cursor = item.start_microseconds
            while cursor < item.end_microseconds:
                end = min(cursor + maximum, item.end_microseconds)
                split.append(
                    _Clip(
                        cursor,
                        end,
                        item.speech_interval_ids,
                        item.processing_chunk_ids,
                    )
                )
                cursor = end
        return tuple(split)

    @staticmethod
    def _overlap(clip: _Clip, start: int, end: int) -> int:
        return max(
            0,
            min(clip.end_microseconds, end)
            - max(clip.start_microseconds, start),
        )

    @staticmethod
    def _unavailable(basis: str) -> ConfidenceMeasure:
        return ConfidenceMeasure(
            origin=ConfidenceOrigin.UNAVAILABLE,
            basis=basis,
        )

    def _observation(
        self,
        request: TranscriptionRequest,
        clip: _Clip,
        segment: dict[str, Any] | None,
    ) -> ProviderTranscriptObservation:
        if segment is None:
            start = clip.start_microseconds
            end = clip.end_microseconds
            segment_reference = None
            candidates: tuple[ProviderTranscriptCandidate, ...] = ()
            selected_candidate_id = None
            findings = (
                "provider returned no lexical segment for selected speech evidence",
            )
        else:
            start = max(
                clip.start_microseconds,
                round(float(segment["start"]) * 1_000_000),
            )
            end = min(
                clip.end_microseconds,
                round(float(segment["end"]) * 1_000_000),
            )
            if end <= start:
                start, end = clip.start_microseconds, clip.end_microseconds
            segment_reference = f"whisper-segment-{segment.get('id', 0)}"
            candidate_id = typed_id(
                "candidate",
                request.request_id,
                segment_reference,
                segment.get("text", ""),
            )
            words = []
            for index, raw_word in enumerate(segment.get("words") or ()):
                word_start = max(
                    start, round(float(raw_word["start"]) * 1_000_000)
                )
                word_end = min(
                    end, round(float(raw_word["end"]) * 1_000_000)
                )
                surface = str(raw_word.get("word", "")).strip()
                if not surface or word_end <= word_start:
                    continue
                probability = raw_word.get("probability")
                recognition = (
                    ConfidenceMeasure(
                        value=max(0.0, min(1.0, float(probability))),
                        origin=ConfidenceOrigin.PROVIDER_NATIVE,
                        basis="Whisper word probability; uncalibrated",
                    )
                    if probability is not None
                    else self._unavailable("Whisper supplied no word probability")
                )
                words.append(
                    ProviderWordObservation(
                        provider_word_id=typed_id(
                            "providerword",
                            request.request_id,
                            segment_reference,
                            index,
                            surface,
                        ),
                        surface_text=surface,
                        sequence_position=len(words),
                        source_interval=MediaInterval(
                            domain=TimeDomain.SOURCE_MEDIA,
                            start_microseconds=(
                                word_start
                                + request.source_mapping_offset_microseconds
                            ),
                            duration_microseconds=word_end - word_start,
                        ),
                        normalized_audio_interval=MediaInterval(
                            domain=TimeDomain.NORMALIZED_CORPUS,
                            start_microseconds=word_start,
                            duration_microseconds=word_end - word_start,
                        ),
                        timestamp_origin=TimestampOrigin.PROVIDER_NATIVE,
                        recognition_confidence=recognition,
                        timing_confidence=self._unavailable(
                            "Whisper supplies timestamps without timing confidence"
                        ),
                        provider_token_reference=str(index),
                        boundary_uncertainty_microseconds=20_000,
                    )
                )
            average_log_probability = segment.get("avg_logprob")
            text_confidence = (
                ConfidenceMeasure(
                    value=max(
                        0.0,
                        min(1.0, math.exp(float(average_log_probability))),
                    ),
                    origin=ConfidenceOrigin.DERIVED,
                    basis=(
                        "exponentiated Whisper segment average log probability; "
                        "uncalibrated"
                    ),
                )
                if average_log_probability is not None
                else self._unavailable(
                    "Whisper supplied no segment average log probability"
                )
            )
            candidate = ProviderTranscriptCandidate(
                provider_candidate_id=candidate_id,
                proposed_text=str(segment.get("text", "")).strip(),
                language=str(segment.get("_language") or "") or None,
                rank=1,
                provider_score=(
                    float(average_log_probability)
                    if average_log_probability is not None
                    else None
                ),
                text_confidence=text_confidence,
                selected=True,
                selection_reason=(
                    "only provider candidate; selected as a fallible observation"
                ),
                words=tuple(words),
            )
            candidates = (candidate,)
            selected_candidate_id = candidate_id
            findings = (
                "candidate selection does not promote text to canonical transcript",
            )
        return ProviderTranscriptObservation(
            observation_id=typed_id(
                "txobs",
                request.request_id,
                start,
                end,
                segment_reference or "no-output",
            ),
            speech_interval_ids=clip.speech_interval_ids,
            source_interval=MediaInterval(
                domain=TimeDomain.SOURCE_MEDIA,
                start_microseconds=(
                    start + request.source_mapping_offset_microseconds
                ),
                duration_microseconds=end - start,
            ),
            normalized_audio_interval=MediaInterval(
                domain=TimeDomain.NORMALIZED_CORPUS,
                start_microseconds=start,
                duration_microseconds=end - start,
            ),
            processing_chunk_ids=clip.processing_chunk_ids,
            provider_segment_reference=segment_reference,
            candidates=candidates,
            selected_candidate_id=selected_candidate_id,
            timing_confidence=self._unavailable(
                "Whisper supplies segment timestamps without timing confidence"
            ),
            boundary_confidence=self._unavailable(
                "speech boundaries remain attributable to Phase 2 activity evidence"
            ),
            findings=findings,
        )

    def _failed(
        self,
        request: TranscriptionRequest,
        started: datetime,
        invocation: ToolInvocationRecord,
        kind: SpeechEvidenceFailureKind,
        message: str,
    ) -> TranscriptionProviderResponse:
        evidence_hash = canonical_hash(
            {
                "request_id": request.request_id,
                "provider": self._identity.model_dump(mode="json"),
                "observations": [],
            }
        )
        return TranscriptionProviderResponse(
            response_id=typed_id(
                "txresponse", request.request_id, kind.value, message
            ),
            request_id=request.request_id,
            provider=self._identity,
            started_at=started,
            completed_at=datetime.now(timezone.utc),
            observations=(),
            normalized_evidence_sha256=evidence_hash,
            raw_evidence=RawProviderEvidence(
                disposition=RawEvidenceDisposition.UNAVAILABLE,
                explanation=message,
            ),
            invocations=(invocation,),
            failure=kind,
            failure_message=message,
            complete=False,
        )

    def transcribe(
        self,
        request: TranscriptionRequest,
        normalized_audio: Path,
        *,
        evidence_root: Path | None = None,
    ) -> TranscriptionProviderResponse:
        if request.provider != self._identity:
            raise ValueError("request belongs to a different transcription provider")
        if request.policy.maximum_candidates != 1:
            raise ValueError("initial Whisper provider supports one candidate")
        source = normalized_audio.resolve(strict=True)
        if sha256_file(source) != request.normalized_audio_sha256:
            raise ValueError("normalized audio hash does not match request")
        clips = self._clips(request)
        active = tuple(
            item
            for item in clips
            if item.end_microseconds - item.start_microseconds
            >= request.policy.minimum_clip_microseconds
        )
        if not active:
            observations = tuple(
                self._observation(request, clip, None) for clip in clips
            )
            evidence_hash = canonical_hash(
                {
                    "request_id": request.request_id,
                    "provider": self._identity.model_dump(mode="json"),
                    "observations": [
                        item.model_dump(mode="json") for item in observations
                    ],
                }
            )
            now = datetime.now(timezone.utc)
            return TranscriptionProviderResponse(
                response_id=typed_id(
                    "txresponse", request.request_id, evidence_hash
                ),
                request_id=request.request_id,
                provider=self._identity,
                started_at=now,
                completed_at=now,
                observations=observations,
                normalized_evidence_sha256=evidence_hash,
                raw_evidence=RawProviderEvidence(
                    disposition=RawEvidenceDisposition.UNAVAILABLE,
                    explanation=(
                        "All selected clips were shorter than the configured "
                        "minimum; no provider inference was attempted."
                    ),
                ),
                complete=True,
            )
        language = (
            request.policy.language
            if request.policy.language_mode == LanguageMode.EXPLICIT
            else None
        )
        clip_timestamps = ",".join(
            f"{item.start_microseconds / 1_000_000:.6f},"
            f"{item.end_microseconds / 1_000_000:.6f}"
            for item in active
        )
        payload = {
            "model_path": str(self.model_path),
            "device": self.device,
            "audio_path": str(source),
            "language": language,
            "temperature": request.policy.decoding_temperature,
            "word_timestamps": (
                request.policy.word_timestamps
                == WordTimestampPolicy.REQUEST_PROVIDER_NATIVE
            ),
            "clip_timestamps": clip_timestamps,
        }
        started = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory(prefix="ratiocinatus-whisper-") as raw_tmp:
            worker_request = Path(raw_tmp) / "request.json"
            worker_request.write_bytes(canonical_bytes(payload))
            arguments = (
                "-m",
                "ratiocinatus.whisper_worker",
                str(worker_request),
            )
            environment = os.environ.copy()
            environment["PATH"] = (
                str(self.executable.parent)
                + os.pathsep
                + environment.get("PATH", "")
            )
            try:
                completed = subprocess.run(
                    [sys.executable, *arguments],
                    capture_output=True,
                    timeout=request.policy.timeout_seconds,
                    check=False,
                    shell=False,
                    env=environment,
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
        invocation = ToolInvocationRecord(
            executable=sys.executable,
            arguments=arguments,
            started_at=started,
            completed_at=datetime.now(timezone.utc),
            exit_code=exit_code,
            standard_output="",
            standard_error=stderr,
            timed_out=timed_out,
        )
        if timed_out:
            return self._failed(
                request,
                started,
                invocation,
                SpeechEvidenceFailureKind.TIMEOUT,
                "Whisper provider process exceeded its timeout",
            )
        if exit_code != 0:
            return self._failed(
                request,
                started,
                invocation,
                SpeechEvidenceFailureKind.PROVIDER_UNAVAILABLE,
                f"Whisper provider process exited with {exit_code}: {stderr}",
            )
        try:
            raw = json.loads(stdout.decode("utf-8"))
            segments = raw.get("segments")
            if not isinstance(segments, list):
                raise ValueError("segments is not a list")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            return self._failed(
                request,
                started,
                invocation,
                SpeechEvidenceFailureKind.MALFORMED_OUTPUT,
                f"Whisper returned malformed JSON: {exc}",
            )
        language_result = raw.get("language")
        observations = []
        represented: set[int] = set()
        for segment in segments:
            if not isinstance(segment, dict) or not str(
                segment.get("text", "")
            ).strip():
                continue
            start = round(float(segment["start"]) * 1_000_000)
            end = round(float(segment["end"]) * 1_000_000)
            candidates = [
                (index, item, self._overlap(item, start, end))
                for index, item in enumerate(active)
            ]
            if not candidates:
                continue
            index, clip, overlap = max(candidates, key=lambda item: item[2])
            if overlap <= 0:
                continue
            represented.add(index)
            normalized = dict(segment)
            normalized["_language"] = language_result
            observations.append(self._observation(request, clip, normalized))
        for index, clip in enumerate(active):
            if index not in represented:
                observations.append(self._observation(request, clip, None))
        for clip in clips:
            if clip not in active:
                observations.append(self._observation(request, clip, None))
        observations.sort(
            key=lambda item: item.normalized_audio_interval.start_microseconds
        )
        evidence_hash = canonical_hash(
            {
                "request_id": request.request_id,
                "provider": self._identity.model_dump(mode="json"),
                "observations": [
                    item.model_dump(mode="json") for item in observations
                ],
            }
        )
        raw_hash = hashlib.sha256(stdout).hexdigest()
        if request.policy.retain_raw_evidence and evidence_root is not None:
            root = evidence_root.resolve()
            root.mkdir(parents=True, exist_ok=True)
            raw_path = root / "raw-provider-response.json"
            temporary = raw_path.with_suffix(".json.partial")
            temporary.write_bytes(stdout)
            os.replace(temporary, raw_path)
            raw_evidence = RawProviderEvidence(
                disposition=RawEvidenceDisposition.RETAINED,
                media_type="application/json",
                content_sha256=raw_hash,
                byte_size=len(stdout),
                relative_path=raw_path.relative_to(root).as_posix(),
                explanation="Unmodified JSON emitted by isolated Whisper worker.",
            )
        else:
            raw_evidence = RawProviderEvidence(
                disposition=RawEvidenceDisposition.HASH_ONLY,
                media_type="application/json",
                content_sha256=raw_hash,
                byte_size=len(stdout),
                explanation=(
                    "Raw Whisper JSON was hashed but not retained by policy "
                    "or because no evidence root was supplied."
                ),
            )
        return TranscriptionProviderResponse(
            response_id=typed_id(
                "txresponse", request.request_id, evidence_hash
            ),
            request_id=request.request_id,
            provider=self._identity,
            started_at=started,
            completed_at=datetime.now(timezone.utc),
            observations=tuple(observations),
            normalized_evidence_sha256=evidence_hash,
            raw_evidence=raw_evidence,
            invocations=(invocation,),
            complete=True,
        )
