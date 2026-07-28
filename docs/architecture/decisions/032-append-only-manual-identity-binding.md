# ADR 032: Manual identity decisions form an append-only attributable ledger

Status: Accepted  
Date: 2026-07-27  
Phase: 3

## Context

The identity foundation can preserve bounded hypotheses and comparison-backed
acoustic support, but neither is an identity decision. Reviewers need to bind,
reject, defer, revise, restore, merge placeholders, and split an incorrectly
unified identity without changing diarization or erasing earlier judgment.

A mutable current-label table would conceal disagreement and make later
correction indistinguishable from rewriting history.

## Decision

Manual identity decisions are stored in sealed, content-addressed successor
runs. Every successor embeds all predecessor decisions byte-for-byte and links
to its immediate predecessor run.

Every decision records its target, identity or explicit unknown outcome,
scope, action, predecessor decision where applicable, author, timestamp,
rationale, supporting evidence, acknowledged contrary evidence, reviewer
certainty, and resulting identity-view version identifier.

The supported actions are:

- bind;
- reject a proposed identity;
- mark unknown;
- revise an active prior decision, including narrowing its scope;
- restore an earlier decision through an explicit successor;
- merge existing unresolved placeholders into an existing survivor identity;
  and
- split an existing identity into at least two existing identity entities.

Merge and split decisions do not manufacture participant entities. Every
referenced identity must already exist in the pinned identity foundation.

Active state is a projection: a decision is active when no later decision
names it as predecessor. Independent active decisions for the same target and
scope remain parallel branches. If their outcomes differ, the report exposes
an unresolved conflict; it never silently chooses a winner.

Manual output is stored separately from clustering and diarization. The policy
requires manual labels to remain visibly distinct and prohibits modification
of source diarization evidence.

## Consequences

- Reviewer decisions are attributable and reversible without becoming
  erasable.
- Unknown and rejection are first-class outcomes.
- Conflicts remain visible until an explicit later decision addresses them.
- Binding histories can be inspected independently of a materialized current
  view.
- Reviewed identity-view assembly and participant-labeled presentation remain
  later work.
