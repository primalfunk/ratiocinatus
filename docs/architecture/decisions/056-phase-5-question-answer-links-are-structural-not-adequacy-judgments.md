# ADR 056: Phase 5 question-answer links are structural, not adequacy judgments

Status: Accepted  
Date: 2026-07-27  
Phase: 5

## Decision

Canonical question acts produce first-class question artifacts retaining their
exact source spans, structural question type, requested form, explicit
alternatives, surface presupposition markers, unresolved or evidenced
addressee state, domain, scope, confidence, and review status.

Canonical answer acts produce one answer-relation artifact each. Exact
normalized relation targets take precedence. Without one, a single preceding
question in the exact bounded-temporal context becomes a probable,
review-required target. Multiple preceding questions remain alternatives. No
supported target remains unresolved. A question appearing later cannot be
linked retrospectively without an explicit target.

Answer form, explicitness, polarity, qualification, premise rejection,
deferral, refusal, inability, multiple targets, co-answer acts, confidence, and
review remain explicit. Phase 5 does not produce responsiveness, adequacy,
completeness, or evasion scores.

## Consequences

- Temporal proximity is evidence for a candidate relation, not proof that an
  answer responds adequately.
- One question may have several co-answer acts, and contracts support one
  answer targeting several questions when explicitly grounded.
- Deferred, refused, inability, premise-rejecting, ambiguous, and unresolved
  answers remain distinct inspectable states.
- Surface presupposition markers do not establish loadedness, unfairness,
  misleadingness, or answerability.
- Question-answer runs replay from the sealed canonical discourse corpus and
  exact context bundle without provider reinvocation.
