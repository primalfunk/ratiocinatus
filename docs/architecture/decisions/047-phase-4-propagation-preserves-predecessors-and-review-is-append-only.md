# ADR 047: Phase 4 propagation preserves predecessors and review is append-only

Status: Accepted  
Date: 2026-07-27

## Decision

Phase 4 correction propagation compares a fully validated predecessor artifact
chain with a fully rebuilt successor chain. Mapping prefers canonical
transcript-word ownership and uses bounded temporal correspondence only as a
fallback.

Each predecessor is classified as unchanged-equivalent, rebuilt one-to-one,
split, merged, removed, or unresolved. Added successors are recorded
separately. Detected changes distinguish text, timing, speaker attribution,
segmentation, display label, and source lineage, and produce an explicit
dependent-artifact invalidation set.

Unchanged predecessor evidence remains reusable. Changed predecessor evidence
also remains immutable and addressable; propagation never overwrites it.
Because utterance identifiers are corpus-scoped, a changed upstream corpus
cannot truthfully retain an identical successor identifier. The mapping record
preserves the predecessor and explains this boundary.

Manual decisions are appended to successor review ledgers. Every action keeps
its prior and proposed state, author, time, rationale, evidence, certainty,
predecessor action, and resulting review-view version. Machine proposals are
always preserved.

## Consequences

- Display-label-only changes rebuild views and windows without claiming that
  segmentation changed.
- Timing changes crossing boundaries require segmentation review.
- Stale views or context windows cannot satisfy propagation validation.
- All fifteen required manual action types are representable.
- Review lineage is acyclic and append-only.
- Review queues package source intervals, media extraction commands, local
  context, speaker evidence, proposed actions, and competing alternatives.
