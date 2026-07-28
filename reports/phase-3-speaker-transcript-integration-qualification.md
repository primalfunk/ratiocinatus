# Phase 3 speaker-labeled transcript integration qualification

Status: **PASSED**  
Application version: 0.4.0  
Target Phase 3 application version: 0.5.0

This slice renders immutable speaker-labeled transcript presentation views
without modifying Phase 2 transcript evidence.

Each output pins the source transcript assembly and version, optional corrected
revision, canonical diarization run, identity-view assembly, and reviewed
identity-view version. The policy declares whether attribution applies to the
original-machine or current-corrected transcript.

Source segments and text are retained once. Normalized-time intersection
creates contiguous attribution spans carrying speaker turns, original segment
and retained word references, machine labels, reviewed labels, participant
identities, identity-view entries, and findings. This supports segments that
span turns, turns that span segments, and content with no speaker turn.

Reviewed, machine-cluster, unknown, unattributed, multiple-candidate, and
conflicted attribution remain distinct. Multiple simultaneous turns require an
explicit overlap disclosure. Conflicted reviewed identity views block trusted
participant rendering.

Corrected rendering validates the complete Phase 2 revision against its base
assembly and preserves the corrected version and revision identifiers.
Validation independently reconstructs all attribution spans. Persistence
refuses incomplete or incompatible caches and stores both machine-readable JSON
and a human-readable text derivative.

The CLI adds `speaker-transcript-render`, `speaker-transcript-inspect`,
`speaker-transcript-list-spans`, and `speaker-transcript-validate`.

Five focused tests and all 168 repository tests passed. Runtime schema export
contains 211 schemas plus 20 controlled-fixture schemas.

Participant-labeled WebVTT and SRT derivatives were not added in this slice.
