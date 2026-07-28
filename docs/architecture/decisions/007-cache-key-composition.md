# ADR 007: Cache-key composition and validation

- Status: Accepted for Phase 1
- Date: 2026-07-26

## Context

Phase 1 must reuse expensive completed work without accepting a derivative from
different source content, stream selection, configuration, provider, tool
build, or artifact format.

## Decision

The version 1 audio-normalization cache key includes:

- complete source SHA-256 fingerprint and byte size;
- selected source-stream identity;
- operation name and version;
- canonical hash of all relevant normalization policy and source-layout input;
- provider identity;
- FFmpeg executable hash, version line, and build configuration; and
- derivative artifact-format version.

The executable path is recorded in provenance but excluded from the tool
identity hash, so moving an identical executable does not invalidate content.

Every hit is validated before reuse. Validation checks the closed manifest,
cache key, source and stream lineage, portable relative path, file presence,
file hash, decodability, duration, sample rate, channel count, sample format,
and sample count where available.

Generation occurs in a unique partial directory. The complete manifest is
written last, and the directory is atomically committed. Existing valid entries
are reused. Invalid entries are either refused by policy or preserved beneath
the cache's `invalid` directory before rebuilding. Cache bypass never
overwrites an existing derivative.

## Alternatives considered

- Path-based keys: fail when content changes at the same path or moves intact.
- Source hash only: silently reuses incompatible policy or tool results.
- Trust manifest and hash without decoding: misses substituted but
  self-consistent media metadata.
- Delete invalid entries: loses recovery and diagnostic evidence.

## Consequences

- Identical source, selection, configuration, provider, and tool build produce
  the same cache identity.
- Policy or tool changes create cache misses without disturbing unaffected
  entries.
- Validation adds a bounded FFprobe cost to every hit.
- Corrupt cache state remains available for recovery analysis.

## Reversibility

Cache and artifact formats are versioned key inputs. Composition can change in
a future format without treating older entries as compatible.

## Qualification evidence

Tests demonstrate miss, validated hit, hash-corruption detection and rebuild,
policy-sensitive invalidation, bypass behavior, and preservation of invalid
entries.
