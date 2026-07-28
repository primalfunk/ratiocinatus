# ADR 040: Canonical words have one utterance owner per corpus version

Status: Accepted  
Date: 2026-07-27  
Phase: 4

## Context

A timestamped Phase 2 word can intersect more than one Phase 3 attribution span
when a speaker boundary falls inside its interval. Copying the word into both
utterances would duplicate canonical speech. Dropping it would silently lose
transcript evidence. Assigning it to a speaker without recording ambiguity
would overstate the timing evidence.

## Decision

Initial Phase 4 segmentation assigns each canonical word to the attribution
span with the greatest temporal intersection. Exact ties resolve
deterministically to the earlier stable span and create an uncertain
word-attribution finding requiring review.

Construction and validation require the utterance corpus to own every canonical
Phase 2 word exactly once. Each component directly records its Phase 2 segment
and word IDs and its Phase 3 speaker-turn and speaker-observation IDs.

## Consequences

- Canonical transcript evidence cannot silently disappear or be duplicated.
- Boundary ties remain visible rather than becoming false speaker certainty.
- Changing the policy produces a new Phase 4 corpus identity only.
- Phase 2 and Phase 3 artifacts remain immutable.
- Accepted later repairs must produce Phase 4 successors.
