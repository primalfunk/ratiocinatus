# Ratiocinatus

> The argument, reckoned from the record.

Ratiocinatus is a local-first system for building traceable, evidence-backed
analysis of recorded reasoning. Its long-term purpose is to connect preserved
audiovisual evidence to explicit interpretation, adjudication, review, and
presentation without collapsing those stages into opaque model prose.

The project is currently at **application version 0.4.0**, with Phases 0
through 5 complete. It provides the evidentiary kernel, controlled audiovisual
proof corpus, local ingestion and speech-evidence providers, canonical
transcripts, participant-speech evidence, speaker-attributed utterances, and
source-grounded discourse-act construction. It does **not** adjudicate whether
an argument is sound, infer speaker intent or credibility, score participants,
or treat machine analysis as established fact.

## Current status

| Area | Available now |
|---|---|
| Evidentiary kernel | Strict contracts, canonical JSON, stable identifiers, source registration, immutable artifact envelopes, append-only provenance, integrity validation, export, and deterministic replay |
| Provider boundaries | Production local media, speech-activity, and transcription observation providers; analytical provider output remains bounded proposal evidence and synthetic evidence stays visibly classified |
| Workspace CLI | Initialization, inspection, source and artifact operations, provider inspection, validation, reporting, export, configuration inspection, and replay |
| Phase 1 ingestion | Complete: portable corpus assembly, strict versioning, all-stage recovery, normalized audio, timestamp-addressed video, packet continuity, virtual/materialized chunks, edge-media fixtures, and two-hour qualification |
| Phase 2 speech evidence | Complete: mapped activity and Whisper observations, canonical assembly, corrected successors, loss-declared subtitles, strict evaluation, stage-local recovery, typed negative proofs, and two-hour chunk-boundary qualification |
| Phase 3 participant speech | Complete (18/18 gates): deterministic diarization, provisional clustering, protected embeddings, scoped identities, bounded voice enrollment and comparison, reviewed identity views, participant transcripts/subtitles, evaluation, recovery, and long-recording qualification |
| Phase 4 utterance corpus | Complete (19/19 gates): source-addressed utterances, structural analysis, interruptions and turn repair, quotation evidence, review and propagation, bounded context windows, portable export, recovery, evaluation, and long-recording qualification |
| Phase 5 discourse acts | Complete (24/24 gates): conservative multi-label act proposals, question-answer and argument relations, lexical/example/quotation and procedural-state construction, append-only review, selective propagation, evaluation, portable export, recovery, and long-recording qualification |
| Controlled proof corpus | Three-speaker clean, naturalized, and adversarial audiovisual variants with stems, exact schedules, hidden references, licenses, and frozen hashes |
| Automated verification | 326 tests, controlled negative cases, 407 runtime JSON-schema exports plus 20 fixture schemas, package build, fixture validation, and proof replay |
| Judgment and scoring | Not implemented; later phases must preserve the distinction between evidence, interpretation, adjudication, and presentation |

Compatibility versions are exposed by the CLI:

```console
ratiocinatus --json version
```

Current values are application `0.4.0`, core contracts `0.1.0`, canonical
serialization `canonical-json-1`, workspace format `0.1.0`, and proof fixture
format `1.0.0`.

## Repository prerequisites

- Python 3.11 or newer
- Git LFS for the checked-in controlled proof audio and video
- No network, GPU, production model, or commercial service is needed for the
  ordinary test suite
- FFmpeg and FFprobe are required for Phase 1 ingestion and qualification;
  the optional Silero VAD toolchain is needed for semantic speech activity;
  the optional OpenAI Whisper toolchain and separately acquired checkpoint are
  needed for local transcription observations;
  the optional Kokoro toolchain is needed only to regenerate fixture media

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
# Add the pinned local semantic speech-activity provider when needed:
python -m pip install -e ".[vad]"
# Add the pinned local transcription runtime when needed:
python -m pip install -e ".[transcription]"
python -m pytest -q
ratiocinatus --json version
```
The transcription provider never downloads a model during evidence processing.
Acquire the official `small` checkpoint separately before use, then verify its
SHA-256 is
`9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794`.
The upstream package can populate its standard cache explicitly with:

```console
python -c "import whisper; whisper.load_model('small', device='cpu')"
```

Use `speech-provider inspect local.openai_whisper` to confirm the qualified
package, checkpoint, device, and runtime fingerprint before transcription.

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

## Canonical transcript assembly

After `speech transcribe` completes, promote validated observations into an
immutable original-machine transcript version:

```console
ratiocinatus --json speech assemble CORPUS_ROOT TRANSCRIPTION_RUN PHASE2_OUTPUT
ratiocinatus --json speech inspect-assembly ASSEMBLY_ROOT
```

The assembly keeps source and normalized timing, Phase 1 stream/chunk lineage,
provider candidates, confidence origins, and machine-readable review or
blocking regions. Canonical promotion makes text addressable; it does not make
model output factually authoritative.
## Transcript corrections

Import a strict correction batch and inspect the immutable successor revision:

```console
ratiocinatus --json speech correct ASSEMBLY_ROOT CORRECTION_BATCH PHASE2_OUTPUT
ratiocinatus --json speech inspect-revision REVISION_ROOT
ratiocinatus --json speech render-transcript REVISION_ROOT --view current
ratiocinatus --json speech correction-history REVISION_ROOT
```

Corrections never rewrite the machine assembly. Human and automated-process
actors remain distinct, prior values must match exactly, and original/current,
difference, and history views are stored as integrity-checked artifacts.

## Subtitle exports

Export either an original-machine or corrected transcript view as deterministic
WebVTT and SRT presentation derivatives:

```console
ratiocinatus --json speech export-subtitles ASSEMBLY_ROOT PHASE2_OUTPUT
ratiocinatus --json speech export-subtitles ASSEMBLY_ROOT PHASE2_OUTPUT --revision-root REVISION_ROOT --view current
ratiocinatus --json speech validate-subtitles SUBTITLE_EXPORT_ROOT
```

Each export includes a sealed companion manifest and validation report carrying
its transcript version, source references, low-confidence regions, rounding and
segmentation policy, file hashes, and declared losses. Subtitle text is not a
replacement for the canonical evidence record.

## Transcript evaluation

Evaluate a declared immutable transcript view against a strict, independently
prepared, source-addressed reference:

```console
ratiocinatus --json speech evaluate-transcript ASSEMBLY_ROOT REFERENCE_JSON PHASE2_OUTPUT
ratiocinatus --json speech evaluate-transcript ASSEMBLY_ROOT REFERENCE_JSON PHASE2_OUTPUT --revision-root REVISION_ROOT --view current --subtitle-export-root SUBTITLE_EXPORT_ROOT
ratiocinatus --json speech validate-evaluation EVALUATION_ROOT
```

Reports preserve aggregate and represented-stratum WER/CER, edit composition,
segment and optional word timing, descriptive confidence reliability, optional
candidate selection, subtitle validity, correction impact, reference hashes,
source mapping, and explicit unavailable metrics. Controlled results are not
general transcription-quality claims.
## Phase 2 recovery

Repair transcription report metadata only after validating its retained request,
normalized response, and raw provider evidence:

```console
ratiocinatus --json speech repair-transcription-report TRANSCRIPTION_RUN_ROOT
ratiocinatus --json speech validate-recovery RECOVERY_REPORT_ROOT
```

Corrupt deterministic stage outputs are moved into a sibling `invalid/`
directory and rebuilt only from validated immediate parents. Recovery records
preserve the detected failure and quarantine location, and state explicitly
whether a provider was invoked. Phase 1 and valid transcription evidence remain
outside downstream invalidation scope.
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
the phase guides under [`docs/`](docs/) for implemented contracts, boundaries, and
qualification evidence.

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
- [Phase 1 ingestion guide and implementation status](docs/PHASE_1.md)
- [Phase 2 transcription and speech-evidence status](docs/PHASE_2.md)
- [Phase 2 speech-activity baseline qualification](reports/phase-2-speech-activity-baseline-qualification.md)
- [Phase 2 semantic VAD controlled evaluation](reports/phase-2-semantic-vad-qualification.md)
- [Phase 2 initial transcription-provider qualification](reports/phase-2-transcription-provider-qualification.md)
- [Phase 2 canonical transcript-assembly qualification](reports/phase-2-transcript-assembly-qualification.md)
- [Phase 2 append-only transcript-correction qualification](reports/phase-2-transcript-correction-qualification.md)
- [Phase 2 subtitle-export qualification](reports/phase-2-subtitle-export-qualification.md)
- [Phase 2 controlled transcript-evaluation qualification](reports/phase-2-transcript-evaluation-qualification.md)
- [Phase 2 cache, resume, and recovery qualification](reports/phase-2-recovery-qualification.md)
- [Phase 2 long-recording qualification](reports/phase-2-long-recording-qualification.md)
- [Phase 2 typed negative-proof qualification](reports/phase-2-negative-proofs.md)
- [Phase 2 completion report](reports/phase-2-completion.md)
- [Phase 3 diarization and participant-identity status](docs/PHASE_3.md)
- [Phase 3 contract and evidence-boundary qualification](reports/phase-3-foundation.md)
- [Phase 3 deterministic diarization evidence-kernel qualification](reports/phase-3-diarization-kernel.md)
- [Phase 3 overlap and uncertain-boundary qualification](reports/phase-3-overlap-boundary-qualification.md)
- [Phase 3 provisional acoustic-clustering qualification](reports/phase-3-provisional-clustering-qualification.md)
- [Phase 3 controlled clustering-evaluation qualification](reports/phase-3-controlled-clustering-evaluation.md)
- [Phase 3 scoped participant-identity foundation qualification](reports/phase-3-identity-foundation.md)
- [Phase 3 bounded reference-voice enrollment qualification](reports/phase-3-reference-enrollment-qualification.md)
- [Phase 3 compatible reference-voice comparison qualification](reports/phase-3-reference-comparison-qualification.md)
- [Phase 3 comparison-backed identity-hypothesis qualification](reports/phase-3-comparison-hypothesis-integration-qualification.md)
- [Phase 3 append-only manual identity-binding qualification](reports/phase-3-manual-identity-binding-qualification.md)
- [Phase 3 reviewed identity-view assembly qualification](reports/phase-3-identity-view-assembly-qualification.md)
- [Phase 3 speaker-labeled transcript integration qualification](reports/phase-3-speaker-transcript-integration-qualification.md)
- [Phase 3 participant-labeled subtitle qualification](reports/phase-3-participant-subtitle-qualification.md)
- [Phase 3 cache, resume, and recovery qualification](reports/phase-3-cache-recovery-qualification.md)
- [Phase 3 controlled temporal-diarization evaluation](reports/phase-3-controlled-diarization-evaluation.md)
- [Phase 3 integrity and completion-reporting qualification](reports/phase-3-integrity-completion-reporting-qualification.md)
- [Current Phase 3 completion report](reports/phase-3-completion.md)
- [Phase 4 speaker-attributed utterance corpus guide](docs/PHASE_4.md)
- [Phase 4 completion report](reports/phase-4-completion.md)
- [Phase 5 discourse-act construction guide](docs/PHASE_5.md)
- [Phase 5 completion report](reports/phase-5-completion-report.md)
- [Phase 5 long-recording qualification](reports/phase-5-long-recording-qualification.md)
- [Testing and baseline policy](docs/TESTING.md)
- [Phase 0.5 completion report](reports/phase-05-completion.md)
- [Phase 1 normalization qualification](reports/phase-1-normalization-qualification.md)
- [Phase 1 video-access qualification](reports/phase-1-video-access-qualification.md)
- [Phase 1 corpus and resume qualification](reports/phase-1-corpus-resume-qualification.md)
- [Phase 1 long-recording and chunk-materialization qualification](reports/phase-1-long-recording-qualification.md)
- [Phase 1 all-stage resume and recovery qualification](reports/phase-1-resume-recovery-qualification.md)
- [Phase 1 edge-media policy qualification](reports/phase-1-edge-media-policy-qualification.md)
- [Phase 1 packet-continuity qualification](reports/phase-1-packet-continuity-qualification.md)
- [Phase 1 completion report](reports/phase-1-completion.md)
- [Architecture decision records](docs/architecture/decisions/)
- [Archived implementation work orders](docs/work_orders/)

## Development policy

Changes to authoritative contracts, canonical serialization, fixture source
text, voice assignments, schedules, media, or hidden references must include
corresponding schemas, tests, validation evidence, and version-impact review.
Do not update a checksum or baseline merely to silence an unexplained failure.
Do not add production models, datasets, found media, cloned voices, secrets, or
provider caches to the repository.

Qualification evidence under `reports/`, exported contracts under `schemas/`,
and the declared Git LFS proof corpus are intentional repository assets. Local
workspaces, downloaded models, provider caches, credentials, private keys,
machine-specific configuration, and generated build/test output are ignored.
Before publishing from a fresh clone or worktree, review the staged file list
and run a secret scanner appropriate to the hosting platform; `.gitignore`
reduces accidental additions but does not remove secrets already committed to
Git history.

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
