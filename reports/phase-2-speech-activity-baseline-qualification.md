# Phase 2 energy-activity baseline qualification

Status: **PASSED**

| Source | Duration (µs) | Intervals | Chunks | Cache reuse | Result |
|---|---:|---:|---:|---|---|
| `synthetic_nonsemantic_activity` | 4000000 | 3 | 1 | yes | PASS |
| `riverton_clean` | 567784000 | 3265 | 1 | yes | PASS |

The project-authored nonsemantic fixture contains silence, a tone, and deterministic noise but no speech. The baseline correctly exposes tone/noise as probable-speech false positives. This is a qualification of deterministic activity processing, coverage, ownership, persistence, and reuse—not transcription quality or semantic speech-detection accuracy.

The Riverton clean source demonstrates operation over canonical Phase 1 media without reading hidden analytical references.
