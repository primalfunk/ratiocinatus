# ADR 046: Phase 4 context windows are budgeted source projections

Status: Accepted  
Date: 2026-07-27

## Decision

Context windows are deterministic projections of one sealed utterance corpus,
its temporal relations, quotation evidence, and canonical speaker-attributed
transcript bundle. They are not free-form prompts and do not replace source
evidence.

Every utterance receives nine window types: preceding, following, same-speaker
history, current-turn neighborhood, exchange, structurally known
question-response, interruption neighborhood, quotation neighborhood, and
bounded temporal context.

Selection is governed by a versioned policy with maximum utterance count,
token estimate, and source duration. Optional speaker balancing and explicit
preservation priorities affect deterministic candidate ordering. The target
utterance must fit the budget in full; otherwise construction fails rather
than silently clipping it.

## Consequences

- Every included utterance retains source intervals, canonical position,
  temporal group, overlap lane, simultaneous references, and inclusion reason.
- Unknown speakers are never conflated for same-speaker history.
- Missing question, interruption, quotation, or resolved-speaker structure is
  disclosed separately from budget truncation.
- Every budget omission records its reason and affected utterance identifiers.
- A truncated window states that the complete exchange was not considered.
- Cached windows are policy- and corpus-version-specific, lineage-validated,
  deterministic, and tamper-evident.
