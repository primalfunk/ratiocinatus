# ADR 050: Phase 4 recovery is boundary-local and protected-source-preserving

Status: Accepted  
Date: 2026-07-27  
Phase: 4

## Decision

Phase 4 persists and validates ten processing boundaries. Valid artifacts are
reused, missing artifacts resume from their direct dependency boundary, and
corrupt derived artifacts are quarantined before rebuilding. An upstream
change invalidates only its transitive Phase 4 dependants.

Recovery reports contain the exact twenty-two negative-proof inventory and
before/after fingerprints for protected source and prior-phase evidence.

## Consequences

- Incomplete proof or boundary inventories are refused.
- Quarantine retains corrupt evidence for inspection.
- Optional analyzer failure cannot invalidate the deterministic corpus.
- Recovery never repairs by mutating source, transcript, or speaker evidence.

