# ADR 035: Participant subtitles are loss-declared presentation derivatives

Status: Accepted  
Date: 2026-07-27  
Phase: 3

## Context

WebVTT and SRT can display labels and text, but cannot carry the complete
transcript, diarization, identity, review, conflict, and policy graph. They
also round microsecond evidence to milliseconds and cannot safely partition
text at every speaker boundary when word alignment is unavailable.

Export must not turn these format limitations into false identity precision.

## Decision

Participant-labeled WebVTT and SRT are optional presentation derivatives of a
validated speaker-labeled transcript view.

Every export manifest pins:

- the speaker-transcript view;
- source transcript assembly, version, and optional corrected revision;
- identity-view assembly and reviewed view;
- diarization run;
- corpus and source addressing;
- cue, line, rounding, long-cue, multi-attribution, overlap, and conflict
  policies;
- attribution spans and identity-view entries used by each cue;
- declared losses; and
- output file hashes and sizes.

The participant label is always the first cue line. Unknown speakers remain
`REVIEWED: UNKNOWN`, unattributed content remains `UNATTRIBUTED`, and machine-
only attribution retains its visible machine-cluster label. Multiple
attributions are combined without inventing a word-level partition. Overlap is
prefixed with `OVERLAP: `.

A conflicted or otherwise blocked speaker transcript is refused before any
subtitle file is written. Microsecond rounding, normalized text, retained long
cues, line-capacity excess, combined attribution, and unavailable format
metadata are declared in the companion manifest.

## Consequences

- Subtitle labels remain traceable to reviewed decisions.
- Unknown and overlap states survive portable presentation.
- WebVTT/SRT cannot be mistaken for authoritative identity records.
- Corrected transcript lineage remains explicit.
- Consumers can validate byte-for-byte deterministic rendering.
- Phase 3 recovery and evaluation can treat subtitle export as an independently
  invalidatable downstream stage.
