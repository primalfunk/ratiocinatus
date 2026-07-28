# Phase 3 participant-labeled subtitle qualification

Status: **PASSED**  
Application version: 0.4.0  
Target Phase 3 application version: 0.5.0

This slice adds deterministic participant-labeled WebVTT and SRT derivatives
from a validated speaker transcript.

Each manifest declares the speaker-transcript view, source transcript assembly
and version, optional corrected revision, identity-view assembly, reviewed
identity-view version, diarization run, corpus, source addressing, cue policy,
attribution spans, identities, identity-view entries, losses, and output file
hashes.

Labels occupy the first cue line. Reviewed, machine-cluster, unknown,
unattributed, multiple-candidate, and overlap states remain visible. Overlap is
explicitly prefixed and multiple attribution is retained without inventing a
word-level text partition. A conflicted or blocked speaker transcript refuses
export before any VTT or SRT is written.

The companion manifest declares millisecond rounding, normalized rendering,
combined attribution, retained long cues, line-capacity excess, and format
metadata that cannot fit in WebVTT/SRT. These exports are presentation
derivatives, not identity records.

Validation reconstructs cues and loss declarations, verifies source addressing,
re-renders each format, and checks paths, byte counts, and hashes. Persistence
refuses incomplete or incompatible caches and reuses exact exports.

The CLI adds `participant-subtitle-export`, `participant-subtitle-inspect`,
`participant-subtitle-list-cues`, and `participant-subtitle-validate`.

Five focused tests and all 173 repository tests passed. Runtime schema export
contains 215 schemas plus 20 controlled-fixture schemas.

Phase 3 stage-local cache recovery and controlled diarization evaluation remain
later work.
