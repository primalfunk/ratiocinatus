# Phase 1 audio-normalization qualification

Status: Partial Phase 1 qualification evidence  
Date: 2026-07-26  
Policy version: 1.0.0  
Derivative format version: 1.0.0

## Policy exercised

- FLAC, lossless
- 16,000 Hz
- mono
- signed 16-bit sample format
- FFmpeg libswresample
- equal-weight stereo average with total gain 1.0
- compression level 5
- source metadata removed
- no denoising, silence removal, enhancement, source separation, automatic
  gain, compression, tempo change, pitch change, or loudness processing

The external tool was the local unbundled
`ffmpeg 2024-09-26-git-f43916e217` Gyan essentials build. Its executable hash,
complete version line, and build configuration are present in each derivative
manifest and cache key.

## Canonical Riverton measurements

| Variant | Selected audio | Source duration (µs) | Derivative duration (µs) | Difference (µs) | Samples | Bytes | SHA-256 | Integrity |
|---|---:|---:|---:|---:|---:|---:|---|---|
| clean | 1 | 567,784,000 | 567,786,687 | +2,687 | 9,084,587 | 9,033,659 | `b6456d31addca16c57dceaa5fc1e42f99673cecc1dfce6b369287ff9f7e4ebbd` | valid |
| naturalized | 1 | 545,859,000 | 545,877,313 | +18,313 | 8,734,037 | 9,020,221 | `80026c326d3175d9d0f8e926d20f26d522cae111fbb787575c426391f69d3c64` | valid |
| adversarial | 1 | 544,466,000 | 544,469,313 | +3,313 | 8,711,509 | 9,000,380 | `fd3c23143eb60d1d3ca72560f6f10a1f35af78ca7fe47118b215bb1149c8e0fe` | valid |

All source streams were 48 kHz stereo AAC. Every derivative independently
decoded as one 16 kHz mono signed-16 FLAC stream. Duration differences remained
within the declared 100,000-microsecond tolerance and are classified as
`rounded`, not `exact`, in derivative-to-source mappings.

The clean run completed in 0.948 seconds, naturalized in 0.931 seconds, and
adversarial in 1.019 seconds on the qualification machine. These are observed
measurements, not performance guarantees.

## Cache evidence

Each first operation produced `miss`; each identical second operation produced
`hit` after manifest, lineage, path, file hash, decode, duration, sample-rate,
channel-count, sample-format, and sample-count validation.

Observed hit-validation times were 0.434 seconds for clean, 0.419 seconds for
naturalized, and 0.401 seconds for adversarial.

Controlled tests additionally demonstrated:

- changed normalization policy creates a different cache key and miss;
- appended derivative corruption is detected by hash and rebuilt;
- the corrupt entry is preserved under `cache/audio-normalize/invalid`;
- cache-refuse policy rejects invalid reuse;
- bypassed normalization does not overwrite an existing derivative; and
- paths containing spaces are supported.

## Boundary and limitations

Only canonical MP4 mix streams were selected. Isolated Riverton stems were not
inspected or selected by normalization logic. Hidden analytical references were
not read.

This report qualifies the audio-normalization and normalized-derivative cache
slice. It is not the Phase 1 completion report. Long-recording, resume,
normalized corpus, video-access, materialized-chunk, and final reporting gates
remain open.
