# Phase 1 edge-media policy qualification

Status: **PASSED**

| Fixture | Decode | Packets | Video outcome | Result |
|---|---|---|---|---|
| `damaged-truncated.mp4` | failed | valid | `refused` (video decode or timestamp qualification failed) | PASS |
| `non-square-pixels.mp4` | valid | valid | `available` (none) | PASS |
| `rotation-90.mp4` | valid | valid | `available` (none) | PASS |
| `unsupported-pixel-format.mp4` | valid | valid | `refused` (unsupported pixel format: yuv444p) | PASS |
| `unusual-time-base.mp4` | valid | valid | `available` (none) | PASS |
| `variable-frame-rate.mp4` | valid | valid | `available` (none) | PASS |

VFR, rotation, pixel aspect, and supported unusual time bases remain source-passthrough metadata. Unsupported pixel formats and failed decode/timestamp qualification are explicitly refused. The truncated fixture retains structurally continuous container packet timestamps, while decoded-output qualification independently detects the damaged payload and prevents access.

An independent second generation matched all six SHA-256 values.

Machine-readable evidence is in `phase-1-edge-media-policy-qualification.json`.
