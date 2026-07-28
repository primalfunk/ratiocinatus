# Phase 2 semantic VAD controlled evaluation

Status: **PASSED**

| Variant | Precision | Recall | F1 | Mean boundary error (ms) |
|---|---:|---:|---:|---:|
| `clean` | 0.9996 | 0.8972 | 0.9456 | 2608.2 |
| `naturalized` | 0.9997 | 0.8956 | 0.9448 | 2697.2 |
| `adversarial` | 0.9998 | 0.8953 | 0.9447 | 2711.1 |

The speech-free control contains silence, a 440 Hz tone, and deterministic broadband noise. Its semantic VAD output was 0 microseconds of probable speech and 0 microseconds uncertain.

These are duration-weighted controlled-fixture measurements. They do not establish general-corpus performance. Hidden analytical references were not read.
