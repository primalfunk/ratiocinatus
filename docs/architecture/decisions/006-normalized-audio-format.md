# ADR 006: Normalized audio format and sample rate

- Status: Accepted for Phase 1
- Date: 2026-07-26

## Context

Speech-processing providers need one stable authoritative audio derivative.
That derivative must remain evidence-preserving, portable, compact enough for
multi-hour recordings, and directly traceable to the selected source stream.

## Decision

The version 1 normalized audio derivative is:

- FLAC;
- mono;
- 16,000 samples per second;
- signed 16-bit PCM before lossless FLAC coding;
- zero-based derivative-local time; and
- free of copied source metadata.

FLAC is lossless and materially reduces storage compared with uncompressed WAV
for long recordings. FFmpeg's libswresample performs the sample-rate conversion.

Mono sources are not downmixed. Sources with two or more channels use an
explicit equal-weight average whose coefficients sum exactly to one. This
prevents the downmix from adding gain. The complete filter expression is
recorded in the invocation. No denoising, silence removal, source separation,
voice enhancement, dynamic-range compression, automatic gain, tempo change,
pitch change, or subjective loudness processing is allowed.

The derivative records source stream and layout, downmix policy, resampler,
format, sample rate, sample count where available, invocation, tool identity,
duration, hash, integrity checks, and derivative-to-source interval mapping.

## Alternatives considered

- 16 kHz mono PCM WAV: simple and maximally interoperable, but substantially
  larger for multi-hour recordings.
- 48 kHz preservation: retains more bandwidth than typical speech providers
  require and increases storage and processing cost.
- Lossy Opus or AAC: compact but introduces irreversible coding changes.
- Layout-specific cinematic downmix: semantically conventional, but may add
  gain and makes evidence behavior depend on layout interpretation.

## Consequences

- Audio content is transformed only by decode, equal-weight downmix where
  needed, and resampling.
- The committed derivative is losslessly coded and independently decodable.
- Later providers can rely on one sample rate and channel count.
- Unusual source sample rates and layouts remain recorded in provenance.

## Reversibility

The policy and derivative format are versioned and included in cache identity.
A future policy can produce another derivative without replacing this one.

## Qualification evidence

Tests normalize mono and stereo WAV sources, including an unusual 11,025 Hz
source, and verify 16 kHz mono signed-16 output, duration agreement,
decodability, hashing, and non-overwrite behavior.
