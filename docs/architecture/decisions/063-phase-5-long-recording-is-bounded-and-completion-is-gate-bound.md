# ADR 063: Phase 5 long-recording is bounded and completion is gate-bound

## Status

Accepted.

## Context

Phase 5 must demonstrate operation beyond two hours without converting a
synthetic mechanics exercise into an accuracy claim. Phase completion also
requires a single auditable judgment over twenty-four heterogeneous gates,
while preserving the distinction among deterministic evidence, provider
proposals, selected machine analysis, human review, measured evaluation,
synthetic mechanics, and integrity validation.

## Decision

Long-recording qualification uses a virtual recording of 7,201 seconds divided
into 121 incremental chunks. Active context is capped at twelve utterances and
relation-target search at twenty utterances. The proof records cross-chunk
continuity, interruption/resume, cache replay, local recovery, unique act
ownership, provider-free export/reload, final integrity, and peak active-state
memory. It invokes no provider and makes no natural-discourse accuracy claim.

Phase 5 completion is represented by a sealed report containing:

- application, contract, and repository state;
- corpus, configuration, and Phase 4 lineage identifiers;
- act, span, relation, alternative, confidence, review, propagation,
  evaluation, recovery, long-recording, memory, regression, and schema
  measurements;
- evidence entries with explicit evidence classes;
- seven non-adjudication boundary statements;
- known limitations and unresolved concerns; and
- exactly twenty-four ordered exit gates.

A gate is complete only when every mapped qualification is present. The
regression gate additionally requires at least the previously qualified
repository test baseline. Missing evidence produces an in-progress report;
tampered evidence produces integrity refusal.

## Consequences

Phase 5 can close without overstating synthetic results. Every exit gate has an
explicit evidence trail, and later evidence revisions can produce successor
completion reports. The resulting discourse corpus is qualified as input to
later proposition and argument phases, but Phase 5 itself makes no truth,
adequacy, validity, intent, credibility, violation, or participant-merit
judgment.
