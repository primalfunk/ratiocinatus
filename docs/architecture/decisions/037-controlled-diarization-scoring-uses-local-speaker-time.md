# ADR 037: Controlled diarization scoring uses local-speaker time

Status: Accepted  
Date: 2026-07-27  
Phase: 3

## Context

Diarization quality cannot be inferred from cluster counts or provider
confidence. It requires independently prepared temporal references, an
explicit speaker mapping, declared boundary and overlap policies, and separate
accounting for missed speech, false alarm, and speaker confusion.

Provider speaker labels are local acoustic labels. Treating them as participant
identities during evaluation would cross the Phase 3 evidence boundary.

## Decision

Controlled temporal evaluation compares the validated provider response with
an independently sealed reference while using the canonical diarization run
for normalized boundaries and overlap intervals.

The scorer:

- maps system labels to controlled local-speaker keys using maximum shared
  duration under a bounded one-to-one mapping;
- computes exact interval durations without time-grid sampling;
- reports missed-speech, false-alarm, and speaker-confusion contributions to
  diarization error rate;
- includes simultaneous speaker time in the DER denominator;
- applies a declared collar and reference-boundary uncertainty;
- matches ordered speaker changes within a declared tolerance;
- reports boundary precision, recall, mean absolute error, and maximum error;
- reports duration-based overlap precision, recall, intersection, and duration
  error;
- excludes declared audience, background, and non-lexical reference regions;
- retains unknown speakers as local scoring speakers;
- reports declared fixture strata; and
- seals the reference, evaluation, and summary report independently.

Unlabeled simultaneous system tracks remain distinct for speaker-time
accounting but cannot receive an optimistic reference mapping.

## Consequences

- DER components remain auditable in microseconds.
- Overlap cannot be hidden by sequentializing simultaneous speech.
- Boundary tolerance and excluded content are persisted with the result.
- Controlled labels cannot be mistaken for names or biometric identity.
- A small synthetic fixture cannot support a general diarization or
  speaker-identification claim.
- Corrupt, incomplete, out-of-bounds, oversized-mapping, and incompatible
  cached evaluations are refused.
