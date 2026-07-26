# Phase 0.5 controlled proof corpus

The canonical family is the fictional **Riverton Evening Access Forum**,
fixture ID `ratiocinatus-proof-riverton-evening-access-v1`, fixture version
1.0.0. It is source and evaluation material, not an analytical result.

The corpus lives in `tests/fixtures/riverton_evening_access_v1`:

- `script/` contains the exact 68-line script, evidence packet, speakers, and
  stable line definitions.
- `generation/` contains policies, 68 independently synthesized raw lines,
  line-audio hashes, synthesis invocations, and four generated visual states.
- `media/{clean,naturalized,adversarial}/` contains an H.264/AAC MP4, a
  lossless stereo FLAC mix, and three isolated mono FLAC stems.
- `schedules/` contains line, overlap, perturbation, and visual-state timing in
  integer microseconds.
- `reference/` is hidden evaluation material. Ordinary analysis must never
  receive it.
- `manifests/` records fixture identity, licenses, generation environments,
  exact commands, fonts, voices, and hashes.
- `checksums/sha256sums.txt` freezes every package file except the generated
  validation reports and the checksum inventory itself.

## Generation

Generation uses `kokoro-onnx` 0.4.9, Kokoro-82M v1.0 FP16, stock voices
`am_adam`, `af_bella`, and `af_sarah`, CPUExecutionProvider, and no voice
cloning. Model/runtime files live under ignored `.tools/tts` and are not
bundled. FFmpeg and Pillow assemble the media.

```console
python -m ratiocinatus.cli fixture generate clean --dry-run
python -m ratiocinatus.cli fixture generate clean
python -m ratiocinatus.cli fixture generate naturalized
python -m ratiocinatus.cli fixture generate adversarial
```

Existing canonical variants are refused unless `--replace` is explicit.
Canonical-media hashes in `fixture_manifest.json` then force a controlled
identity review: waveform changes cannot pass validation merely by rewriting
the general checksum inventory.

Generation is classified as configuration-equivalent. Frozen media hashes are
authoritative. A tested L002 regeneration was hash-identical on the original
environment, but cross-runtime byte identity is not promised.

## Inspection and validation

```console
python -m ratiocinatus.cli --json fixture list
python -m ratiocinatus.cli --json fixture inspect
python -m ratiocinatus.cli --json fixture validate
python -m ratiocinatus.cli fixture checksum
python -m ratiocinatus.cli --json fixture license-report
python -m ratiocinatus.cli fixture regenerate-line clean L002
python -m ratiocinatus.cli fixture export riverton-v1.zip
python -m ratiocinatus.cli fixture compare PATH_A PATH_B
```

Validation checks contracts, stable line order, speaker/evidence references,
spoken-number landmarks, participant names, version-bound script/voice/license
hashes, hidden references, candidate-call support, required licenses, media
presence/properties/durations, schedules, overlap references, perturbations,
the single adversarial visual mismatch, canonical-media identity, and package
checksums.

## Licensing

The project-authored script, evidence, graphics, code, and generated package are
distributed under Apache-2.0. Third-party tools, model weights, stock voices,
and fonts retain the separately recorded upstream terms. Kokoro-82M stock model/voices are recorded as Apache-2.0,
kokoro-onnx as MIT, Pillow as MIT-CMU, and the installed eSpeak NG and FFmpeg
generation tools as GPL builds. No tool or model binary is bundled.

## Boundaries

No transcription, diarization, speaker recognition, discourse extraction,
argument reconstruction, adjudication, factual verification, scoring, review
workflow, or analytical overlay is implemented here. Hidden annotations are
conservative evaluation references, not mandatory future conclusions.

