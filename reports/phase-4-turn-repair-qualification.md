# Phase 4 bounded turn-repair qualification

- Status: passed
- Target application version: 0.6.0
- Evidence class: synthetic mechanics
- Turn-repair contract models: 8
- Runtime schemas: 269
- Focused Stage 5 tests: 6
- Full regression tests: 214

This slice qualifies source-addressed conflict detection and bounded proposals
across transcript words and segments, speaker boundaries and turns,
attribution spans, and utterance ownership.

Every proposal retains contrary evidence and all source intervals. Automated
word reassignment is prohibited. Manual acceptance creates a new sealed,
predecessor-linked successor record without rewriting Phase 2, Phase 3, or
the original Phase 4 utterance corpus.
