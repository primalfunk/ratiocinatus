# ADR 012: Packet continuity and version-aware recovery

Status: Accepted  
Date: 2026-07-26

## Context

Representative decoding proves that selected payloads can produce output at
bounded positions, but it does not independently expose packet timestamp gaps
or DTS regressions. Resume also needs to distinguish recoverable stale output
from compatible committed output. Treating unknown persisted format versions
as current would make that distinction unsafe.

## Decision

Selected audio and video streams receive bounded early, middle, and late
FFprobe packet probes. The provider records packet counts, missing PTS/DTS,
maximum DTS gaps, DTS regressions, discontinuity intervals, invocation
evidence, and the exact FFprobe identity. Detected discontinuities can be
applied to the source timeline and therefore become visible to mapping.

Packet continuity complements decoded-output qualification. Neither is allowed
to stand in for the other: structurally continuous packet timestamps do not
prove that a truncated payload decodes.

Phase 1 persisted contract versions are closed literals. Unsupported versions
fail validation. During resumable ingestion, incompatible or corrupted
committed artifacts are recorded as invalidated and preserved before rebuild.
Write denial, full-disk, and stage-builder failures are recorded as failed
attempts before the exception is propagated.

## Alternatives

- Rely only on FFmpeg decode exit codes. Rejected because successful process
  exit can occur without decoded output and provides weak timestamp evidence.
- Scan every packet in every source. Deferred because bounded probes provide a
  predictable initial qualification cost; full scans can be added as an
  explicit policy mode.
- Accept future format versions using permissive strings. Rejected because
  consumers cannot safely infer forward compatibility.

## Consequences

The corpus boundary now has complementary payload and timestamp evidence, and
resume does not silently reuse unknown formats. Packet inspection remains
representative rather than exhaustive. Sources requiring timestamp repair are
refused; remux or transcode remediation remains a future versioned policy.

## Reversibility and qualification

Probe depth and discontinuity thresholds are versioned policy values and can be
revised without changing source evidence. Qualification covers all 18 selected
Riverton stream/position probes, synthetic regression/gap inputs, a truncated
payload, unsupported persisted versions, tool-version mutation, write denial,
and simulated full disk.
