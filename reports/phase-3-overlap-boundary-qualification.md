# Phase 3 overlap and uncertain-boundary qualification

Status: **PASSED**  
Application version: 0.4.0  
Target Phase 3 application version: 0.5.0

This slice completes the initial Stage 2 temporal reconciliation behavior and
implements the Stage 3 overlap normalization kernel.

Diarization requests now embed canonical transcript segments and words when a
Phase 2 assembly is supplied. Canonical observation and turn mappings are
derived by temporal intersection. Boundaries retain configured uncertainty,
inside-segment and inside-word references, nearby competing proposals, overlap
effects, confidence, and review state without rounding to transcript edges.

Provider observations emitted from non-owning Phase 1 overlap windows remain
in the provider response and reconcile to one identical earliest-owner
canonical observation. Missing counterparts, duplicated owners, and invalid
ownership markers refuse.

Provider overlap proposals become integrity-sealed `OverlapInterval` records.
Their source mapping, corpus bounds, supporting observations, active-speaker
count claim, confidence, and partial attribution are preserved. Invalid
overlap mappings refuse.

The CLI can list turns, boundaries, and overlaps independently. Reports include
review-boundary count, overlap count, and overlap duration.

Twenty focused Phase 3 tests and all 139 repository tests passed. Schema export
produced 187 runtime schemas plus 20 controlled-fixture schemas.

No production diarization model, speaker cluster, reference-voice comparison,
participant identity, or embedding export was added.
