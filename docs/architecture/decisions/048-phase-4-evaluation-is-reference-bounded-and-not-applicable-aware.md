# ADR 048: Phase 4 evaluation is reference-bounded and not-applicable aware

Status: Accepted  
Date: 2026-07-27  
Phase: 4

## Decision

Phase 4 controlled evaluation uses source-addressed utterance and relation
references. Its fixed twenty-metric inventory covers boundary, segmentation,
attribution, unknown preservation, interruption, continuation, completeness,
overlap, repair, quotation, propagation, stability, and context behavior.

Boundary matching uses a declared temporal collar and deterministic one-to-one
matching. Segmentation comparison uses canonical transcript-word ownership.
A metric without applicable reference examples is explicitly not applicable;
it is never assigned zero or perfect performance.

## Consequences

- Every score retains numerator, denominator, reference, and stratum lineage.
- Synthetic mechanics and controlled measurements remain distinct.
- Missing applicability cannot silently improve aggregate results.
- Controlled results do not establish general natural-speech accuracy.

