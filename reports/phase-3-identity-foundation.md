# Phase 3 scoped participant-identity foundation qualification

Status: **PASSED**  
Application version: 0.4.0  
Target Phase 3 application version: 0.5.0

This slice implements minimal participant-identity entities and bounded
identity hypotheses without adding voice matching or definitive binding.

Identity entities record a stable identifier, display and alternate labels,
identity type, information source, explicit artifact scope, status, and
provenance. They contain no biographical, political, psychological,
credibility, or general profiling fields and never modify their source
clusters.

Identity foundation runs are immutable, integrity-sealed successors. Each
successor retains all predecessor identities, hypotheses, and conflicts.
Unknown scope targets, predecessor rewrites, incomplete caches, and invalid
lineage are refused.

Hypotheses target known source-addressed artifacts and preserve acoustic,
contextual, documentary, and manual support as separate measures. Supporting
and contrary evidence remain explicit. Competing active proposals for one
artifact and scope produce an unresolved conflict instead of an automatic
selection.

The CLI creates identities, proposes hypotheses, validates and inspects
foundation runs, and independently lists identities, hypotheses, and
conflicts. Premature reference-voice hypotheses are refused until the later
comparison stage.

Three focused identity tests, twenty focused Phase 3 tests, and all 139
repository tests passed. Schema export produced 187 runtime schemas plus 20
controlled-fixture schemas.

No reference enrollment, voice comparison, automatic binding, manual reviewed
identity view, participant-labeled transcript, or participant-labeled subtitle
export was added.
