# ADR 014: Energy activity baseline and inherited overlap ownership

Status: Accepted  
Date: 2026-07-26

## Context

Phase 2 needs an executable speech-activity pipeline before a semantic local
VAD is selected and licensed. The pipeline must prove Phase 1 audio access,
bounded chunk processing, source mapping, overlap reconciliation, persistence,
and reuse without presenting a weak detector as stronger evidence than it is.

## Decision

The first executable provider is a deterministic local PCM energy-activity
baseline. FFmpeg decodes one Phase 1 chunk at a time to transient 16 kHz mono
signed-16 PCM. Fixed frames receive an uncalibrated normalized RMS score and
are classified by the recorded speech/non-speech thresholds.

The provider calls high-energy regions `probable_speech` only as an explicitly
derived activity hypothesis. Every such interval records that energy cannot
distinguish speech from music, noise, or non-lexical vocalization. The provider
capability report repeats this limitation, and qualification includes a
speech-free tone/noise fixture that demonstrates the false positive.

PCM is discarded after each chunk. The retained evidence is the canonical hash
of normalized observations plus complete invocation records. No enhancement or
source repair occurs.

Phase 1 `earliest_chunk_owns_overlap` intervals remain authoritative. Frames
are clipped to their chunk ownership interval before canonical grouping.
Completed activity runs require contiguous coverage, valid source mapping, and
no output outside ownership.

## Alternatives

- Call energy activity a semantic VAD. Rejected because that would overstate
  the evidence.
- Delay all Stage 2 work until a model dependency is selected. Rejected because
  corpus mapping, chunk ownership, persistence, and recovery can be qualified
  independently.
- Analyze the entire derivative in one process. Rejected because it would not
  exercise the Phase 1 long-recording boundary.
- Retain decoded PCM. Rejected because normalized Phase 1 audio is already the
  evidence-bearing derivative and PCM would duplicate it without adding proof.

## Consequences

The pipeline is operational and honest but not sufficient for the final Phase
2 speech-activity gate. A semantic local VAD must replace or supplement it, and
evaluation must quantify speech precision/recall. Baseline outputs remain
useful for regression and provider-failure comparison.

## Reversibility and qualification

The provider and configuration are included in request identities, so another
provider creates independent evidence without invalidating Phase 1. Tests cover
silence/activity separation, stable reuse, CLI operation, and overlapping
chunks. Checked-in qualification covers a deterministic speech-free
silence/tone/noise fixture and the canonical Riverton clean source.
