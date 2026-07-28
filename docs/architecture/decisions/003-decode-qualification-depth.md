# ADR 003: Decode-qualification depth

- Status: Accepted for Phase 1
- Date: 2026-07-26
- Decision owners: Project owner and implementation agent

## Context

Container inspection confirms declared structure but does not prove that selected
streams decode throughout a recording. Always decoding every complete source
would make routine ingestion unnecessarily expensive, particularly for
multi-hour recordings, while probing only the beginning would miss common
truncation and seek failures.

## Decision

Default qualification decodes a bounded one-second window from each selected
stream at three source-relative positions:

- early: zero;
- middle: half of the latest valid probe start; and
- late: the latest valid probe start.

Short sources clamp all three positions to zero but retain distinct probe
records. Each stream is probed independently with an explicit FFmpeg stream map.
The provider uses argument arrays, disables interactive input, captures output,
records timeouts and exit codes, and sends decoded output to FFmpeg's null
muxer. It creates no derivative.

The selected streams' declared durations must agree with the container within
the greater of two seconds or one percent. Missing duration is a typed warning;
an implausible difference is a failure.

Full-file decode is supported as an explicit policy switch. Its default status
is `not_performed`, not success. Final Phase 1 qualification may require the
full-decode option for designated fixtures.

The source fingerprint is checked before and after qualification. Mutation
invalidates the operation.

## Alternatives considered

- Inspection only: too weak because decoder, timestamp, and truncation failures
  can remain hidden.
- Beginning-only probe: inexpensive but does not exercise representative seek
  points or the end of the recording.
- Mandatory full decode: strongest single check but too costly as the default
  for resumable iteration over long recordings.
- Combined audio/video probes: fewer processes, but a failure is less precisely
  attributable to one selected stream.

## Consequences

- Default qualification cost is bounded by the number of selected streams and
  the probe duration.
- Every probe has independent invocation evidence and a typed outcome.
- Successful samples are evidence of representative decodability, not proof
  that every packet in the recording decodes.
- Full decode remains available when a qualification gate demands it.

## Reversibility

Probe positions, duration, timeout, and full-decode behavior are versioned
policy fields. A future policy can add more samples without changing stored
results from this version.

## Qualification evidence

The canonical Riverton clean MP4 passed six default probes: audio and video at
early, middle, and late positions. Decode-start, sampled-decode, and duration
plausibility statuses were all `success`; full decode was explicitly
`not_performed`.
