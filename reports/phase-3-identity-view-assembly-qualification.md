# Phase 3 reviewed identity-view assembly qualification

Status: **PASSED**  
Application version: 0.4.0  
Target Phase 3 application version: 0.5.0

This slice adds deterministic, sealed assembly of all eight identity views
required by the Phase 3 work order: raw provider diarization, canonical machine
diarization, cluster consistency, unresolved speakers, identity hypotheses,
reference comparisons, manually reviewed identity assignments, and binding
history.

The assembly pins the exact provider response, diarization run, clustering run,
identity foundation, binding ledger, and optional comparison run. Its reviewed
view identifier is the resulting identity-view version recorded by the latest
manual binding.

Manual decisions are applied per canonical turn only when both target and
declared scope cover it. Machine and reviewed labels remain separate fields.
Reviewed labels use a mandatory `REVIEWED: ` prefix, including explicit
`REVIEWED: UNKNOWN` and `REVIEWED: CONFLICT` states.

Parallel incompatible decisions create blocking findings and prevent the
reviewed view from being trusted for participant rendering. Impossible
simultaneous assignment of one identity to independent overlapping turns is
also detected. Unresolved merge and split proposals, hypotheses, invalid
comparisons, and missing comparison evidence remain visible rather than being
silently resolved.

Persistence refuses incomplete or incompatible caches and reuses an exact
assembly. Validation independently recomputes reviewed state from the ledger.
The CLI adds `identity-view-assemble`, `identity-view-inspect`,
`identity-view-list`, `identity-view-reviewed`, and `identity-view-validate`.

Five focused tests and all 163 repository tests passed. Runtime schema export
contains 206 schemas plus 20 controlled-fixture schemas.

Phase 2 transcript evidence was not modified. Speaker-labeled transcript and
subtitle derivatives remain the next Phase 3 work.
