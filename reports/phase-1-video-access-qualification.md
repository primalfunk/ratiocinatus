# Phase 1 video-access qualification

Status: Partial Phase 1 qualification evidence  
Date: 2026-07-26  
Policy version: 1.0.0  
Access format version: 1.0.0

## Policy exercised

The canonical video strategy is qualified source passthrough with
timestamp-authoritative access. It creates no persistent video derivative.

- full encoded frame preserved;
- no crop or resize;
- no caption burn-in;
- no speed change;
- no aspect-ratio rescaling;
- FFmpeg autorotation disabled during extraction;
- rotation and pixel-aspect metadata retained for display consumers; and
- unsupported pixel formats or damaged timestamps refused rather than silently
  transcoded.

## Riverton clean measurement

The canonical clean MP4 selected global stream 0, a fixed-rate 1920x1080 H.264
stream at 30 fps. Early, middle, and late decode probes passed before the access
plan was marked available.

A request at normalized corpus time 123,456,789 microseconds located the nearest
declared frame at 123,466,667 microseconds:

| Measurement | Result |
|---|---:|
| Timestamp difference | 9,878 µs |
| Mapping classification | rounded |
| Extracted dimensions | 1920x1080 |
| Output bytes | 190,828 |
| Output SHA-256 | `77ed3a2838e2b5d0bce0c2e6464dc62d002d4774f375f6366e0a0619e2518307` |
| Rotation metadata | none |
| Extraction and validation time | 1.029 s |

A half-open one-second interval beginning at 123,000,000 microseconds indexes
30 frame timestamps, from 123,000,000 through 123,966,667 microseconds.

## Defect found during qualification

The first implementation used a relative FFprobe read-window end. FFprobe
started decoding at the preceding keyframe, causing the window to end before
the requested timestamp and producing an incorrect 5,856,789-microsecond
selection error.

The provider now:

1. requests an absolute bounded interval end with additional seek preroll;
2. filters all returned timestamps to the requested half-open interval; and
3. chooses the minimum absolute timestamp difference.

The repeated request then located the expected adjacent 30 fps frame with a
9,878-microsecond difference.

## Controlled coverage

Tests additionally cover:

- constant and variable frame-rate declarations;
- rotation metadata without implicit pixel transformation;
- audio-only `not_applicable` plans;
- Unicode and space-containing source and output paths;
- interval frame indexing;
- exact extracted-file hashing; and
- refusal to overwrite an existing frame output.

## Boundary and limitations

Frame-number addressing is not authoritative. This slice does not remux or
transcode video, infer scenes, identify faces, infer active speakers, or produce
analytical annotations.

The passthrough policy is qualified for sources whose selected video stream
passes representative decode and timestamp access. Damaged-timestamp and
unsupported-pixel-format remediation remains unsupported pending a separate
versioned transformation policy.
