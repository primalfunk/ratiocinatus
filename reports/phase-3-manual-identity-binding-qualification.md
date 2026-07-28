# Phase 3 manual identity-binding qualification

Status: **PASSED**  
Application version: 0.4.0  
Target Phase 3 application version: 0.5.0

This slice adds a sealed, content-addressed, append-only ledger for attributable
manual participant-identity decisions. It supports scoped bind, rejection,
unknown, revision, restoration, placeholder merge, and identity split actions.

Each decision preserves author identity and display name, timestamp, rationale,
supporting evidence, acknowledged contrary evidence, reviewer certainty,
predecessor decision, and resulting identity-view version identifier. Revision
and restoration can only name an earlier active decision for the same target.
Prior decisions remain unchanged in every successor run.

Active decisions are derived from predecessor links. Independent branches for
the same target and scope are retained, and incompatible active outcomes
produce an unresolved conflict in the derived report. No branch is silently
selected or used to rewrite the ledger.

Merge and split actions require participant entities already present in the
pinned identity foundation. Placeholder merge accepts unresolved placeholders
only, and split requires at least two resulting entities. Neither operation
creates identities or edits foundation evidence.

Persistence is separate from diarization and clustering, refuses partial or
incompatible caches, and reuses an exact cached run. The CLI adds
`identity-bind`, `identity-binding-inspect`, `identity-binding-list`,
`identity-binding-history`, and `identity-binding-validate`.

Five focused tests and all 158 repository tests passed. Runtime schema export
contains 201 schemas plus 20 controlled-fixture schemas.

Reviewed identity-view materialization, participant-labeled transcripts, and
participant-labeled subtitle exports were not added.
