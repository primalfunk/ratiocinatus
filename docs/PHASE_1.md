# Phase 1: Audiovisual ingestion and source addressing

Status: Complete  
Target application version: 0.3.0  
Work order: [`work_orders/phase_01.txt`](work_orders/phase_01.txt)

Phase 1 converts an immutable registered audiovisual source into a validated,
addressable, resumable corpus. It produces no transcript, speaker inference,
discourse interpretation, judgment, score, or analytical overlay.

## Implemented foundation

The inspection, selection, and decode-qualification foundation now provides:

- strict, closed Phase 1 inspection and stream-inventory contracts;
- content-grounded file fingerprints and source-local stream identities;
- explicit FFprobe discovery or configured executable selection;
- argument-array execution without shell interpolation;
- bounded execution time;
- FFprobe executable hash, version, build configuration, arguments, exit code,
  standard error, raw JSON, and raw JSON hash;
- exact decimal-to-integer-microsecond conversion;
- container, chapter, program, tag, disposition, video, audio, subtitle, data,
  attachment, and unknown-stream representation;
- `media inspect` and `media streams` commands;
- JSON and human-readable output through the existing CLI;
- generated JSON Schemas for the new contracts; and
- offline parser and negative tests;
- versioned deterministic stream-selection policy and candidate assessments;
- explicit audio and video overrides subject to validation;
- default-stream preference, index tie-breaking, and attached-picture exclusion;
- valid audio-only selection and typed missing-audio failure;
- bounded FFmpeg early, middle, and late probes for every selected stream;
- optional explicit full-file decode qualification;
- duration plausibility and before/after source-fingerprint checks; and
- `media select` and `media qualify` commands;
- explicit source-media and normalized-corpus time domains;
- signed source timestamps and non-negative normalized timestamps;
- exact point and interval mappings with clipping and discontinuity classes;
- chunk-local-to-source interval recovery;
- deterministic virtual 10-minute chunks with five-second overlap;
- stable configuration-sensitive plan and chunk identities;
- explicit earliest-chunk overlap ownership and coverage multiplicity; and
- `media timeline`, `media map-time`, and `ingest plan` commands;
- lossless 16 kHz mono signed-16 FLAC audio normalization;
- explicit unit-total-gain downmix and recorded FFmpeg transformation;
- derivative hash, decode, duration, sample-rate, channel, format, and sample-count checks;
- atomic partial-directory commit with failed-attempt preservation;
- content-, selection-, configuration-, provider-, tool-, and format-addressed cache keys;
- validated cache hit, corruption rebuild, policy invalidation, refuse, and bypass behavior; and
- `derivative normalize-audio`, `derivative list`, `derivative inspect`, `cache inspect`, and `cache validate` commands;
- qualified source-passthrough video access without persistent transcoding;
- explicit VFR, rotation, pixel-aspect, damaged-timestamp, and unsupported-format policy;
- nearest-frame lookup by normalized timestamp with bounded preroll filtering;
- half-open frame timestamp indexes over normalized intervals;
- source/corpus timestamp, rounding, invocation, dimension, and hash evidence for every extraction; and
- `video plan`, `video frame`, and `video frames` commands;
- FFmpeg progress-based proof that every successful decode probe produced frames or audio time;
- distinct refused video plans for invalid time bases, unsupported pixel formats, and failed decode/timestamp probes;
- source-passthrough preservation of real VFR, 90-degree rotation, non-square pixels, and a 1/1,000,000 time base; and
- reproducible Apache-2.0 technical edge fixtures with exact commands and hashes;
- portable corpus layout with relative paths and independently copied source/audio evidence;
- closed audiovisual-corpus, ingestion, checkpoint, integrity, and normalized-source contracts;
- atomic stage and manifest commits with source/configuration-sensitive ingestion identity;
- committed-stage validation and reuse across interruption;
- invalid-stage preservation before rebuilding;
- independently loadable, exportable, and substitution-detecting corpus validation;
- machine- and human-readable corpus integrity and normalized-source reports; and
- `ingest run`, `ingest resume`, `ingest status`, `ingest validate`, `corpus list`, `corpus inspect`, `corpus validate`, and `corpus export` commands;
- qualified interruption and resume after all 11 persisted stages;
- stage-specific validation of referenced normalized audio before reuse;
- orphan atomic-partial preservation as failed-attempt evidence;
- committed derivative corruption rebuild, changed-source rejection, incompatible-configuration rejection, and chunk-policy isolation with unaffected audio reuse;
- explicit normalized-audio chunk materialization only when a provider, export, or qualification requires a file;
- complete derivative, corpus/source interval, command, tool, duration, format, hash, size, and integrity lineage;
- reason-, interval-, derivative-, policy-, provider-, and tool-sensitive materialization cache identities;
- validated cache hit, corruption quarantine/rebuild, refuse, and no-overwrite bypass behavior;
- bounded early, middle, and late packet-timestamp probes for selected streams;
- packet DTS regression and gap detection with timeline discontinuity propagation;
- strict rejection and recovery of unsupported persisted Phase 1 versions;
- recorded recovery from write denial, full disk, and external-tool mutation; and
- `media packets`, `chunk list`, and `chunk materialize` commands.

The provider has been exercised against all three canonical Riverton MP4s. Each
selected stream 1 as authoritative audio and stream 0 as video, and all six
bounded probes passed. The clean FLAC mix also passed its three audio probes as
a valid audio-only source. These runs use only technical media and do not read
hidden analytical references.

## Current limitations

Representative decode and packet qualification are bounded by default rather
than exhaustive full-file scans. Remux/transcode remediation and cooperative
cancellation of a running external-tool process remain unsupported; timeout and
resumable stage-boundary interruption are implemented. Passthrough access
refuses damaged payloads and unsupported pixel formats instead of silently
repairing them.

The local GPL-enabled FFmpeg installation is an external development tool. It
is not bundled with Ratiocinatus.

## Long-recording qualification

The reproducible Apache-2.0 synthetic source generator produced a 7,201-second
A/V source; an independent second generation produced the same byte hash (SHA-256 `a7a06422d18fb729ddb6eb1477c34ca52142c6c2f726bfb850dfd91f9ba2464b`).
The qualification passed with 13 default chunks, complete overlap ownership,
exact start/middle/end mappings, an intentional interruption after audio
normalization, committed-stage reuse on resume, and cache hits for validated
start/middle/end materializations. End-to-end processing took 7.66981 seconds
on the qualification host; Python allocator peak was 2,495,017 bytes. See the
[machine-readable report](../reports/phase-1-long-recording-qualification.json)
and [human report](../reports/phase-1-long-recording-qualification.md).

Reproduce it with FFmpeg available:

```console
python scripts/generate_phase1_long_fixture.py .qualification/phase1-long
set PYTHONPATH=src
python scripts/qualify_phase1_long.py .qualification/phase1-long/phase1-long-synthetic.avi .qualification/phase1-long-workspace .qualification/phase1-long-materialized reports/phase-1-long-recording-qualification.json reports/phase-1-long-recording-qualification.md
```

## Resume and edge-media qualification

The resume matrix passed after every persisted stage from `source_verified`
through `complete`. Recovery also passed for orphan partial output, committed
derivative substitution, changed source content, changed chunk policy, an
incompatible resume configuration, write denial, full disk, unsupported persisted
versions, and external-tool version mutation. See the [resume report](../reports/phase-1-resume-recovery-qualification.md)
and its [machine-readable evidence](../reports/phase-1-resume-recovery-qualification.json).

Six independently reproducible Apache-2.0 edge fixtures passed their declared
outcomes. VFR, 90-degree rotation, non-square pixels, and a valid unusual time
base remained available and untransformed. `yuv444p` and a truncated source with
no late decoded frames produced explicit refused plans. See the [edge-media report](../reports/phase-1-edge-media-policy-qualification.md)
and its [machine-readable generation and result evidence](../reports/phase-1-edge-media-policy-qualification.json).

Reproduce both matrices with FFmpeg available:

```console
python scripts/generate_phase1_edge_fixtures.py .qualification/phase1-edge
python scripts/generate_phase1_edge_fixtures.py .qualification/phase1-edge-repeat
set PYTHONPATH=src
python scripts/qualify_phase1_edge_fixtures.py .qualification/phase1-edge .qualification/phase1-edge-repeat reports/phase-1-edge-media-policy-qualification.json reports/phase-1-edge-media-policy-qualification.md
python scripts/qualify_phase1_resume.py .qualification/phase1-resume reports/phase-1-resume-recovery-qualification.json reports/phase-1-resume-recovery-qualification.md
python scripts/qualify_phase1_packets.py tests/fixtures/riverton_evening_access_v1/media reports/phase-1-packet-continuity-qualification.json reports/phase-1-packet-continuity-qualification.md
```

## Packet continuity and exit audit

All 18 selected-stream packet probes across the three canonical MP4s passed
with monotonic DTS and no detected discontinuities. Synthetic analysis tests
cover missing timestamps, DTS regression, and large gaps. The truncated edge
fixture demonstrates why packet structure and decoded-output integrity remain
complementary gates. See the [packet report](../reports/phase-1-packet-continuity-qualification.md).

The final audit passed 77 tests, Phase 0 deterministic proof, Phase 0.5 media
integrity, 79 Phase 0/1 schema exports, all-stage recovery, and the two-hour
qualification.

## Phase 2 handoff

Phase 1 is complete at application version 0.3.0. Later phases may consume the
portable corpus, normalized audio, timestamp-addressed video, timelines, and
stable chunks without changing source evidence. Transcript, speaker,
proposition, adjudication, and scoring contracts remain intentionally outside
this phase. See the [completion report](../reports/phase-1-completion.md) and
[machine-readable exit audit](../reports/phase-1-completion.json).