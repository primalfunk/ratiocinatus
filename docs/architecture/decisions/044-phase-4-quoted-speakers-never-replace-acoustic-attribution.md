# ADR 044: Phase 4 quoted speakers never replace acoustic attribution

Status: Accepted  
Date: 2026-07-27

## Decision

Spoken quotations are stored as separate sealed records containing a bounded
text span, quotation type, attribution wording and source, quoted-speaker
target where supported, and the unchanged acoustic attribution of the quoting
utterance.

Quotation marks alone are insufficient. Automated candidates require an
explicit attribution, reporting, reading, recitation, imitation, or
hypothetical-speech cue. Automatic paraphrase inference and quoted-identity
binding are prohibited.

Embedded, replayed, remote, and synthesized speech are stored as separate
source records. Automated source candidates require explicit transcript
markers such as `[recording]`, `[remote]`, or `[voicemail]`.

## Consequences

- A named or hypothesized quoted person never becomes the acoustic speaker.
- Self-quotation may share the acoustic target, but only under an explicit
  self-reporting construction.
- External source matches require explicit references.
- Ordinary quotation punctuation and ordinary mentions of recordings do not
  create candidates.
- Unknown quoted or embedded speakers remain unknown and reviewable.
- Original utterance text, speaker attribution, and source type remain
  immutable evidence.
