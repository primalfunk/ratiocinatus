# ADR 039: Phase 4 utterances are derived analytical groupings

Status: Accepted  
Date: 2026-07-27  
Phase: 4

## Context

Transcript segments reflect transcription behavior, while speaker turns are
temporal speaker-participation claims. Neither is reliably identical to a
discourse utterance. Treating any of these units as interchangeable would hide
uncertainty and make later correction propagation destructive.

## Decision

Phase 4 represents an utterance as a versioned derived grouping over declared
Phase 2 transcript and Phase 3 identity-view versions. Each utterance preserves
ordered source and normalized intervals, transcript components, speaker
evidence, text views, attribution disposition, completeness, structural states,
review status, creation process, configuration, and integrity.

Canonical transcript words may have at most one utterance owner within one
utterance-corpus version. Simultaneous utterances remain possible because
source intervals may overlap across utterances. Unknown and conflicting
attribution are valid explicit results.

## Consequences

- Utterance construction cannot rewrite prior-phase evidence.
- Stable identifiers depend on evidence, configuration, and review state.
- Text normalization cannot invent or silently repair speech.
- Quoted and acoustic speakers remain separate.
- Interruption structure cannot imply intent or blame.
- Later segmentation and review operations must produce derived successors.
