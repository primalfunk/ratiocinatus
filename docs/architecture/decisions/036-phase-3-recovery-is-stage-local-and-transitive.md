# ADR 036: Phase 3 recovery is stage-local and transitively invalidated

Status: Accepted  
Date: 2026-07-27  
Phase: 3

## Context

Phase 3 has independently persisted provider responses, normalized speaker
observations, embeddings, clusters, reference evidence, identity decisions,
reviewed views, speaker transcripts, and participant subtitles. Treating that
chain as one cache would either reuse incompatible evidence or repeat costly
and privacy-sensitive upstream work after a downstream failure.

Recovery must preserve invalid evidence for diagnosis, resume interrupted
stages, and never silently trust a partial participant view.

## Decision

Phase 3 recovery uses eleven explicit stage boundaries:

- diarization provider response;
- normalized diarization observations;
- speaker embeddings;
- clustering;
- reference enrollments;
- reference comparisons;
- identity hypotheses;
- identity bindings;
- identity views;
- speaker transcript; and
- participant subtitles.

Every declared stage is validated before reuse. Missing stages resume from
their persisted boundary. Corrupt stages move to a stage-local `invalid/`
directory before rebuilding. A rebuilt stage invalidates only its transitive
dependents according to a versioned dependency graph.

Recovery tasks execute in topological order even if requested out of order.
Provider invocation is recorded per rebuilt stage. Valid provider evidence and
other valid upstream stages are reused without invocation.

Recovery reports seal their records, invalidation plans, interruption
boundaries, protected-upstream fingerprints, and negative proofs. Report paths
and artifact paths are confined below the declared recovery root.

## Consequences

- Participant-name changes rebuild views and presentation derivatives without
  acoustic reprocessing.
- Embedding-model changes invalidate embeddings, dependent clustering,
  enrollments, comparisons, and participant views while preserving Phase 1,
  Phase 2, and provider observations.
- Corrupt downstream exports cannot cause valid diarization providers to run
  again.
- Interrupted stages resume without duplicating committed evidence.
- Quarantined bytes remain available for diagnosis.
- The orchestration layer accepts each stage's authoritative validator and
  rebuild operation rather than weakening stage-specific integrity checks.
