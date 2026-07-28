# Phase 3 comparison-backed identity-hypothesis qualification

Status: **PASSED**  
Application version: 0.4.0  
Target Phase 3 application version: 0.5.0

This slice connects eligible reference-voice comparisons to bounded,
append-only participant-identity hypotheses without creating identity
bindings.

Only validated supports and weakly-supports classifications may be promoted.
Strong support creates a supported hypothesis; weak support remains proposed.
Inconclusive, weakly contradictory, contradictory, and invalid comparisons are
refused by the positive-promotion operation.

The comparison, clustering, diarization, enrollment, and identity-foundation
lineage is revalidated before promotion. The comparison target and proposed
identity must remain within the declared identity scope. Comparison and
reference identifiers, target provenance, supporting references, contrary
references, normalized score-scale strength, and calibration status remain
explicit.

Acoustic support stays separate from contextual, documentary, and manual
support. Its basis states that normalized strength is not an identity
probability. The operation creates an immutable identity-foundation successor
and never modifies clustering, diarization, enrollment, comparison, or prior
identity evidence.

The CLI adds `identity-propose-from-comparison`. Six focused integration tests
and all 153 repository tests passed. Runtime schema export remains 198 schemas
plus 20 controlled-fixture schemas because this slice reuses the existing
strict comparison and identity contracts.

No automatic binding, manual binding, definitive identity decision, reviewed
identity view, participant-labeled transcript, or participant-labeled subtitle
export was added.
