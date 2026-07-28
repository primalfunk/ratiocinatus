# ADR 041: Phase 4 structural analysis does not rewrite utterances

Status: Accepted  
Date: 2026-07-27

## Decision

Completeness, disfluency, and self-repair analysis is stored as sealed,
source-addressed evidence separate from the utterance corpus.

Completeness classification uses only bounded observable signals in this
slice: lexical-token presence, duration, punctuation, and the source-media
boundary. If those signals do not support a class, the result is `unknown`
and requires review. Semantic completion is prohibited.

Disfluency spans retain exact transcript word identifiers, time intervals,
and surface wording. Self-repair records explicitly separate reparandum,
repair marker, and repair word identifiers. Every detected relation remains
a review candidate.

## Consequences

- Raw, display, and minimally normalized utterance text remain unchanged.
- Analysis can be regenerated and compared without invalidating the corpus.
- Filler, hesitation, repetition, false-start, and explicit-correction
  candidates remain directly traceable to canonical words.
- Candidate labels describe observed speech structure; they are not clinical,
  psychological, intentional, or quality judgments.
- Grammatical and discourse-level completion remain unresolved until a later
  reviewed or appropriately qualified analysis stage.
