# Phase 4 deterministic initial utterance segmentation

Status: **PASSED**

- Phase: 4
- Target application version: 0.6.0
- Focused Phase 4 tests: 9 passed
- Segmentation integration tests: 4 passed
- Full regression: 199 passed
- Runtime schemas: 248

## Qualified mechanics

- deterministic alignment of Phase 2 canonical words with Phase 3 attribution
  spans;
- explicit Phase 2 segment/word and Phase 3 turn/observation lineage;
- stable source and normalized-time interval sets;
- at most one canonical utterance owner per transcript word;
- maximum-intersection ownership for words crossing speaker boundaries;
- explicit review flags for equal-support boundary ties;
- policy-bounded merging across transcript segments;
- preservation of reviewed, machine, conflicting, and unknown attribution;
- stable corpus identity, persistence, reload, and warm-cache replay;
- corrupt-cache and incompatible-lineage refusal; and
- structured CLI build, list, inspect, and validation operations.

## Boundary

This qualification establishes deterministic construction mechanics, not
natural-speech segmentation accuracy. Initial completeness is deliberately
conservative. Interruption, continuation, repair, self-repair, disfluency, and
quotation relations remain later stages.

The slice does not introduce claim extraction, argument analysis, factual
adjudication, credibility scoring, intent inference, or participant judgment.
