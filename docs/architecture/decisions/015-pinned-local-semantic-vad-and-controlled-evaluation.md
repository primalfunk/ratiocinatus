# ADR 015: Pinned local semantic VAD and controlled evaluation

Status: Accepted  
Date: 2026-07-26

## Context

The energy-activity baseline proves chunking, ownership, mapping, persistence,
and negative-control behavior, but it cannot distinguish speech from energetic
non-speech. Phase 2 therefore needs a semantic speech-presence provider without
weakening the provider-independent evidence contracts or creating a network
dependency.

Provider probabilities, speech boundaries, and controlled-fixture evaluation
metrics are different claims. A model probability must not be presented as a
calibrated corpus probability, and a favorable synthetic result must not become
a general performance claim.

## Decision

Use the optional local `silero-vad==6.2.1` package through provider identity
`local.silero_vad`. The integration:

- requires the exact package version and verifies the packaged TorchScript
  model SHA-256
  `e1122837f4154c511485fe0b9c64455f7b929c96fbb8d79fbdb336383ebd3720`;
- records package, model, Torch, FFmpeg, configuration, and integration
  identity in evidence-sensitive fingerprints;
- loads the model from the installed package without a runtime download;
- does not redistribute the package or model in this repository;
- analyzes 16 kHz mono PCM in 512-sample (32 ms) frames;
- resets model state at every Phase 1 chunk, using inherited overlap as context
  before clipping to canonical ownership;
- retains provider-native frame probabilities as uncalibrated confidence;
- preserves the threshold band as `uncertain`;
- represents a decodable-duration remainder of at most one frame as uncertain,
  while rejecting larger PCM coverage gaps; and
- retains the energy provider as a control and diagnostic baseline.

Evaluate only `probable_speech` as the positive class. Controlled references
come from the public, project-authored line schedules prepared before this
provider was selected. Overlapping and adjacent scheduled lines are unioned.
Report duration-weighted precision, recall, F1, false-positive and
false-negative durations, plus nearest-reference-boundary error. Uncertain
output is non-positive and is never silently promoted to speech.

Silero VAD is MIT-licensed according to its
[official repository](https://github.com/snakers4/silero-vad) and
[PyPI package](https://pypi.org/project/silero-vad/). Its Python runtime
dependencies retain their own terms.

## Consequences

Semantic speech activity remains an optional installation (`.[vad]`) and an
explicit provider choice. Base installation and ordinary offline tests do not
require a model. A missing or mismatched package/model cannot masquerade as the
qualified provider.

The initial controlled measurements are useful regression evidence, not a
production accuracy guarantee. Nearest-boundary error is deliberately labeled
as such; it is not an onset/offset assignment score. Hidden argument and
discourse references are outside this evaluation and remain unread.

## Alternatives considered

- Keep the energy baseline as the production detector. Rejected because its
  known tone/noise false positives are semantic failures.
- Use a remote VAD service. Rejected for the initial provider because it would
  add network, retention, cancellation, and service-version uncertainty.
- Redistribute model weights in the repository. Rejected because the installed
  optional package supplies the pinned artifact and redistribution is
  unnecessary.
- Convert probabilities directly to a calibrated confidence claim. Rejected
  because no Ratiocinatus corpus calibration has been performed.
