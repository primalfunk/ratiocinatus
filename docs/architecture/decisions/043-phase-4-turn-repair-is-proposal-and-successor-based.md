# ADR 043: Phase 4 turn repair is proposal- and successor-based

Status: Accepted  
Date: 2026-07-27

## Decision

Phase 4 detects bounded mismatches among transcript words and segments,
speaker-change boundaries, speaker turns, attribution spans, and utterance
ownership. Every conflict records supporting and contrary evidence.

Automated rules may propose a boundary move or turn split only when timestamp
evidence satisfies declared tolerances. Mixed-speaker, overlap, unknown, and
equal-support cases are preserved or marked unresolved. Automated word
reassignment is prohibited.

A review decision is append-only. Accepting a proposal creates a sealed
`TurnRepairSuccessor` that projects the proposed change and explicitly retains
all predecessor artifact references. The predecessor transcript, diarization,
speaker view, and utterance corpus are never modified.

## Consequences

- All eight required repair actions are representable by strict contracts.
- Machine proposals remain distinct from manual decisions.
- Contrary evidence is mandatory and remains visible during review.
- Rejected and deferred decisions do not create successors.
- Accepted decisions must create exactly one derived successor.
- Successor records describe a bounded change projection; later stages may
  assemble successor views without overwriting prior evidence.
