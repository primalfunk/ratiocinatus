# ADR 045: Phase 4 transcript views are loss-declared derivatives

Status: Accepted  
Date: 2026-07-27

## Decision

Speaker-attributed transcripts are deterministic presentation derivatives of
the sealed utterance corpus and its analysis, temporal-relation, turn-repair,
quotation, and embedded-source evidence.

Every bundle contains exactly six views: machine speaker cluster, reviewed
participant identity, unknown-preserving, correction-aware, overlap-expanded,
and compact reading. Every view retains utterance identifiers, source and
normalized intervals, attribution and review status, and evidence references.

The overlap-expanded view preserves temporal partial order with explicit
groups and lanes. Sequential views declare overlap linearization in sealed
presentation-loss records. Missing reviewed labels and corrected text also
produce explicit losses; they never trigger guessed values.

## Consequences

- No transcript view replaces or mutates the utterance corpus.
- Unknown and conflicting speakers remain visible.
- Interruption, continuation, overlap, quotation, source, repair, uncertainty,
  and review state remain inspectable as markers and evidence references.
- Consumers can select a convenient view while detecting its presentation
  limitations mechanically.
- Every bundle is deterministic, lineage-validated, tamper-evident, and
  cache-safe.
