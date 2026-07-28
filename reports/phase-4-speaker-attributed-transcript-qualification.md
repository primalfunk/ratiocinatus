# Phase 4 speaker-attributed transcript qualification

- Status: passed
- Target application version: 0.6.0
- Evidence class: synthetic mechanics
- Utterance-view contract models: 6
- Runtime schemas: 281
- Focused Stage 7 tests: 5
- Full regression tests: 224

This slice qualifies six deterministic speaker-attributed transcript views:
machine cluster, reviewed identity, unknown-preserving, correction-aware,
overlap-expanded, and compact reading.

All views preserve utterance identifiers, source intervals, attribution and
review state, and evidence references. The overlap-expanded view retains
temporal groups and lanes; sequential views disclose overlap linearization.
Unavailable labels and corrected surfaces remain visible as sealed
presentation losses, and no view replaces upstream evidence.
