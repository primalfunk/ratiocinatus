# ADR 034: Speaker labels are transcript presentation spans

Status: Accepted  
Date: 2026-07-27  
Phase: 3

## Context

Canonical speaker turns and transcript segments do not have a one-to-one
relationship. One segment may cross several turns, one turn may cover several
segments, corrected transcript segments may have new identifiers, and parts of
a transcript can remain unattributed. Inserting a single speaker field into
Phase 2 transcript evidence would lose those relationships and rewrite an
authoritative upstream artifact.

## Decision

Speaker-labeled transcripts are immutable Phase 3 presentation views over a
declared Phase 2 transcript view and a declared reviewed identity-view version.

The source transcript view is explicitly either `original_machine` or
`current_corrected`. Corrected rendering requires and preserves the revision,
corrected version, base assembly, and correction-history lineage.

Each source transcript segment is retained once with its text unchanged.
Temporal turn intersections divide only the segment's attribution metadata
into contiguous spans. Every span preserves:

- source and normalized time;
- canonical speaker-turn identifiers;
- transcript segment and retained word references;
- machine and reviewed labels;
- participant identities and identity-view entries;
- attribution kind;
- overlap disclosure; and
- findings.

Attribution kinds distinguish reviewed identity, machine cluster, unknown,
unattributed, multiple candidates, and conflict. Multiple simultaneous turns
are disclosed as overlap and are not serialized as a false sequence.

A conflicted reviewed identity view produces a blocked speaker transcript.
Validation reconstructs every attribution span from the pinned transcript,
diarization, and identity view; a re-sealed edited rendering is invalid.

## Consequences

- Phase 2 transcript text and corrections remain immutable.
- Corrected and machine transcript attribution cannot be confused.
- Many-to-many turn/segment relationships remain inspectable.
- Unknown, unattributed, multiple-candidate, and overlap states remain visible.
- Participant-labeled subtitles can use this view as their declared source.
