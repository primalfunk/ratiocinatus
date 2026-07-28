# Phase 1 completion report

Status: **COMPLETE**  
Date: 2026-07-26  
Application version: 0.3.0  
Contract version: 0.1.0  
Corpus format: 1.0.0

Phase 1 satisfies its success definition. Ratiocinatus accepts a complete
audiovisual source and produces a portable, integrity-checked, addressable,
resumable corpus without producing a transcript, speaker analysis, argument
artifact, judgment, score, or analytical overlay.

## Exit gates

| Gate | Status | Evidence |
|---|---|---|
| Inspection and selection | Complete | Raw FFprobe evidence, complete stream inventory, deterministic default and explicit selection |
| Decode and packets | Complete | Early/middle/late decoded-output probes and bounded packet continuity for selected streams |
| Timeline | Complete | Explicit integer-microsecond domains, interval mappings, clipping and discontinuity classifications |
| Audio | Complete | Lossless 16 kHz mono signed-16 FLAC, validated duration and integrity, no evidentiary enhancement |
| Video | Complete | Timestamp-addressed qualified source passthrough; VFR, rotation, and pixel aspect preserved |
| Chunks | Complete | Stable virtual 10-minute chunks, five-second overlap ownership, optional validated materialization |
| Cache | Complete | Valid reuse, configuration invalidation, corruption quarantine/rebuild, refuse, and bypass |
| Resume | Complete | Interruption after every one of 11 persisted stages and targeted fault recovery |
| Long recording | Complete | 7,201-second source, 13 chunks, exact start/middle/end mapping, bounded memory |
| Corpus | Complete | Relative references, copied source/audio evidence, validation, export, and reload |
| Reporting | Complete | Machine contracts plus human CLI/report renderings and checked-in qualification evidence |
| Regression and boundary | Complete | 77 tests, Phase 0 proof, Phase 0.5 media validation, no analytical artifacts |

All Phase 0/1 persisted format and policy versions are strictly validated.
There are 79 exported Phase 0/1 schemas and 20 fixture schemas.

## Canonical-source results

All three Riverton variants passed integrity validation. Each selected global
stream 0 for video and stream 1 for audio. Their 18 decoded-output probes and
18 packet-continuity probes passed. No packet DTS regression or discontinuity
was detected.

The normalized derivatives are lossless 16 kHz mono signed-16 FLAC. All three
passed independent decode, hash, size, duration, format, channel, sample-rate,
and sample-count checks. Their source-to-derivative duration differences were
2,687, 18,313, and 3,313 microseconds, within the declared 100,000-microsecond
tolerance.

Video remains source passthrough. Timestamp-based access is qualified; VFR,
rotation, non-square pixels, and a positive 1/1,000,000 time base retain their
metadata. Unsupported pixel formats and damaged decoded payloads are refused.

## Recovery and scale

The recovery matrix passed interruption and resume after all 11 persisted
stages. It also passed orphan-partial recovery, derivative substitution,
changed source and configuration detection, isolated chunk-policy invalidation,
write denial, simulated full disk, unsupported stage and corpus versions, and
external-tool version mutation. The measured matrix took 31.765811 seconds.

The synthetic long source was 7,201 seconds and 233,429,346 bytes. Ingestion,
resume, and three chunk materializations completed in 7.66981 seconds, produced
469,902,759 bytes, and peaked at 2,495,017 Python allocator bytes. All 13 chunks
covered the source, and sampled materializations changed from cache miss to
validated cache hit.

## Dependencies and repository state

Phase 1 adds no Python runtime dependency. FFmpeg and FFprobe are required
external, unbundled tools. Qualification used the
`2024-09-26-git-f43916e217-essentials_build-www.gyan.dev` build with Python
3.11.0. The local GPL-enabled tool build is not distributed with the project.

The audit was produced on branch `master` from baseline
`83f83b9aeac4728a253a03ba9910caef433fe08e`; Phase 1 changes were intentionally
still uncommitted at capture time.

## Declared limits

- Remux/transcode repair is unsupported; affected sources are explicitly
  refused.
- Active external-tool cancellation is deferred; timeout and resumable
  stage-boundary interruption are implemented.
- Packet continuity uses bounded early/middle/late sampling, not an exhaustive
  full-file scan.

These limits do not block the Phase 1 success definition. Phase 2 can consume
the stable corpus boundary without reopening inspection, selection,
normalization, addressing, chunking, cache, resume, or integrity decisions.

Machine-readable details, including negative cases and the complete evidence
inventory, are in `phase-1-completion.json`.
