# Dependency inventory

Ratiocinatus 0.4.0 has one Python runtime dependency: Pydantic `>=2.8,<3`
for strict runtime contracts and derived schemas. setuptools `>=68` is the
build backend. Pytest `>=8` and coverage.py `>=7` are development-only. Python
3.11 or newer is the platform prerequisite.

Phase 1 and the Phase 2 energy baseline require FFmpeg and FFprobe for decode,
normalization, inspection, timestamp access, and transient PCM analysis. They
are externally discovered or explicitly configured and are not bundled.
Semantic speech activity is optional through the `vad` extra, pinned to
`silero-vad==6.2.1`; that package requires PyTorch and TorchAudio. The installed
package supplies the verified model artifact locally, and this repository does
not redistribute it. Local transcription is optional through the
`transcription` extra, pinned to `openai-whisper==20250625`; the verified
`small` checkpoint is acquired separately and is not redistributed. Ordinary
base tests require no model, GPU, network, or commercial service. Canonical transcript assembly, corrections, subtitles, evaluation, and recovery
are implemented locally. Phase 3 now exposes an unconfigured diarization
provider and protected-reference embedding boundary without selecting a model;
later analytical provider families remain unconfigured or deterministic mocks.
Resolve an environment's transitive Python inventory with `python -m pip
freeze`; it is not authoritative project state because environments vary.