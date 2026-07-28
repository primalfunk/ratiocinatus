# ADR 053: Phase 5 deterministic baseline prefers unknown to weak cues

Status: Accepted  
Date: 2026-07-27  
Phase: 5

## Decision

The first Phase 5 classifier is a versioned, provider-free, high-precision
baseline. It emits discourse-act observations only when an explicit lexical or
structural cue supports a bounded type. Punctuation alone, generic declarative
form, and unconstrained semantic interpretation are insufficient.

Every match creates an exact Phase 4 display-text span, source-media interval,
uncalibrated rule-strength confidence, rule identifier, and immutable
observation. Several compatible rules may match one utterance. Unmatched
utterances are explicitly unclassified.

Quotation observations consume declared Phase 4 quotation evidence. They do
not independently reinterpret quotation marks or alter acoustic attribution.

## Consequences

- The baseline is measurable before model assistance.
- Recall is intentionally limited in favor of inspectable evidence.
- A question mark alone does not establish question function.
- Rule strength is not presented as calibrated probability.
- Partial text spans may retain utterance-resolution media timing when no
  word-to-character alignment exists, and that limitation is disclosed.
- Provider execution, truth assignment, answer-quality scoring, intent
  inference, and semantic claim extraction are prohibited in this stage.

