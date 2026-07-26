# Phase 0.5 completion report

- Date: 2026-07-26
- Status: complete (corpus generated, machine-qualified, owner-auditioned, and licensed under Apache-2.0)
- Application version: 0.2.0
- Fixture contract version: 0.1.0
- Fixture format/version: 1.0.0
- Fixture ID: `ratiocinatus-proof-riverton-evening-access-v1`
- Starting state: Phase 0 kernel at application 0.1.0; Phase 0 worktree
  uncommitted; no controlled audiovisual corpus
- Final state: 68-line controlled corpus, three generated variants, schedules,
  hidden references, manifests, checksums, reports, 20 fixture schemas, CLI,
  offline mock TTS, and 30 passing tests

## Delivered media

| Variant | Duration | Lines | Overlaps | Acoustic perturbations | Visual states | MP4 bytes | MP4 SHA-256 |
|---|---:|---:|---:|---:|---:|---:|---|
| clean | 567.784667 s | 68 | 0 | 0 | 137 | 14,448,161 | `1485faf0c8fa17ded5f17f3c4d1fa882757d65fff44393d3cecc2ad6b1c3266a` |
| naturalized | 545.858667 s | 68 | 2 | 0 | 136 | 14,301,751 | `5a6797523d0566d754a30ca8aa290bb26f19a94ac372c31f81b1b6e06113a780` |
| adversarial | 544.466667 s | 68 | 3 | 4, plus one visual mismatch | 136 | 14,264,371 | `08ab6072bd057c667691b96c0c889adf843de7b57d2d8e6d45f4be29fd9d3bd2` |

Each variant has a 48 kHz stereo FLAC mix and three isolated 48 kHz mono FLAC
stems. Videos are 1920ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â1080, H.264, fixed 30 fps, with 48 kHz stereo AAC and no
DRM. Total frozen fixture size is approximately 230 MiB. The checksum inventory
contains more than 126 entries, including all canonical media and 68 raw PCM
line artifacts.

## Script and references

Complete: all 68 stable lines were extracted verbatim from the archived work
order, each with a text SHA-256. Eight fictional evidence items, three fictional
participants, names, quantities, and required spoken-number landmarks validate.

Hidden reference annotations: 5 discourse acts, 4 propositions, 3 argument
relations, 3 obligations, 4 candidate calls, 4 expected non-calls, and 3
ambiguities (26 total). Candidate calls and non-calls are separate, all
references resolve, and no overall winner or score is encoded.

## TTS, visual, and generation environment

- Engine: kokoro-onnx 0.4.9 (MIT)
- Model: hexgrad/Kokoro-82M v1.0 FP16 (Apache-2.0)
- Model SHA-256:
  `c1610a859f3bdea01107e73e50100685af38fff88f5cd8e5c56df109ec880204`
- Voice bundle SHA-256:
  `bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d`
- Moderator: `am_adam`, speed 0.96
- Participant A: `af_bella`, speed 1.00
- Participant B: `af_sarah`, speed 0.94
- Language/source rate: en-US / 24 kHz; assembly rate: 48 kHz
- Execution: local CPU, ONNX CPUExecutionProvider, no GPU, network, voice
  cloning, imitation, biometric input, music, footage, or photographic assets
- Visuals: geometric avatars and text generated with Pillow 12.1.0; exact Arial
  input-font hashes are preserved in each generation manifest
- Assembly: installed GPL-enabled FFmpeg 2024-09-26 build using libx264 and AAC;
  exact commands/configuration are preserved
- Measured mixes: -20.7 LUFS integrated; -3.2 dBTP clean/naturalized;
  -3.1 dBTP adversarial; 4.1ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Å“4.2 LU loudness range

Variant A generation took 247.816 seconds including the first 68 line
syntheses. Variants B and C reused frozen line audio and took 63.524 and 64.286
seconds respectively. Peak memory was not measured reliably on this Windows
run. GPU use was false.

## Authorized difficulty

Complete: clean delivery; controlled variable pauses; canonical self-correction;
two naturalized overlaps; longer adversarial overlaps; L037/L038 interruption;
L039 pause; L063 breath; initially unhighlighted L056; low-volume L037;
broadband-noise L053; clipped L058 onset; closer but distinct participant
voices; ambiguous L061-L063; and one declared L050 active-speaker mismatch.
The optional spoken "Well" before L020 was not used, preserving canonical words.
## Licensing

Classification: redistributable under Apache-2.0 with recorded notices.
Project-authored code, script, evidence, documentation, generated graphics, and
fixture media default to Apache-2.0. Generation dependencies and stock
voice/model terms remain separately recorded; model and tool binaries are not
bundled. No required component has an unknown license in the validated package.
## Tests, qualification, and negative cases

Automated result: `30 passed`. Ordinary tests are offline and use a
deterministic symbolic, non-speech TTS mock.

Qualification passed:

- all three variants generated from a clean fixture definition;
- all media opened through FFprobe;
- all contracts, references, timing, properties, licenses, and hashes passed;
- a 230,429,046-byte ZIP export (`cbf37db66c9618cafa2a799a7b273557f068af1f1a98cc41eddede9605d9d270`) validated after extraction and compared equal with zero
  differences;
- destructive export overwrite was refused;
- L002 controlled regeneration was hash-identical:
  `658c97c17900e5d0df95eac5e7b0f24e7c3cd18338e445326d7b58b636d1f340`.

Controlled tests reject or detect duplicate/absent lines, unknown speakers,
unchanged-version script and voice changes, out-of-bounds intervals, unknown
overlap lines, unknown reference evidence, unsupported candidate calls, unknown
required licenses, cloned-voice flags, untracked assets, checksum/media identity
mismatches, failed line synthesis, and destructive export overwrite.

## Reproducibility and deviations

Classification: configuration-equivalent generation with content-hash-frozen
canonical media. Same-environment L002 regeneration happened to be
hash-identical; cross-version ONNX/phonemizer/codec identity is not promised.
Any canonical media change fails against `fixture_manifest.json` until an
explicit versioned replacement is approved.

The generated MP4 uses the requested H.264/AAC profile. The available FFmpeg
binary is GPL-enabled rather than an LGPL-only build; it is a local generation
tool and is not redistributed. The project design document was not silently
edited; the required revision is proposed separately.

## Owner audition and readiness

On 2026-07-26, the project owner listened to the clean, naturalized, and
adversarial files and accepted them as adequate for initial use. This satisfies
the pending human audiovisual gate. Apache-2.0 was selected as the project and
fixture default license.

Phase 0.5 is complete and the corpus is ready for Phase 1. The acceptance is
fit-for-purpose, not a claim that the fixture is perfect or that later systems
are accurate. No production transcription, diarization, analysis, adjudication,
scoring, or analytical rendering was implemented or claimed.