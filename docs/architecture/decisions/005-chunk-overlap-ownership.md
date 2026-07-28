# ADR 005: Chunk overlap ownership

- Status: Accepted for Phase 1
- Date: 2026-07-26

## Context

Overlapping operational chunks expose the same corpus interval to more than one
provider invocation. A later aggregation phase needs one deterministic owner
for results in overlap regions, even though Phase 1 does not yet produce
transcripts or analytical results.

## Decision

Version 1 uses `earliest_chunk_owns_overlap`.

The earlier chunk owns its complete interval. Each later chunk's ownership
begins after its overlap with the previous chunk. Ownership intervals are
contiguous, non-overlapping, begin at corpus zero, and end at corpus duration.
Operational chunk intervals still retain their overlap; ownership affects only
future result reconciliation.

Chunk plans record both the operational interval and ownership interval. Phase
1 does not apply this policy to transcription or any other analytical output.

## Alternatives considered

- Latest chunk owns overlap: equally deterministic but discards the earlier
  invocation's already-established ownership.
- Split at overlap midpoint: balanced but introduces another boundary and
  rounding rule.
- Deduplicate later by content: depends on provider output and belongs to a
  later analytical phase.
- Allow duplicate ownership: prevents deterministic aggregation.

## Consequences

- Every normalized corpus point has exactly one ownership interval.
- Provider inputs retain the full configured context overlap.
- Later phases can reconcile results without inventing a policy.

## Reversibility

Ownership policy is a versioned chunk-policy field. A different policy creates
a different plan identity while allowing unaffected upstream artifacts to be
reused.

## Qualification evidence

Contract validation checks contiguous ownership, corpus-end coverage, ordinal
continuity, exact adjacent overlap, source/corpus duration agreement, and
terminal-short-chunk consistency.
