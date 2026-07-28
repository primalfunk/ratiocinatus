# ADR 017: Deterministic canonical transcript promotion

Status: Accepted  
Date: 2026-07-26

## Context

Provider transcript observations are fallible evidence. Phase 2 nevertheless
needs stable canonical segment and word artifacts for later correction,
assembly views, and subtitle export. Promotion must not imply that selected
provider text is true, fabricate confidence, discard alternatives, or hide
missing and ambiguous output.

The canonical artifacts also need the selected Phase 1 audio-stream lineage,
both source and normalized intervals, processing-chunk ownership, speech
activity references, provider/model identity, and content integrity.

## Decision

Introduce a versioned `TranscriptAssemblyPolicy` and keep provider inference
separate from canonical promotion. The promotion stage:

- accepts only a valid Phase 1 corpus and a validated persisted transcription
  request, response, and report from the same lineage;
- promotes only the explicitly selected, non-empty candidate from each
  provider observation;
- normalizes text with Unicode NFKC and whitespace collapse while preserving
  case;
- creates stable `TranscriptSegment` and timestamped `TranscriptWord`
  identities from evidence and policy, not wall-clock execution time;
- preserves the proposed text, selected candidate, alternatives, confidence
  origin and basis, timestamp origin, provider token reference, and all mapped
  intervals;
- uses the provider response completion time as the deterministic creation time
  for the original machine version;
- creates machine-readable `LowConfidenceRegion` artifacts for weak or
  unavailable text, timing, and boundary confidence, candidate disagreement,
  missing word timing, missing output, and provider failure;
- blocks downstream use when an observation cannot be promoted, but does not
  block merely because the initial Whisper provider lacks calibrated timing
  confidence;
- emits one immutable original-machine `TranscriptVersion`;
- persists the assembly, version, each segment, each word, each low-confidence
  region, and machine/human reports separately; and
- verifies artifact seals, version digests, cross-references, word containment,
  non-regressing segment order, cache identity, and Phase 1 stream lineage on
  reuse.

Confidence thresholds compare only measures already supplied or explicitly
derived by the same provider. They are review-routing policy, not a claim that
scores from different providers are calibrated or comparable.

## Consequences

Canonical means structurally selected and addressable, not factually correct.
The original provider candidate remains recoverable, and low-confidence cues
cannot disappear into report prose or display styling.

With the initial Whisper provider, canonical segments and words are expected to
carry review regions because segment, word-timing, and boundary confidence are
unavailable. Those regions do not block later review-oriented processing.
Missing selected text and provider failure do block downstream use.

Changing provider evidence, selected candidate, source/configuration lineage,
or assembly policy produces new segment and version identities. Rendering-only
changes do not. Later corrections will create successor versions rather than
altering the original machine version.

## Alternatives considered

- Treat every completed provider observation as canonical automatically.
  Rejected because empty, unresolved, or contradictory observations require an
  explicit policy result.
- Copy segment confidence onto words. Rejected because it would fabricate
  word-level evidence.
- Represent weak evidence only with report prose or UI color. Rejected because
  review and blocking state must be machine-readable.
- Omit unavailable timing confidence from review routing. Rejected because
  absence of evidence is operationally important and must remain visible.
- Use assembly execution time in stable artifact identities. Rejected because
  replaying identical stored evidence and policy must reproduce the same
  assembly.
