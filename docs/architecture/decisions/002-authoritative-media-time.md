# ADR 002: Authoritative media-time representation

- Status: Accepted for Phase 1
- Date: 2026-07-26
- Decision owners: Project owner and implementation agent

## Context

Phase 1 must preserve exact traceability across source, normalized corpus,
derivative, and chunk time domains. Media containers expose rational time bases
and may also expose negative or non-zero starts. Binary floating-point seconds
cannot be the authoritative stored representation.

## Decision

Canonical public intervals and durations use signed integer microseconds.
Parsing decimal FFprobe seconds uses decimal arithmetic with round-half-even
conversion. Original integer timestamps and rational time-base strings are
retained wherever FFprobe provides them, so a later validator can reproduce and
audit the conversion.

Normalized corpus time will begin at zero. Source media time may be negative or
non-zero. Models must name their time domain rather than relying on an implicit
timeline. Floating-point seconds may appear only as non-authoritative display
values.

Mapping results will declare whether a conversion is exact, rounded, clipped,
discontinuous, unavailable, or ambiguous. A later Phase 1 slice will define the
mapping and tolerance contracts.

## Alternatives considered

- Binary floating-point seconds: familiar but not stable enough for canonical
  equality or long chains of interval transformations.
- Rational values everywhere: maximally exact but cumbersome for application
  boundaries and ordinary interval operations.
- Integer nanoseconds: finer than the source material normally warrants and
  increases the risk of implying unsupported precision.

## Consequences

- Canonical values are portable and straightforward to compare.
- Negative source starts remain representable.
- Some rational media timestamps require a declared rounding classification.
- Original timestamp and time-base evidence must be retained beside converted
  microseconds.

## Reversibility

The representation can be extended with an exact rational pair in a future
contract version. Existing microsecond values remain valid derived fields.

## Qualification evidence

The Phase 1 inspection tests cover exact positive duration conversion and a
negative source start. The canonical Riverton clean MP4 inspection preserves
the video `1/15360` and audio `1/48000` time bases and reports zero stream
starts.
