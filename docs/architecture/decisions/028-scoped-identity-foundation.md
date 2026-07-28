# ADR 028: Scoped participant identities and bounded hypotheses

Status: Accepted  
Date: 2026-07-26

## Decision

Represent participant identity as a separate, minimal attribution artifact.
Every identity requires a display label, type, information source, explicit
scope, status, and provenance. The contract contains no biographical,
political, psychological, credibility, or general profiling fields.

Store identities and hypotheses in integrity-sealed
`IdentityFoundationRun` successors. A successor may add evidence but must
preserve all identities, hypotheses, and conflicts from its declared
predecessor. Identity creation never modifies a diarization observation, turn,
cluster, transcript, or controlled evaluation.

Every hypothesis targets one known cluster, turn, or observation and proposes
one known identity within a validated scope. Acoustic, contextual,
documentary, and manual support remain four separate `ConfidenceMeasure`
records. Supporting evidence is mandatory and contrary evidence remains
visible.

When two active hypotheses propose different identities for the same artifact
and scope, create an unresolved conflict. Do not automatically rank, merge,
bind, or discard either proposal. Reference-voice comparison hypotheses are
refused until the separate enrollment and comparison stage exists.

## Rationale

Useful attribution work can begin from a controlled roster, introduction, or
review proposal without pretending those sources establish identity. Keeping
the entity, hypothesis, acoustic cluster, and eventual manual binding separate
allows later evidence to challenge an attribution without rewriting its
history.

Append-only successors make the creation sequence recoverable and prevent a
later hypothesis from silently editing earlier support or contrary evidence.

## Consequences

- Cluster identifiers and contents remain independent of identity labels.
- Unknown and locally distinct participants are valid identity entities.
- Identity scope cannot silently expand from a local artifact to a corpus.
- Different support types cannot be collapsed into one score.
- Competing hypotheses remain visible and unresolved.
- No automated hypothesis becomes a confirmed binding.
- Reference enrollment, voice comparison, and manual reviewed views remain
  later Phase 3 stages.
