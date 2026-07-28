# ADR 019: Subtitles as loss-declared presentation derivatives

Status: Accepted  
Date: 2026-07-26

## Context

WebVTT and SubRip are useful presentation formats, but neither can carry the
complete transcript evidence model. They cannot faithfully embed canonical
source addresses, confidence origins, review regions, correction lineage,
segmentation decisions, or every known representational loss.

Subtitle export must also reduce microsecond evidence timestamps to
milliseconds and may need to divide long canonical segments. Those operations
must not silently change or discard uncertain text.

## Decision

Export subtitles from a declared immutable transcript view, never directly
from provider output. Every export has a sealed companion manifest and
validation report naming:

- the base assembly, optional correction revision, transcript version, and
  original-machine or current-corrected view;
- the source, corpus, canonical source and normalized intervals, and source
  artifact identifiers for every cue;
- a versioned policy that floors cue starts and ceilings cue ends to
  milliseconds;
- retained word identifiers when provider word timing safely supports a split;
- overlapping low-confidence region identifiers and a review recommendation;
- every generated WebVTT or SRT file, hash, byte length, and media type; and
- explicit records for timestamp rounding, normalized-text rendering,
  word-timing segmentation, retained long cues, line-limit overruns,
  low-confidence metadata, and format metadata kept in the manifest.

Long cues split only when retained word text exactly reconstructs the canonical
normalized text. Otherwise the full cue is retained and the limit exceedance is
recorded. This avoids manufacturing timing for corrected or otherwise
unsubstantiated words.

Export refuses blocked assemblies, missing corrected revisions, regressive or
out-of-range timing, invalid source mappings, malformed cue text, stale cache
contents, and file or report corruption. Rendering is deterministic from the
manifest.

## Consequences

WebVTT and SRT remain convenient views, not authoritative evidence. A consumer
needing provenance or confidence must retain the companion manifest.

Low-confidence text remains visible. Its review status moves to the manifest
because the target formats do not have a portable confidence model.

Corrected text may have canonical segment timing but no word-level split until
later alignment establishes new word evidence. This is an intentional
conservative limitation.

## Alternatives considered

- Embed all provenance in comments. Rejected because player support is
  inconsistent and SubRip has no dependable metadata convention.
- Round every boundary to nearest. Rejected because it can start a cue after
  or end it before its canonical evidence interval.
- Split long corrected cues proportionally by character count. Rejected
  because that invents lexical timing.
- Omit uncertain cues. Rejected because it silently suppresses evidence and
  creates a misleadingly clean presentation.
