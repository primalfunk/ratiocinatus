# ADR 059: Phase 5 procedural state is descriptive and event-sourced

Status: Accepted  
Date: 2026-07-28  
Phase: 5

## Decision

Canonical procedural acts and procedural questions produce an ordered event
log using source-media time and stable act identity. Every event retains its
source act, utterance, exact source intervals and evidence spans, observed
Phase 4 attribution, structural target state, descriptive effects, confidence,
and review status.

Every event produces one immutable procedural-state snapshot. State may record
an observed speaker, separately evidenced recognized speaker, pending question,
active response interval, moderator instruction, time warning and expiration,
clarification request, topic transition, extension state, and unresolved
events.

Observed acoustic speaker and procedurally recognized speaker are different
concepts. Pronouns such as “you” do not identify a floor recipient. A floor
grant may open an active response interval while its participant target remains
unresolved. Only explicit turn yield or time-expiration events close that
interval automatically in this stage.

## Consequences

- Every procedural state change is traceable to an act and source interval.
- Missing targets remain unresolved instead of being inferred from intent.
- Timing and moderator speech remain descriptive observations.
- Contracts constrain violation, fault, blame, and sanction assignments to
  false or zero.
- The state can be replayed exactly from the canonical discourse and Phase 4
  utterance corpora.
