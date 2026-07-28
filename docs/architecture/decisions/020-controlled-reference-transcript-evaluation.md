# ADR 020: Controlled-reference transcript evaluation

Status: Accepted  
Date: 2026-07-26

## Context

Provider execution and canonical assembly do not establish transcription
quality. Evaluation requires independently prepared reference text with an
explicit relationship to the source timeline. A single WER number would also
hide timing behavior, conditions represented by the corpus, unavailable
reference evidence, confidence reliability, correction effects, and subtitle
validity.

Reference text creates a leakage risk if it is passed to the provider being
evaluated. Controlled synthetic results also risk being described too broadly.

## Decision

Represent evaluation input as a strict, versioned `ReferenceTranscript`. It
names the corpus, source, source and normalized-audio hashes, timeline mapping,
source and schedule document hashes, provenance, independence statement, and
one or more source-addressed reference segments. Each segment declares at least
one controlled stratum. Optional reference words and expected candidate labels
remain absent unless independently prepared evidence supports them.

Evaluate one declared immutable transcript version and view. The sealed report
contains:

- word substitutions, deletions, insertions, WER, character edits, and CER;
- aggregate and represented-stratum edit metrics;
- segment onset and offset error using maximum interval overlap followed by
  nearest midpoint;
- word timing error when the reference supplies word timing, or an explicit
  unavailable result otherwise;
- descriptive confidence/reliability bins that retain confidence origin and do
  not claim calibration;
- candidate-selection accuracy only when references label an expected
  candidate;
- validated subtitle cue counts when a matching export is supplied;
- original versus corrected WER/CER and their signed change when a revision is
  supplied;
- the count of reference segments overlapping machine-readable review regions;
  and
- findings that limit interpretation to the controlled reference.

Text normalization uses Unicode NFKC, case-folding, and a versioned
alphanumeric/apostrophe token policy. Reference text is evaluation-only input
and must not enter speech detection or transcription inference.

Reports and their human-readable renderings are persisted atomically under a
stable evaluation identity. Reuse requires exact report, source-lineage,
integrity-seal, and rendering agreement.

## Consequences

Unavailable word timing and candidate labels remain visible rather than
becoming zero error or inferred labels. Adding those references later creates
new reference and evaluation identities.

Timing error is a presentation of boundary disagreement, not speaker
assignment or semantic alignment. Confidence reliability is descriptive unless
a separately documented calibration study supports stronger claims.

The initial qualification covers public Riverton lines L001–L005. It cannot
support general claims or condition-specific claims for perturbations occurring
elsewhere in the fixture.

## Alternatives considered

- Keep evaluation calculations only in qualification scripts. Rejected because
  required results would lack strict artifacts, cache validation, and CLI use.
- Evaluate provider output directly. Rejected because the canonical
  transcript version and correction lineage would be bypassed.
- Treat missing reference word times as zero timing error. Rejected because it
  invents evidence.
- Report only aggregate WER. Rejected because it conceals edit composition,
  timing behavior, represented conditions, and correction effects.
- Use hidden analytical references. Rejected because Phase 2 evaluates speech
  evidence, not later argument or adjudication labels.
