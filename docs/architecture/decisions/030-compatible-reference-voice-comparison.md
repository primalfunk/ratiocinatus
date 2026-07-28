# ADR 030: Compatible reference-voice comparison is non-binding evidence

Status: Accepted  
Date: 2026-07-27  
Phase: 3

## Context

An enrolled reference voice can support or weaken a participant-identity
hypothesis, but a similarity score is not a probability of identity and does
not establish a real-world person. Scores are meaningful only within the model
space, model fingerprint, extraction method, score scale, threshold policy,
quality conditions, and calibration context that produced them.

Inactive, expired, rejected, revoked, replaced, incompatible, or unusable
reference evidence must not receive an interpreted result.

## Decision

Reference comparison is an immutable analytical observation bound to:

- one canonical speaker cluster or observation;
- one active reference enrollment;
- the clustering, diarization, identity-foundation, and enrollment lineage;
- exact target and reference model-space identifiers and fingerprints;
- protected target and reference representation references and digests;
- a named comparison provider and method;
- an explicit score scale and ordered threshold policy;
- calibration dataset, operating point, cohort, and estimated error rates when
  available;
- target and reference quality, channel compatibility, overlap, and duration;
- supporting and contrary evidence references;
- and an explicit uncertainty measure.

The threshold policy maps compatible scores to one of five interpreted
classes: supports, weakly supports, inconclusive, weakly contradicts, or
contradicts an identity hypothesis. Ineligible or incompatible evidence is
classified as comparison invalid.

When calibration is unavailable, the comparison and report must say that the
score is not a probability and has no established error rate. Scores from
different model spaces, fingerprints, methods, scales, threshold policies, or
calibration contexts must not be compared as if they share one meaning.

Automatic identity binding is prohibited by the threshold-policy contract.
Comparison artifacts do not create, confirm, reject, or revise a participant
binding.

## Consequences

- Compatible controlled scores can become explicit acoustic evidence.
- All six required result classes remain machine-readable.
- Revoked, replaced, expired, rejected, and incompatible references produce
  invalid comparisons rather than silent omission.
- Calibration limitations remain visible in reports.
- Protected representation values remain outside portable contracts.
- A later slice may connect comparison evidence to identity hypotheses, but
  must preserve the distinction between acoustic support and binding.
