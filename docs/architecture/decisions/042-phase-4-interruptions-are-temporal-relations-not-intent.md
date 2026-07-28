# ADR 042: Phase 4 interruptions are temporal relations, not intent

Status: Accepted  
Date: 2026-07-27

## Decision

Phase 4 stores adjacency, overlap, interruption, and continuation as separate
sealed relations derived from the utterance corpus, completeness analysis, and
Phase 3 diarization evidence.

A simultaneous interruption requires a Phase 3 overlap interval projected
onto at least two utterances. An immediate takeover requires a short temporal
gap, different explicit speaker attribution, and an observable incomplete
terminal signal. All relations remain review candidates.

Every Phase 3 overlap interval is preserved. Its projection explicitly records
whether speech was separated into utterances, remained mixed, has uncertain
word attribution, or was untranscribed.

Possible resumptions require the same explicit attribution target, bounded
elapsed time, an unresolved or incomplete predecessor, and intervening
utterance activity. They remain unresolved continuation candidates because
this slice does not use semantic similarity.

## Consequences

- Overlapping speech remains a partial temporal order and is not serialized
  into a false conversational sequence.
- Supportive interjection, backchannel, moderator cutoff, technical cutoff,
  and audience interruption types are representable but not inferred here.
- An interruption record never establishes blame, intent, dominance, or
  conversational quality.
- Continuation cycles and temporally impossible ordering are rejected.
- Raw utterances, completeness evidence, and Phase 3 diarization remain
  immutable source evidence.
