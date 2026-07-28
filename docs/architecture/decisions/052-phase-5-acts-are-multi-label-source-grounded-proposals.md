# ADR 052: Phase 5 acts are multi-label source-grounded proposals

Status: Accepted  
Date: 2026-07-27  
Phase: 5

## Decision

A Phase 5 discourse act is an immutable analytical proposal about the
conversational function of one or more exact spans in a declared Phase 4
utterance. Every selected act retains Phase 4 corpus lineage, text-view and
source addressing, observations, candidate selection, alternatives, contrary
evidence, multidimensional confidence, targets, and review state.

The vocabulary is closed and versioned. Multiple compatible acts may be
selected for one utterance or span. Mutually exclusive candidates remain
visible when unresolved. Every input utterance is either represented by one or
more selected acts or explicitly recorded as unclassified.

Provider output is evidence, never authority. It must pass normalization,
schema, source-address, lineage, and selection validation before contributing
to a canonical act.

## Consequences

- Whole-utterance single-label collapse is not the canonical representation.
- Exact evidence spans are required for selected acts.
- Unknown, ambiguous, truncated, phatic, non-lexical, and insufficient-context
  states are first-class outcomes.
- Assertion does not imply truth; answer does not imply adequacy; rebuttal does
  not imply success; procedure does not imply violation or blame.
- Phase 4 changes invalidate dependent Phase 5 evidence without rewriting
  Phase 4 or unaffected Phase 5 artifacts.

