# ADR 010: Explicit, derivative-based chunk materialization

Status: Accepted  
Date: 2026-07-26

## Context

The canonical chunk plan is virtual: intervals address the normalized corpus
without multiplying stored media. Some downstream providers nevertheless
require a file per chunk. Those files must not become silent alternate sources,
and cache reuse must not bypass integrity checks.

## Decision

Audio chunks are materialized only by an explicit request with a recorded
reason. The input is the validated normalized audio derivative, not the
original source. Materialization:

- uses the chunk's half-open normalized-corpus interval;
- preserves FLAC, sample rate, channel count, and signed-16 sample format;
- records the source derivative identity and hash, corpus interval, original
  source interval, derivative-local interval, expected and actual duration,
  exact FFmpeg arguments, tool identity, output hash, size, and integrity;
- includes the reason, interval, derivative identity, policy, provider, tool,
  and artifact-format version in its cache identity;
- validates the derivative hash before and after work;
- re-hashes and decodes cached output before reuse;
- quarantines invalid cache entries before rebuilding, or refuses according to
  policy; and
- never overwrites an existing destination when cache use is bypassed.

The output remains a derived convenience artifact. The virtual chunk plan and
portable corpus remain authoritative.

## Consequences

Providers that accept interval-addressed streams incur no extra storage.
Providers that require files receive independently validated artifacts with
complete lineage. Identical silent chunks may have identical content hashes,
while retaining distinct materialization and chunk identities.
