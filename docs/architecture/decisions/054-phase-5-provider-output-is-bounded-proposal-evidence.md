# ADR 054: Phase 5 provider output is bounded proposal evidence

Status: Accepted  
Date: 2026-07-27  
Phase: 5

## Decision

A discourse provider receives one target utterance and the exact members of one
validated, bounded-temporal Phase 4 context window. The request records the
Phase 4 corpus digest, context bundle and window identities, displayed text,
text-view identities, source intervals, truncation state, budgets, provider and
model fingerprints, deterministic seed where supported, and configuration
digest.

Provider output is normalized into typed proposals before it can become a
Phase 5 observation. Evidence offsets must reproduce the target display text.
Identified utterance targets must exist inside the supplied context. Candidate
budgets, family/type compatibility, confidence origin, raw-output digest, and
provider identity are validated.

Provider observations remain non-authoritative. Canonical selection occurs in
a later consolidation stage.

## Consequences

- A provider cannot silently expand its target-search scope.
- Fabricated targets and spans are typed validation failures.
- Timeouts may retry only within the declared bound and cannot duplicate
  observations.
- Unavailable providers, unavailable models, malformed output, and validation
  failures preserve failure evidence without forcing a classification.
- Provider-native confidence is not cross-provider comparable unless separately
  calibrated.
- Valid normalized observations can be persisted and validated without
  reinvoking the provider.

