# ADR 013: Separate speech providers and conservative confidence

Status: Accepted  
Date: 2026-07-26

## Context

Speech presence, recognized text, and temporal alignment are different
evidentiary claims. Providers expose unlike scores and capabilities, and some
provide no meaningful confidence or word timing. A generic provider result or
single confidence number would conceal those differences.

## Decision

Speech activity and transcription use separate provider interfaces, requests,
policies, and result contracts. Provider identity includes the implementation,
model identity or fingerprint where known, licensing, distribution status, and
declared capabilities.

Every confidence measure records a value only when available, its origin, its
basis, and a calibration identity if claimed calibrated. Provider-native and
derived confidence remain distinguishable. Scores are not comparable across
providers without a separately documented calibration.

Word timestamp origin is independently classified as provider-native,
estimated, externally aligned, or unavailable. Provider-normalized
observations are evidence inputs and do not become canonical transcript
segments merely because they pass schema validation.

Unconfigured provider boundaries advertise `available: false` and raise a
typed unavailable error. They never return placeholder transcript text.

## Alternatives

- Reuse the Phase 0 generic transcription provider payload. Rejected because it
  cannot express temporal, confidence, model, or failure semantics precisely.
- Combine speech detection and transcription. Rejected because confidence and
  failure in one stage must not imply the same state in the other.
- Substitute a default numeric confidence when providers omit one. Rejected
  because it invents evidence.

## Consequences

Later provider integrations must normalize their output without leaking
provider-specific fields into authoritative contracts. Callers must handle
unavailable confidence and timestamps explicitly. This adds structure but
prevents model output from being represented as settled source truth.

## Reversibility and qualification

Provider implementations are replaceable behind the interfaces. Policies and
persisted formats are versioned. Contract tests cover unknown versions,
impossible confidence states, contradictory capability claims, invalid mapped
intervals, implicit candidate selection, unavailable providers, and structured
capability inspection.
