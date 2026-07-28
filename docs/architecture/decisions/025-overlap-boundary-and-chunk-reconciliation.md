# ADR 025: Overlap, uncertain boundaries, and chunk reconciliation

Status: Accepted  
Date: 2026-07-26

## Decision

Preserve provider overlap proposals as explicit canonical `OverlapInterval`
evidence instead of flattening them into a dominant speaker turn. Associate
overlap with every temporally intersecting canonical observation, retain an
unknown speaker count when the provider cannot support one, and mark
attribution partial while speaker clusters are unavailable.

Represent each proposed turn edge as a separate `SpeakerChangeBoundary`.
Assign configured uncertainty, identify transcript segments and words that
contain the boundary, retain nearby competing proposals, mark overlap effects,
and require review when confidence is weak or unavailable, the boundary falls
inside transcript evidence, overlap affects it, or a competing proposal exists.
Do not round a speaker boundary to a transcript edge.

Derive transcript links by temporal intersection with the embedded canonical
Phase 2 transcript evidence. Provider-supplied transcript references are
validated as aligned hints but are not authoritative.

At Phase 1 chunk transitions, retain non-owner provider observations in the
raw response while reconciling each to an identical earliest-owner canonical
observation. Refuse non-owner evidence without a canonical counterpart and
refuse duplicated canonical ownership.

## Rationale

Overlap, turn changes, transcript edges, and processing chunks describe
different structures. Collapsing them produces false precision, duplicate
speakers at chunk transitions, and incorrect single-speaker transcript views.
Explicit uncertainty and deterministic reconciliation preserve what the
provider actually supports without allowing operational chunking to alter the
evidentiary result.

## Consequences

- Canonical runs contain only owner observations but raw responses retain
  non-owner duplicates.
- Turns referencing non-owner duplicates are deterministically remapped.
- Overlap remains partially or wholly unattributed until later clustering.
- Boundary review is visible and queryable.
- Transcript segment and word links remain stable across provider label edits.
- Invalid overlap mappings and missing chunk-owner counterparts refuse.
