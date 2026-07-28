# Phase 4 quotation and embedded-speech qualification

- Status: passed
- Target application version: 0.6.0
- Evidence class: synthetic mechanics
- Quotation contract models: 6
- Runtime schemas: 275
- Focused Stage 6 tests: 5
- Full regression tests: 219

This slice qualifies bounded quotation spans and explicit embedded, replayed,
remote, and synthesized speech-source candidates.

Quotation punctuation alone is insufficient. Quoted-speaker attribution is
stored separately and cannot replace the acoustic speaker of the utterance.
Embedded-source candidates require explicit transcript markers and remain
reviewable; they do not establish an external media source by themselves.
