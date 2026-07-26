"""Provider-independent TTS boundary and deterministic non-speech test mock."""

from __future__ import annotations

import hashlib
import io
import math
import struct
import wave
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping


class TTSProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class TTSDescriptor:
    provider_id: str
    version: str
    voices: tuple[str, ...]
    languages: tuple[str, ...]
    deterministic: bool
    mock: bool
    available: bool


@dataclass(frozen=True)
class TTSRequest:
    line_id: str
    text: str
    voice_id: str
    language: str = "en-us"
    speed: float = 1.0


@dataclass(frozen=True)
class TTSResult:
    line_id: str
    wav_bytes: bytes
    sample_rate_hz: int
    sample_count: int
    synthetic_notice: str


class TTSProvider(ABC):
    @property
    @abstractmethod
    def descriptor(self) -> TTSDescriptor: ...

    @abstractmethod
    def synthesize(self, request: TTSRequest) -> TTSResult: ...


class DeterministicMockTTS(TTSProvider):
    """Generate symbolic tones for orchestration tests, never intelligible speech."""

    def __init__(self, *, fail_line: str | None = None):
        self.fail_line = fail_line

    @property
    def descriptor(self) -> TTSDescriptor:
        return TTSDescriptor(
            provider_id="mock.symbolic-tts", version="0.1.0",
            voices=("mock_mod", "mock_a", "mock_b"), languages=("en-us",),
            deterministic=True, mock=True, available=True,
        )

    def synthesize(self, request: TTSRequest) -> TTSResult:
        if request.line_id == self.fail_line:
            raise TTSProviderError(f"intentional mock failure for {request.line_id}")
        if request.voice_id not in self.descriptor.voices:
            raise TTSProviderError(f"unknown mock voice: {request.voice_id}")
        rate = 8_000
        digest = hashlib.sha256(
            f"{request.line_id}\0{request.text}\0{request.voice_id}".encode()
        ).digest()
        frequency = 220 + digest[0]
        count = rate // 5 + digest[1] * 4
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(rate)
            frames = bytearray()
            for index in range(count):
                envelope = min(1.0, index / 80, (count - index) / 80)
                value = int(7_000 * envelope * math.sin(2 * math.pi * frequency * index / rate))
                frames.extend(struct.pack("<h", value))
            output.writeframes(bytes(frames))
        return TTSResult(
            line_id=request.line_id, wav_bytes=buffer.getvalue(),
            sample_rate_hz=rate, sample_count=count,
            synthetic_notice="SYMBOLIC NON-SPEECH MOCK; NOT TRANSCRIPTION EVIDENCE",
        )


class KokoroOnnxTTS(TTSProvider):
    """Optional local stock-voice provider, imported lazily for offline tests."""

    def __init__(self, model_path: Path, voices_path: Path):
        from kokoro_onnx import Kokoro
        self.model_path = model_path
        self.voices_path = voices_path
        self._engine = Kokoro(str(model_path), str(voices_path))

    @property
    def descriptor(self) -> TTSDescriptor:
        return TTSDescriptor(
            provider_id="kokoro-onnx", version="0.4.9",
            voices=tuple(self._engine.get_voices()), languages=("en-us",),
            deterministic=False, mock=False,
            available=self.model_path.is_file() and self.voices_path.is_file(),
        )

    def synthesize(self, request: TTSRequest) -> TTSResult:
        if request.voice_id not in self.descriptor.voices:
            raise TTSProviderError(f"unknown Kokoro voice: {request.voice_id}")
        import numpy as np
        import soundfile as sf
        samples, rate = self._engine.create(
            request.text, voice=request.voice_id, speed=request.speed,
            lang=request.language,
        )
        samples = np.nan_to_num(samples.astype(np.float32))
        peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
        if peak > 0.98:
            samples *= 0.98 / peak
        buffer = io.BytesIO()
        sf.write(buffer, samples, rate, format="WAV", subtype="PCM_16")
        return TTSResult(
            line_id=request.line_id, wav_bytes=buffer.getvalue(),
            sample_rate_hz=rate, sample_count=len(samples),
            synthetic_notice="KOKORO STOCK SYNTHETIC VOICE; NOT A REAL PERSON",
        )

def orchestrate_lines(
    provider: TTSProvider, requests: Iterable[TTSRequest],
    destination: Path, *, resume: bool = True,
) -> tuple[Path, ...]:
    """Synthesize each line independently; completed lines survive later failure."""
    destination.mkdir(parents=True, exist_ok=True)
    outputs = []
    for request in requests:
        target = destination / f"{request.line_id}.wav"
        if resume and target.is_file():
            outputs.append(target)
            continue
        result = provider.synthesize(request)
        temporary = destination / f".{request.line_id}.tmp"
        temporary.write_bytes(result.wav_bytes)
        temporary.replace(target)
        outputs.append(target)
    return tuple(outputs)

