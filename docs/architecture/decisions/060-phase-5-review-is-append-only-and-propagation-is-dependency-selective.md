# ADR 060: Phase 5 review is append-only and propagation is dependency-selective

## Status

Accepted.

## Context

Phase 5 machine proposals must remain inspectable after review, while changes to
the Phase 4 utterance corpus must invalidate only dependent analytical evidence.
A broad rebuild would erase useful provenance and unnecessarily change stable
discourse-act identifiers. Directly editing the canonical discourse corpus would
likewise obscure the distinction between machine evidence and human judgment.

## Decision

Manual discourse review is represented by immutable actions in versioned,
append-only ledgers. Every action records its target artifacts, prior and proposed
states, author, timestamp, rationale, evidence, certainty, resulting review
status, and resulting discourse-view version. Review never modifies the Phase 4
utterance corpus.

Review queues are derived artifacts. Queue items retain source interval
references, displayed utterance text, speaker attribution, local context,
proposed acts, evidence spans, alternatives, confidence, and supported actions.

Phase 4 correction propagation produces a sealed impact plan:

- displayed-text and boundary changes invalidate dependent evidence spans,
  observations, candidate sets, and selected acts;
- quotation changes invalidate quotation-dependent classification evidence;
- interruption or continuation changes rebuild affected relation targets;
- substantive speaker changes invalidate classification only when
  identity-specific context was explicitly declared as a dependency;
- display-label-only changes preserve classification and act identifiers;
- unaffected act identifiers are recorded as preserved;
- procedural state and review queues are scheduled for rebuilding when Phase 4
  changes are detected.

Owning construction stages create successor analytical artifacts. The
propagation stage records what must be rebuilt; it does not rewrite its inputs.

## Consequences

Review attribution and machine proposals remain auditable. Correction work is
bounded by explicit dependencies, provider evidence can be reused when still
valid, and stable identifiers do not churn after presentation-only changes.
Callers that use speaker identity during classification must declare that
dependency; undeclared identity assumptions cannot trigger invalidation.
