# ADR 061: Phase 5 evaluation is controlled, stratified, and not-applicable-aware

## Status

Accepted.

## Context

Discourse construction produces multi-label, span-addressed, relational, and
often unresolved analytical evidence. A single aggregate accuracy value would
hide important failure modes and could incorrectly treat absent reference
phenomena as perfect performance. Synthetic fixtures can prove mechanics, but
they cannot establish natural-conversation quality.

## Decision

Phase 5 evaluation uses sealed controlled references that declare:

- utterance-owned act families and types;
- exact evidence spans;
- expected relation targets;
- expected alternative candidates;
- unresolved outcomes;
- conversational strata;
- preparation provenance; and
- whether the evidence is controlled-reference or synthetic-mechanics evidence.

The evaluator reports all 28 work-order measurement dimensions. Metrics without
eligible reference evidence are explicitly `not_applicable` with a zero
denominator and no value. They are never reported as perfect scores.

Act family and type use micro precision, recall, and F1. Compatible multi-label
sets use exact set match and Jaccard partial match. Evidence spans use
one-to-one intersection-over-union matching at a policy threshold. Relation,
question, lexical, quotation, and procedural measurements retain their
domain-specific labels. Confidence reliability is disclosed as reliability of
uncalibrated ranking scores, not probability calibration.

Correction propagation, unaffected-artifact stability, and human-review impact
are measured only when their sealed source artifacts are supplied. Machine and
reviewed evidence remain separate.

Results are stratified by declared conversational conditions. Synthetic
mechanics results are labeled as such and cannot support natural-conversation
performance claims.

## Consequences

Evaluation is reproducible, complete in metric inventory, and conservative
about missing evidence. Later controlled corpora can populate additional
strata without changing metric semantics. Completion reports can consume the
sealed evaluation directly, while export, recovery, and long-recording
qualification remain separate Stage 10 evidence.
