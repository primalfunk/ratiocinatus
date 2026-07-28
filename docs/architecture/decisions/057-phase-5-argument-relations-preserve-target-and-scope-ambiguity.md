# ADR 057: Phase 5 argument relations preserve target and scope ambiguity

Status: Accepted  
Date: 2026-07-28  
Phase: 5

## Decision

Objection and rebuttal acts produce a common bounded relation record with a
typed challenge dimension or rebuttal method, exact supporting spans, target
acts and utterances, challenged spans, qualifications, alternatives, temporal
and context basis, confidence, review state, and unresolved issues.

Explicit normalized targets take precedence. Otherwise, the canonical acts in
the nearest prior utterance of the exact bounded-temporal window supply
candidate targets. One candidate is probable and review-required; several
remain alternatives; none remains unresolved. An explicitly unresolved
rebuttal type cannot be promoted by temporal proximity.

Concessions and qualifications remain separate modifier structures.
Concessions retain exact conceded spans, restrictions visible through
same-utterance qualifications, target alternatives, conditions, and
exceptions. Qualifications prefer other canonical acts in the same utterance;
multiple compatible acts preserve ambiguous scope.

## Consequences

- Objections to content, evidence, definition, procedure, premise, relevance,
  and generalized targets remain distinguishable.
- Rebuttal method never implies rebuttal success.
- Partial concession may coexist with retained disagreement and several
  qualification dimensions.
- Target and scope ambiguity remain inspectable rather than being collapsed.
- Temporal proximity is a reviewable candidate mechanism, not semantic proof.
- No factual adjudication or intent inference is introduced.
