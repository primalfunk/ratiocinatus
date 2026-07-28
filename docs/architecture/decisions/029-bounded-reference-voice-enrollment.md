# ADR 029: Bounded reference-voice enrollment

Status: Accepted  
Date: 2026-07-27  
Phase: 3

## Context

Participant-identity hypotheses need a controlled way to register reference
voice evidence before any acoustic comparison is attempted. A filename, display
label, or available embedding is not sufficient authority to enroll a voice.
Reference material may have unclear provenance, inadequate permission, poor
quality, insufficient speech, contamination, incompatible model lineage, or a
later revocation.

Enrollment must remain separate from comparison and identity binding. It must
also preserve replacement and revocation history without rewriting previously
accepted evidence.

## Decision

Reference voices are stored in an integrity-sealed, append-only enrollment run
bound to one participant-identity foundation.

Each enrollment records:

- the proposed identity and its exact declared scope;
- source and recording provenance;
- licensing and consent or other lawful-use basis;
- source-media interval and usable speech duration;
- audio quality and contamination assessment;
- extraction provider, model space, and model fingerprint;
- a protected representation reference and digest, never vector values;
- validation result, findings, disposition, expiry, and replacement lineage.

The default policy rejects references with restricted or unknown licensing,
without recorded consent or another lawful-use basis, with less than two
seconds of speech, with unusable audio, or with known contamination. Marginal
quality and possible or unknown contamination remain accepted only with an
explicit warning.

Revocation and replacement are terminal lifecycle events appended in successor
runs. Replacement requires a new enrollment for the same identity and scope
that passes validation. Original enrollments and lifecycle events remain
recoverable.

Enrollment does not calculate similarity, create an identity hypothesis,
confirm a participant, or modify diarization, clustering, or identity
foundation evidence.

## Consequences

- Multiple references can be retained for one identity.
- Invalid references remain auditable as rejected enrollments.
- Rights, consent, quality, and contamination failures are visible rather than
  inferred from filenames or hidden provider behavior.
- Revocation and replacement do not erase history.
- Later comparison work can accept only active, compatible enrollments.
- A later slice must define calibrated voice comparison and must not convert a
  score directly into an identity binding.
