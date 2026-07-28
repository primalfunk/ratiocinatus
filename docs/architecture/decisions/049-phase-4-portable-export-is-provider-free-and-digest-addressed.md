# ADR 049: Phase 4 portable export is provider-free and digest-addressed

Status: Accepted  
Date: 2026-07-27  
Phase: 4

## Decision

A Phase 4 portable bundle contains the complete selected Phase 4 artifact chain,
its runtime schemas, and a sealed manifest. Entries use relative paths and
record byte size, media type, contract type, and SHA-256 digest. Prior-phase
references remain relative and external; optional analytical providers and
models are not redistributed or required for reload.

## Consequences

- Absolute paths, missing entries, digest changes, and incompatible contract
  types are refused.
- Reload can validate evidence without invoking a provider.
- Replay proves manifest stability for the same artifact set.
- Source-media export remains subject to workspace policy.

