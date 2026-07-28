# ADR 018: Append-only transcript corrections and successor views

Status: Accepted  
Date: 2026-07-26

## Context

Canonical machine transcript text remains fallible. Reviewers and bounded
automated processes need to correct it without rewriting provider observations,
the original machine assembly, or Phase 1 evidence. A correction must be
replayable and must fail when based on stale, conflicting, or unknown state.

The work order requires replacement, insertion, deletion, split, merge,
boundary, language, normalization, uncertainty, and earlier-candidate
restoration records. It also requires original, current, history, and difference
views, with human and automated corrections explicitly distinguished.

## Decision

Represent correction input as a strict `TranscriptCorrectionBatch` targeting
one known transcript version. Each draft includes exact prior segment state,
proposed state, correction type, affected source interval, actor, timestamp,
reason, and evidence or review references.

Applying a valid batch:

- validates the untouched base assembly and all separately persisted children;
- rejects unknown versions, stale prior values, repeated targets, prohibited
  actors, missing review evidence, invalid source mapping, overlapping results,
  and type-specific shape errors;
- assigns stable correction identities from batch content;
- creates immutable `TranscriptCorrection` records that name the resulting
  version;
- creates a corrected successor `TranscriptVersion` whose predecessor is the
  original machine version;
- preserves an exact original-machine view;
- constructs a current corrected overlay without mutating canonical machine
  segments;
- persists correction history and a typed difference report;
- distinguishes human actors from versioned automated processes; and
- validates and reuses the resulting revision cache only when every embedded
  and separately persisted artifact agrees.

Text-changing corrections conservatively withhold inherited word evidence for
the changed segment. Language-only, normalization-only, and uncertainty-only
corrections may retain word references because they do not claim changed
lexical timing. Boundary adjustments withhold inherited words until alignment
is explicitly re-established.

Correction batches currently create one successor from an original-machine
assembly. Additional successor chaining will use the same prior-state and
predecessor rules rather than editing an existing revision.

## Consequences

“Corrected” means a recorded review or process decision, not that the text is
infallible. The original provider candidate, canonical machine segment,
confidence measures, and low-confidence regions remain recoverable.

The original and current renderings, correction history, and difference report
are persisted contracts rather than CLI-only presentations. Rendering changes
do not trigger retranscription.

Corrections that change timing must preserve the Phase 1 source-to-normalized
mapping. Split and merge operations must cover their targets exactly, and final
corrected segment order may not overlap or regress.

## Alternatives considered

- Edit canonical segments in place. Rejected because it destroys the original
  model result and invalidates audit history.
- Store only a corrected text blob. Rejected because it loses target, timing,
  actor, reason, and version lineage.
- Retain word evidence after arbitrary text replacement. Rejected because the
  old words no longer substantiate the corrected lexical content.
- Permit corrections without exact prior values. Rejected because stale review
  decisions could silently overwrite newer state.
- Treat automated corrections as human corrections. Rejected because the
  provenance and accountability boundaries differ.
