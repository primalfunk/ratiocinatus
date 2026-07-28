# ADR 055: Phase 5 consolidation preserves compatible and conflicting candidates

Status: Accepted  
Date: 2026-07-27  
Phase: 5

## Decision

Deterministic and provider observations are grouped only when they propose the
same act family and type for overlapping source text. The canonical candidate
retains every source observation, span, target proposal, contrary item,
confidence origin, and limitation. Corroboration adds a small declared ranking
bonus but does not turn either evidence source into authority.

Candidates above the selection threshold may be selected together when their
functions are compatible. Mutually exclusive candidates are compared only
within explicit, versioned exclusion groups and overlapping spans. A materially
stronger candidate may be selected while its alternative is retained as
rejected. Close exclusive alternatives remain unresolved and produce no
canonical act. Unknown and unclassified remain valid outcomes.

## Consequences

- Consolidation is evidence grouping and bounded selection, not majority
  voting.
- Multi-label utterances remain first-class.
- Provider-only candidates require review and provider output never selects
  itself by authority.
- Rejected, deferred, and unresolved candidates remain inspectable.
- Provider failure evidence remains upstream and is counted in the
  consolidation report.
- The complete run, canonical corpus, and report replay from sealed baseline,
  provider, context, and Phase 4 inputs.
