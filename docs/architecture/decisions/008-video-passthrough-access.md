# ADR 008: Video passthrough, remux, or transcode policy

- Status: Accepted for Phase 1
- Date: 2026-07-26

## Context

Later phases need timestamp-addressable video evidence, but automatic video
transcoding is expensive and can alter pixels, timing, color, aspect ratio, or
display orientation. The qualified Phase 0.5 sources already use broadly
supported H.264 video with stable timestamps.

## Decision

Version 1 defaults to `source_passthrough_timestamp_access`.

The selected source video remains the authoritative working video. No remux or
transcode is created when inspection and early/middle/late decode qualification
succeed. The access plan records:

- selected stream and content-grounded source identity;
- time base and average and real frame-rate declarations;
- constant- or variable-frame-rate status;
- dimensions and pixel format;
- sample and display aspect ratios;
- rotation metadata;
- seek-qualification state; and
- the complete no-transform policy.

Frame requests use normalized corpus timestamps. FFprobe locates the nearest
declared frame timestamp within a bounded search window; FFmpeg extracts that
timestamp from the selected stream. The result records both source and corpus
timestamps, rounding error, file hash, dimensions, and both tool invocations.

Extraction disables FFmpeg autorotation. Encoded pixels are preserved at their
encoded dimensions without cropping, resizing, caption burn-in, speed change,
or aspect-ratio rescaling. Rotation and pixel-aspect metadata remain explicit
instructions to later display consumers.

Audio-only sources produce a valid `not_applicable` video plan. Unsupported
pixel formats or damaged timestamps are refused rather than silently
transcoded. Remux and transcode may be added by a later versioned policy when
qualification evidence justifies them.

## Alternatives considered

- Always transcode: simplifies downstream decoding but increases storage and
  risks unnecessary evidentiary changes.
- Always remux: can improve seeking for some containers but rewrites timestamps
  and offers no benefit for already-qualified sources.
- Frame-number addressing: unstable for variable frame rate, edit lists, and
  different decoder behavior.
- Rely on implicit autorotation: makes extracted pixels depend on tool defaults
  rather than recorded policy.

## Consequences

- Qualified source video consumes no additional persistent storage.
- Every extracted frame remains traceable to an explicit timestamp and stream.
- Display consumers must honor recorded rotation and pixel-aspect metadata.
- Sources with genuinely damaged access behavior are rejected until a
  transformation policy is deliberately qualified.

## Reversibility

Strategy and transformation behavior are versioned policy fields. A remux or
transcode policy can create a distinct access plan and derivative without
replacing the passthrough plan.

## Qualification evidence

Controlled tests cover constant and variable frame-rate metadata, rotation,
audio-only sources, non-ASCII paths, interval timestamp enumeration, nearest
frame extraction, exact output hashing, and non-overwrite behavior. Canonical
Riverton extraction is recorded in the Phase 1 video-access qualification
report.
