# ADR 004: Processing chunk duration and overlap

- Status: Accepted for Phase 1
- Date: 2026-07-26

## Context

Later providers must process recordings that may last several hours without
loading an entire source or derivative into memory. Chunks are operational
windows, not speech, scene, or discourse boundaries.

## Decision

The version 1 default chunk policy uses:

- a 10-minute target duration;
- a 5-second adjacent overlap;
- a 30-second nominal minimum;
- a 15-minute maximum; and
- zero-based normalized corpus-time boundaries.

The final chunk may be shorter than the nominal minimum and is marked
explicitly. No silence, speaker, scene, or content-aware cutting is permitted.
Chunk starts advance by target duration minus overlap. The first chunk begins at
zero and the final chunk reaches the corpus end.

Chunk-plan and chunk identities include the source identity, corpus duration,
complete versioned policy, ordinal, and exact interval. Changing any relevant
policy field creates a new plan identity.

## Alternatives considered

- Non-overlapping chunks: simpler, but hostile to providers needing context at
  operational boundaries.
- Content-aware boundaries: semantically attractive but violates the Phase 1
  boundary and makes planning dependent on later analysis.
- Materialize every chunk: wastes storage and duplicates evidence before a
  provider demonstrates that files are necessary.

## Consequences

- Default plans provide deterministic, bounded processing windows.
- Adjacent coverage normally has multiplicity two inside the five-second
  overlap.
- Chunks remain virtual until a provider requires materialization.
- Terminal short chunks require explicit handling rather than silent padding.

## Reversibility

All values are carried in a versioned policy and plan identity. A future policy
can change duration or overlap without invalidating source inspection,
selection, qualification, or normalization artifacts.

## Qualification evidence

A synthetic 20-minute timeline produces three chunks beginning at 0,
595,000,000, and 1,190,000,000 microseconds. The final chunk reaches exactly
1,200,000,000 microseconds, adjacent overlap is exactly 5,000,000 microseconds,
and the terminal short chunk is explicit.
