# Phase 3 bounded reference-voice enrollment qualification

Status: **PASSED**  
Application version: 0.4.0  
Target Phase 3 application version: 0.5.0

This slice implements bounded reference-voice enrollment and validation
without performing voice comparison or participant binding.

Each enrollment is lineage-bound to one participant-identity foundation and
records the proposed identity, exact declared scope, source and recording
provenance, licensing status, consent or other lawful-use basis, source
interval, usable speech duration, audio quality, contamination, extraction
provider, model space, model fingerprint, and protected representation
reference and digest. Representation values do not enter portable contracts.

The default policy rejects unknown or restricted licensing, missing lawful-use
authority, insufficient speech, unusable audio, and known contamination.
Marginal quality and unresolved contamination produce explicit warnings.
Rejected evidence remains auditable.

Enrollment runs are immutable, integrity-sealed successors. Revocation and
replacement are append-only terminal lifecycle events. Replacement requires a
validated successor for the same identity and scope; original evidence remains
recoverable. Complete or incompatible cache fragments are refused.

CLI operations enroll, inspect, list, validate, revoke, and display lifecycle
history. Four focused enrollment tests and all 143 repository tests passed.
Schema export produced 192 runtime schemas plus 20 controlled-fixture schemas.

No similarity score, reference comparison, identity hypothesis, automatic
binding, manual binding, participant-labeled transcript, or participant-labeled
subtitle export was added.
