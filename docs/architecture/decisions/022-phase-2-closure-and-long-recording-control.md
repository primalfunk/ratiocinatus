# ADR 022: Phase 2 closure and long-recording control

Status: Accepted  
Date: 2026-07-26

## Decision

Close Phase 2 at application version 0.4.0 after the 13 exit gates pass.

Qualify the recording-longer-than-two-hours path by reusing the existing
Apache-2.0 Phase 1 long corpus and running Phase 2 with visibly synthetic,
qualification-only activity and transcription marker providers. Emit one
canonical owned interval and one mapped transcript marker per Phase 1 chunk.

Use the synthetic control only to measure source preservation, inherited
overlap ownership, temporal mapping, cache replay, persisted-stage resume,
bounded Python allocation, integrity validation, and final canonical assembly.
Do not use it to claim speech-detection or transcription accuracy.

Normalize every work-order negative case into the checked-in
`phase-2-negative-proofs` report. A case passes only when its selected test
asserts the expected typed refusal or conservative recovery and is not skipped.

## Rationale

Running semantic VAD and Whisper over two hours of deliberately silent
technical media would spend substantial compute while producing no meaningful
accuracy evidence. The mechanical long-recording risks are chunk ownership,
addressing, memory, resume, caching, and assembly. Synthetic markers isolate
those risks without presenting generated text as an observation about the
recording.

Recognition quality remains measured separately against the frozen controlled
Riverton references. Keeping the two claims separate preserves evidentiary
clarity.

## Consequences

- Phase 2 completion evidence distinguishes controlled accuracy from
  long-recording mechanics.
- The long run must preserve the Phase 1 corpus tree byte-for-byte.
- Qualification providers are script-local and are not exposed as production
  CLI providers.
- Later phases may consume transcript evidence but may not reinterpret it as
  source truth or infer identity, argument, judgment, or score within Phase 2.
