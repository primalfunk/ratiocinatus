# Phase 4 context-window qualification

- Status: passed
- Target application version: 0.6.0
- Evidence class: synthetic mechanics
- Context-window contract models: 6
- Runtime schemas: 287
- Focused Stage 8 tests: 6
- Full regression tests: 230

This slice qualifies nine deterministic context-window projections for every
utterance, bounded simultaneously by utterance count, token estimate, and
source duration.

Every member retains source addressing, canonical order, overlap group and
lane, simultaneous references, inclusion reasons, and evidence lineage.
Budget omissions identify their affected utterances, while unavailable
question, interruption, quotation, or speaker structure is disclosed
separately. Truncated windows explicitly state that they do not represent the
complete exchange.
