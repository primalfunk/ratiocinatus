# Ratiocinatus

> The argument, reckoned from the record.

Ratiocinatus is a local-first system for building traceable, evidence-backed
analysis of recorded reasoning. Its long-term purpose is to connect preserved
audiovisual evidence to explicit interpretation, adjudication, review, and
presentation without collapsing those stages into opaque model prose.

The project is currently at **application version 0.2.0**. It provides the
evidentiary kernel and the first controlled audiovisual proof corpus. It does
**not** yet transcribe real recordings, identify speakers, adjudicate arguments,
score participants, or produce annotated editions.

## Current status

| Area | Available now |
|---|---|
| Evidentiary kernel | Strict contracts, canonical JSON, stable identifiers, source registration, immutable artifact envelopes, append-only provenance, integrity validation, export, and deterministic replay |
| Provider boundaries | Media inspection, transcription, diarization, embeddings, structured generation, rendering, and TTS; analytical providers remain visibly synthetic mocks |
| Workspace CLI | Initialization, inspection, source and artifact operations, provider inspection, validation, reporting, export, configuration inspection, and replay |
| Controlled proof corpus | Three-speaker clean, naturalized, and adversarial audiovisual variants with stems, exact schedules, hidden references, licenses, and frozen hashes |
| Automated verification | 30 offline tests, controlled negative cases, JSON-schema exports, package build, fixture validation, and exported-package comparison |
| Production analysis | Not implemented; reserved for later phases |

Compatibility versions are exposed by the CLI:

```console
ratiocinatus --json version
```

Current values are application `0.2.0`, core contracts `0.1.0`, canonical
serialization `canonical-json-1`, workspace format `0.1.0`, and proof fixture
format `1.0.0`.

## Repository prerequisites

- Python 3.11 or newer
- Git LFS for the checked-in controlled proof audio and video
- No network, GPU, production model, or commercial service is needed for the
  ordinary test suite
- FFmpeg and the optional Kokoro toolchain are needed only to regenerate fixture
  media

Install Git LFS before cloning or checking out the corpus binaries:

```console
git lfs install
git lfs pull
```

Without LFS, the media paths contain pointer files and media validation will
correctly fail.

## Installation

Create and activate a virtual environment, then install the project and its
development dependencies:

```console
python -m venv .venv
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pytest -q
ratiocinatus --json version
```

On Windows, activate with `.venv\Scripts\Activate.ps1`. On POSIX shells, use
`source .venv/bin/activate`. The package can also be built without downloading
runtime dependencies:

```console
python -m pip wheel . --no-deps --no-build-isolation --wheel-dir dist
```

## Evidentiary-kernel proof

The deterministic Phase 0 proof can be repeated without external providers:

```console
ratiocinatus --json workspace init .demo --deterministic
ratiocinatus --json source register .demo fixtures/sources/opaque.txt
ratiocinatus --json provider list
ratiocinatus --json provider invoke .demo mock.transcription transcription proof-input
ratiocinatus --json artifact list .demo
ratiocinatus --json workspace validate .demo
ratiocinatus --json report .demo
ratiocinatus --json workspace export .demo .demo-export
```

Use the operation identifier returned by `provider invoke` to inspect and replay
the operation:

```console
ratiocinatus --json operation inspect .demo OPERATION_ID
ratiocinatus --json replay .demo OPERATION_ID
```

A controlled malformed-provider case is available as well:

```console
ratiocinatus provider invoke .demo mock.transcription transcription proof-input --mode malformed
```

CLI exit codes are `0` success, `2` invalid request, `3` missing input, `4`
unavailable or failed provider, `5` integrity or replay failure, and `10`
unexpected internal failure.

## Controlled proof corpus

The canonical fixture family is the fictional **Riverton Evening Access Forum**
(`ratiocinatus-proof-riverton-evening-access-v1`). It contains 68 scripted
lines spoken by three stock synthetic voices in a moderated civic-policy forum.
All people, organizations, evidence, and events are fictional.

| Variant | Duration | Purpose |
|---|---:|---|
| Clean | 9:27.785 | Best-case transcription, timing, diarization, and speaker-attribution source |
| Naturalized | 9:05.859 | Controlled pauses, interruption, overlaps, and an initially unhighlighted utterance |
| Adversarial | 9:04.467 | Longer overlaps, low volume, broadband noise, clipped onset, closer voices, ambiguity, and one declared visual mismatch |

Each variant includes:

- a 1920x1080, fixed-30-fps H.264/AAC MP4;
- a lossless 48 kHz stereo FLAC mix;
- isolated 48 kHz stems for the moderator and both participants;
- line, overlap, perturbation, and visual-state schedules in integer
  microseconds;
- generation and licensing manifests; and
- content hashes and independently validated hidden reference annotations.

Inspect or validate the corpus with:

```console
ratiocinatus --json fixture list
ratiocinatus --json fixture inspect
ratiocinatus --json fixture validate
ratiocinatus --json fixture license-report
```

Files under `tests/fixtures/riverton_evening_access_v1/reference/` are hidden
evaluation material. Ordinary analysis must never consume them. They represent
conservative intended interpretations and expected uncertainty, not mandatory
future conclusions.

### Regenerating fixture media

Canonical media is already checked in through Git LFS. Regeneration is optional
and was qualified on Windows using:

- `kokoro-onnx` 0.4.9;
- Apache-2.0 Kokoro-82M v1.0 stock model and voices;
- Pillow 12.1.0; and
- the recorded FFmpeg build and commands.

The model and voice files are intentionally not stored in Git. Their filenames,
source identities, expected locations, and SHA-256 hashes are recorded in
`tests/fixtures/riverton_evening_access_v1/generation/voice_policy.json`.
Install the optional dependencies in the ignored `.tools/tts` environment and
place those files under `.tools/tts/models/` before regeneration.

```console
python -m venv .tools/tts
.tools\tts\Scripts\python -m pip install ".[fixture]"
ratiocinatus fixture generate clean --dry-run
ratiocinatus fixture regenerate-line clean L002
```

Generation is classified as configuration-equivalent. Frozen hashes, not an
assumption of cross-runtime byte identity, define the canonical fixture.
Existing canonical outputs are protected from accidental overwrite.

## Architectural guarantees

The implemented foundation follows these rules:

- source evidence is preserved and addressed by content hash;
- authoritative contracts reject unknown fields and export their own schemas;
- canonical artifacts use deterministic UTF-8 JSON and SHA-256;
- timestamps entering canonical artifacts come from an injected clock;
- operations do not report success before required artifacts and provenance are
  committed;
- historical provenance is append-only;
- provider selection is explicit and provider-specific types do not become
  domain contracts;
- mock results are visibly synthetic; and
- unsupported or non-replayable work is reported explicitly rather than
  approximated as success.

See [PROJECT_DESIGN.md](PROJECT_DESIGN.md) for the long-term architecture and
[docs/PHASE_0.md](docs/PHASE_0.md) for the current kernel format.

## Repository layout

```text
src/ratiocinatus/   Runtime contracts, kernel, fixture tooling, providers, CLI
tests/              Offline tests and the canonical controlled proof corpus
schemas/            Runtime-derived JSON schemas
fixtures/           Small Phase 0 opaque and malformed fixtures
scripts/            Reproducible proof, corpus bootstrap, generation, finalization
docs/               Architecture, work orders, licensing, and operating guides
reports/             Machine- and human-readable qualification evidence
config/              Example validated configuration
```

Important documentation:

- [Phase 0 kernel guide](docs/PHASE_0.md)
- [Phase 0.5 corpus guide](docs/PHASE_05.md)
- [Testing and baseline policy](docs/TESTING.md)
- [Phase 0.5 completion report](reports/phase-05-completion.md)
- [Architecture decision records](docs/architecture/decisions/)
- [Archived implementation work orders](docs/work_orders/)

## Development policy

Changes to authoritative contracts, canonical serialization, fixture source
text, voice assignments, schedules, media, or hidden references must include
corresponding schemas, tests, validation evidence, and version-impact review.
Do not update a checksum or baseline merely to silence an unexplained failure.
Do not add production models, datasets, found media, cloned voices, secrets, or
provider caches to the repository.

Run the complete offline validation before proposing a change:

```console
python -m pytest -q
ratiocinatus --json fixture validate
python scripts/phase0_proof.py --output reports/phase-0-proof.json
```

## License

Ratiocinatus is licensed under the [Apache License, Version 2.0](LICENSE).
Apache-2.0 is the default for project-authored source, documentation, scripts,
synthetic fixtures, and generated graphics unless explicitly stated otherwise.
Third-party dependencies, model weights, stock voices, fonts, and generation
tools retain their own terms as recorded in the project and fixture license
manifests.