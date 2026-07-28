# ADR 031: Positive comparisons may support bounded identity hypotheses

Status: Accepted  
Date: 2026-07-27  
Phase: 3  
Supersedes: ADR 028's temporary deferral of reference-comparison hypotheses

## Context

The identity foundation already separates acoustic, contextual, documentary,
and manual support. Compatible reference-voice comparison now produces
validated, immutable evidence, but comparison artifacts remain deliberately
separate from participant-identity hypotheses and bindings.

An integration rule is needed that cannot turn an arbitrary score, invalid
comparison, contradiction, or inconclusive result into positive identity
support.

## Decision

Only a validated `supports_hypothesis` or `weakly_supports_hypothesis`
comparison may create a reference-comparison-sourced identity hypothesis.

Integration requires:

- exact comparison, clustering, diarization, enrollment, and identity-
  foundation lineage;
- an active eligible reference and compatible model space;
- a comparison target within the identity's declared scope;
- the comparison's proposed identity to exist in that foundation;
- the comparison identifier and reference identifier in supporting evidence;
- preservation of target provenance and contrary evidence references;
- acoustic support stored separately from contextual, documentary, and manual
  support;
- and an append-only identity-foundation successor.

Acoustic support is the score normalized only within the comparison's declared
score scale. Its basis states that it is support strength, not a probability
of identity. Calibration is retained only when the comparison supplies a
calibrated dataset and operating point.

Strong support creates a `supported` hypothesis. Weak support creates a
`proposed` hypothesis. Inconclusive, weakly contradictory, contradictory, and
invalid comparisons are refused by this positive-promotion operation rather
than mislabeled as supporting evidence.

No integration action creates, confirms, rejects, or revises an identity
binding.

## Consequences

- Positive acoustic evidence can enter the append-only identity foundation.
- Weak support cannot silently become confirmed attribution.
- Nonpositive comparison evidence remains available for later contrary-
  evidence and review workflows.
- Other support dimensions remain explicitly unavailable unless independently
  supplied.
- Competing scoped hypotheses still create unresolved conflicts.
- Manual identity binding and reviewed identity views remain later work.
