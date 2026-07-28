# Phase 3 cache, resume, and recovery qualification

Date: 2026-07-27  
Phase: 3  
Target Phase 3 application version: 0.5.0  
Status: **PASSED**

## Qualified boundary

This slice adds stage-local orchestration over the independently validated
Phase 3 artifacts. Eleven explicit boundaries separate diarization provider
responses, normalized observations, embeddings, clustering, reference
evidence, identity evidence, reviewed views, speaker transcripts, and
participant subtitles.

Five strict runtime contracts record recovery policy, protected fingerprints,
dependency invalidation, stage actions, and the sealed qualification report.

## Recovery behavior

- Valid stages are validated and reused.
- Missing stages resume from their persisted boundary.
- Corrupt stages are moved into a stage-local `invalid/` directory before
  rebuilding.
- Rebuilt evidence invalidates only transitive downstream stages.
- Tasks execute in deterministic topological order.
- Rebuild paths are confined below the declared recovery root.
- Provider invocation is recorded and is avoided for valid upstream evidence.
- Failed rebuilds preserve quarantined evidence and raise a typed integrity
  error.

The dependency proof shows that a participant binding or name change preserves
provider observations, normalized observations, embeddings, and clustering.
An embedding-model change preserves provider and normalized evidence while
invalidating embedding-dependent clusters, enrollments, comparisons, identity
views, transcripts, and subtitles.

## Evidence

Six focused tests cover closed schemas, dependency planning, corruption,
selective rebuilding, upstream provider reuse, interruption resume, failed
rebuild preservation, sealed reporting, CLI inspection, corrupt report
refusal, and path confinement.

All 179 repository tests passed. Runtime schema export contains 220 schemas
plus 20 controlled-fixture schemas.

The existing Silero VAD and Torch deprecation warnings remain non-failing and
unrelated to this slice.

## Remaining boundary

No production diarization, clustering, or reference-comparison provider is
selected by this work. Controlled diarization evaluation and complete Phase 3
reporting remain separate slices.
