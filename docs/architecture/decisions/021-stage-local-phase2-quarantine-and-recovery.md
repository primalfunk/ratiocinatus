# ADR 021: Stage-local Phase 2 quarantine and recovery

Status: Accepted  
Date: 2026-07-26

## Context

Phase 2 artifacts form a dependency chain from speech activity through
transcription, assembly, correction, subtitles, and evaluation. Existing stage
operations validate caches before reuse and refuse corrupt entries, but refusal
alone does not restore operation. Deleting a broad output tree would also
discard valid expensive evidence and obscure the original failure.

An interruption can leave either no committed artifact at the next stage or
valid primary evidence with incomplete report metadata. These cases should not
be treated as equivalent to corrupt provider evidence.

## Decision

Use stage-local recovery with a versioned `Phase2RecoveryPolicy`:

- validate every artifact before reuse;
- when a stage artifact is corrupt, move that exact artifact directory into
  its sibling `invalid/` directory before rebuilding;
- identify quarantined copies from a tree hash and never overwrite an existing
  quarantine;
- rebuild only from validated immediate parents;
- keep Phase 1 source, normalized audio, transcription responses, and retained
  raw provider evidence outside downstream invalidation scope;
- treat an absent next-stage artifact as a resumable boundary rather than
  corruption;
- reconstruct a missing or corrupt transcription report from its validated
  request, normalized response, and retained raw evidence without invoking the
  provider; and
- record action, detected failure, upstream identities, quarantine location,
  provider invocation, and post-recovery validation in a sealed report.

If primary transcription response evidence or retained raw evidence fails
validation, metadata repair refuses. Re-inference requires the normal provider
operation and must not be disguised as report repair.

The CLI exposes transcription-report repair and recovery-report
inspection/validation. The generic recovery controller is used by qualification
and later orchestration for deterministic downstream stages.

## Consequences

Invalid artifacts remain available for diagnosis. A successful recovery does
not erase evidence of the failure.

Changing or corrupting one deterministic downstream stage does not force
speech detection or transcription to run again. The recovery report proves
this with protected before/after fingerprints and an explicit
`provider_invoked` field.

Recovery is intentionally conservative. It does not attempt to patch malformed
canonical JSON, infer missing transcript content, or silently accept a partial
cache.

## Alternatives considered

- Delete the entire Phase 2 output and restart. Rejected because it discards
  valid expensive evidence and violates selective invalidation.
- Repair corrupt JSON in place. Rejected because it destroys the failure
  evidence and may invent domain content.
- Re-run transcription whenever a report is missing. Rejected because a report
  is deterministically reconstructible from a valid retained response.
- Leave corrupt entries in the active cache. Rejected because repeated runs
  cannot distinguish them from trusted output.
- Quarantine upstream and downstream together. Rejected because valid parent
  evidence should remain stable and reusable.
