# ADR 024: Deterministic diarization evidence kernel

Status: Accepted  
Date: 2026-07-26

## Decision

Key every diarization request to the validated Phase 1 corpus, selected audio
stream, normalized-audio hash, source mapping, chunk plan, exact canonical
Phase 2 speech intervals, optional transcript assembly/version, provider
identity, and diarization policy. Exclude request wall-clock time from the
identity.

Persist provider response evidence separately from a canonical diarization
run. Seal normalized provider evidence, each canonical speaker observation,
each provisional speaker turn, and the complete run. Treat a partially present
cache as an integrity failure rather than resuming from ambiguous state.

Require every canonical observation to be contained by its referenced speech
evidence and Phase 1 chunk ownership interval, with exact source,
normalized-corpus, and chunk-local mappings. Provider labels remain
non-authoritative acoustic annotations and are not promoted into participant
identity or forced clusters.

## Rationale

Phase 3 must be reproducible from immutable upstream evidence without silently
depending on timestamps, filesystem state, or provider-local identity labels.
Keeping raw provider output separate from normalized canonical evidence makes
provider claims inspectable while allowing the kernel to enforce common
lineage and addressing rules.

## Consequences

- Identical evidence and configuration safely reuse an existing complete run.
- Changed policy, provider, speech selection, transcript version, or upstream
  lineage produces a different request identity.
- Incomplete, substituted, or mapping-incompatible evidence refuses.
- Phase 1 media and Phase 2 evidence are read-only inputs.
- Initial runs may contain unknown or unassigned turns and no clusters.
- A production provider still requires a separate selection and qualification
  decision.
