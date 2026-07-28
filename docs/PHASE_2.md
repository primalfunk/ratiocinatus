# Phase 2: Transcription and temporal speech evidence

Status: Complete  
Target application version: 0.4.0  
Work order: [`work_orders/phase_02.txt`](work_orders/phase_02.txt)

Phase 2 converts a valid Phase 1 audiovisual corpus into timestamped,
confidence-bearing speech and transcript evidence.

A transcript is a fallible analytical derivative. It does not replace the
source recording, and proposed text is not an authoritative reconstruction of
speech. Every later segment and word must remain mapped to the Phase 1 corpus.

## Implemented foundation

The first Stage 1 slice provides:

- strict Phase 2 format and policy versions;
- stable corpus-, audio-, chunk-plan-, provider-, and policy-sensitive request identities;
- separate speech-activity and transcription requests;
- provider-independent speech-activity and transcription interfaces;
- explicit provider/model identity, licensing, distribution, and capability
  declarations;
- separate confidence origin, value, basis, and calibration identity;
- explicit provider-native, estimated, externally aligned, and unavailable
  timestamp origins;
- speech, non-speech, uncertain, non-lexical, interference, and provider-failure
  activity classifications;
- mapped source-media and normalized-audio speech intervals;
- Phase 1 chunk lineage and canonical overlap ownership markers;
- boundary evidence with independent uncertainty and confidence;
- provider-normalized transcript observations, alternatives, selection, and
  word observations that are not yet authoritative transcript artifacts;
- retained, hash-only, and unavailable raw-evidence states;
- explicit provider failure classes;
- bounded per-chunk FFmpeg PCM decoding with no retained PCM duplicate;
- deterministic fixed-frame RMS activity scoring and explicit semantic limits;
- optional pinned local Silero VAD with exact package/model provenance;
- provider-native, explicitly uncalibrated semantic speech probabilities;
- strict public-schedule reference and duration-weighted evaluation contracts;
- optional pinned local Whisper provider with verified checkpoint provenance;
- isolated, timeout-bounded transcription inference with retained raw JSON;
- mapped provider segment and word observations with explicit timestamp origins;
- deterministic canonical `TranscriptSegment` and timestamped `TranscriptWord`
  promotion through a separately versioned policy;
- selected Phase 1 audio-stream, source/normalized interval, speech-activity,
  chunk, provider, observation, candidate, and token lineage on canonical artifacts;
- machine-readable low-confidence regions with review and downstream-blocking
  decisions that keep text, timing, and boundary confidence separate;
- immutable original-machine transcript versions, per-artifact integrity seals,
  version digests, and persisted assembly reports;
- append-only replacement, insertion, deletion, split, merge, boundary,
  language, normalization, uncertainty, and earlier-candidate correction types;
- explicit human versus versioned automated-process correction provenance;
- corrected successor versions with exact prior-state checks and immutable
  original/current/difference/history views;
- conservative withholding of word claims invalidated by text or boundary changes;
- strict word containment, temporal order, lineage, child-artifact, and cache
  validation for canonical assemblies;
- separate normalized-evidence hashes and transcription cache validation;
- clipping to inherited Phase 1 overlap ownership before canonical assembly;
- complete-coverage, source-mapping, ownership, and cache validation;
- strict controlled-reference transcript evaluation with aggregate and stratified
  WER/CER, timing, reliability, subtitle, and correction-impact evidence;
- machine- and human-readable speech-activity reports; and
- `speech-provider list`, `speech-provider inspect`, `speech detect`,
  `speech inspect`, `speech transcribe`, `speech inspect-transcription`,
  `speech assemble`, `speech inspect-assembly`, `speech correct`,
  `speech inspect-revision`, `speech render-transcript`,
  `speech correction-history`, `speech export-subtitles`,
  `speech inspect-subtitles`, `speech validate-subtitles`,
  `speech evaluate-transcript`, `speech inspect-evaluation`, and
  `speech validate-evaluation`, `speech repair-transcription-report`,
  `speech inspect-recovery`, and `speech validate-recovery` commands.

Two executable local speech-activity providers are available. The base
`local.ffmpeg_energy_activity` provider remains a deterministic control whose
`probable_speech` classification cannot distinguish speech from music, noise,
or non-lexical sound. The optional `local.silero_vad` provider supplies semantic
speech-presence probabilities from pinned `silero-vad==6.2.1`; they remain
provider-native and uncalibrated. Install it with `python -m pip install -e
".[vad]"` and select it explicitly with `speech detect --provider
local.silero_vad`. The optional `local.openai_whisper` provider uses pinned
`openai-whisper==20250625` and the verified multilingual `small` checkpoint.
Install it with `python -m pip install -e ".[transcription]"`; acquire the
checkpoint separately at the recorded official hash. Its output remains provider observation evidence and does not become canonical
merely because inference completed; the separate assembly policy must promote it.

## Confidence semantics

Confidence is not collapsed into one score. Each measure states whether it is
provider-native, derived, or unavailable, plus the basis for the claim.
Unavailable confidence has no numeric value. Derived scores are not marked
calibrated without a calibration identity, and scores from different providers
are not assumed comparable.

Speech presence, transcript text, segment timing, word timing, and boundary
confidence remain separate claims.

## Versioning and invalidation

Phase 2 persisted formats, speech-activity policy, transcription policy, and transcript-assembly policy
begin at `1.0.0` and reject unsupported versions. Evidence-affecting provider,
model, language, decoding, candidate, timing, segmentation, threshold, and
retention settings participate in later configuration and artifact identities.

Changing any such field will require a new run or evidence artifact. Rendering
changes alone must not cause retranscription.

## Speech-activity qualification

The baseline passed deterministic processing, complete coverage, source
preservation, Phase 1 ownership reconciliation, persistence, and cache reuse on
a project-authored speech-free silence/tone/noise fixture and the canonical
Riverton clean source. The speech-free fixture deliberately proves the expected
tone/noise false positive, so no semantic detection-quality claim is made. See
the [machine report](../reports/phase-2-speech-activity-baseline-qualification.json)
and [human report](../reports/phase-2-speech-activity-baseline-qualification.md).

## Semantic VAD qualification

The pinned local Silero provider passed complete coverage, source preservation,
cache reuse, and controlled evaluation on clean, naturalized, and adversarial
Riverton lossless mixes. Duration-weighted precision was 0.9996 or higher,
recall was 0.8953--0.8972, and F1 was 0.9447--0.9456. The speech-free
silence/tone/noise control produced zero probable-speech duration. These are
controlled synthetic-fixture measurements, not general performance claims.
The public line schedules were prepared before provider selection; hidden
analytical references were not read. See the [machine report](../reports/phase-2-semantic-vad-qualification.json)
and [human report](../reports/phase-2-semantic-vad-qualification.md).

The `speech evaluate-activity` command evaluates a persisted run against a
public line schedule and can persist the strict evaluation artifact with
`--output`. Only `probable_speech` is positive; uncertain output remains
non-positive. See [ADR 015](architecture/decisions/015-pinned-local-semantic-vad-and-controlled-evaluation.md).

## Initial transcription-provider qualification

The pinned Whisper provider passed isolated execution, source preservation, raw
response retention, normalized evidence validation, word observation mapping,
and stable cache reuse on public lines L001--L005 in all three Riverton
variants. Each variant produced 23 provider segment observations and 189 word
observations with no unresolved excerpt observation. Controlled WER was 0.0466
and CER was 0.0369. These are synthetic excerpt measurements, not general
quality or calibration claims. The public reference text was used only after
inference; hidden analytical references were not read. See the [machine
report](../reports/phase-2-transcription-provider-qualification.json) and
[human report](../reports/phase-2-transcription-provider-qualification.md), plus
[ADR 016](architecture/decisions/016-pinned-whisper-provider-observation-boundary.md).

## Canonical transcript-assembly qualification

The assembly policy passed on the same public L001--L005 provider evidence for
all three Riverton variants. Each run deterministically promoted all 23 segment
observations and all 189 mapped provider-native words, reused an identical
second assembly, and produced no validation findings or blocking regions.

The clean variant produced 235 review regions; naturalized and adversarial each
produced 236. Of those, 212 per variant record unavailable segment/word timing
confidence and 23 record unavailable boundary confidence. Naturalized and
adversarial each add one low word-recognition-confidence region. These counts
are evidence that uncertainty remained machine-readable, not a calibration or
quality claim. See the [machine report](../reports/phase-2-transcript-assembly-qualification.json)
and [human report](../reports/phase-2-transcript-assembly-qualification.md).

## Canonical transcript assembly

`speech assemble CORPUS TRANSCRIPTION_RUN DESTINATION` promotes only validated,
explicitly selected provider candidates into stable canonical segments and
mapped words. `speech inspect-assembly ASSEMBLY_ROOT` verifies and displays the
persisted assembly and report. The original provider response remains immutable.

The original-machine version persists the assembly, version, every segment,
every timestamped word, every low-confidence region, and machine/human reports.
Unavailable timing confidence remains unavailable and creates review evidence;
it is never replaced with segment confidence or an invented score. Missing
selected text and provider failure produce blocking records without invented
canonical text. See [ADR 017](architecture/decisions/017-deterministic-canonical-transcript-promotion.md).

## Transcript-correction qualification

The append-only correction path passed on all three controlled Riverton
assemblies. Each variant applied one explicitly human merge correction that
restored the public L001 orthography `8 p.m.` from the two observed machine
segments `8p.` and `M.`. Every run preserved the base assembly hash, produced a
valid predecessor/successor chain, retained the original reading, exposed the
corrected reading, persisted one difference and history entry, withheld the
invalidated word claims, and reused an identical second revision. No automated
correction was represented as human work.

This is a correction-mechanics and lineage qualification, not an independent
accuracy claim. See the [machine report](../reports/phase-2-transcript-correction-qualification.json)
and [human report](../reports/phase-2-transcript-correction-qualification.md).
## Append-only corrections and successor views

`speech correct ASSEMBLY_ROOT CORRECTION_BATCH DESTINATION` imports a strict,
version-targeted correction batch. It persists the successor version, every
correction record, exact original and current views, a difference report,
correction history, and machine/human revision reports. `speech
render-transcript` renders any persisted original/current/difference/history
view, while `speech correction-history` exposes the append-only lineage.

A correction must reproduce the current prior value exactly. Conflicting
batch targets, unknown versions, invalid temporal mappings, missing evidence
references, and prohibited actor types fail explicitly. Text-changing and
boundary-changing corrections withhold inherited word claims until later
alignment establishes them again. See [ADR 018](architecture/decisions/018-append-only-transcript-corrections.md).

## Subtitle-export qualification

Deterministic WebVTT and SubRip exports passed on the original-machine and
corrected successor views for all three controlled Riverton variants. Every cue
retained canonical source and normalized timing, source-artifact references,
and overlapping low-confidence identifiers. Both formats parsed with exactly
one timing line per manifest cue, and identical second exports reused the
validated cache.

The qualification used stricter three-second/30-character limits to exercise
the documented long-cue policy. Provider word timing is used only when its text
exactly reconstructs the canonical text; otherwise the whole cue is retained
and the loss is recorded. Microsecond starts are floored and ends are ceiled to
milliseconds. See the [machine report](../reports/phase-2-subtitle-export-qualification.json),
[human report](../reports/phase-2-subtitle-export-qualification.md), and
[ADR 019](architecture/decisions/019-subtitles-as-loss-declared-presentation-derivatives.md).

## Subtitle presentation derivatives

`speech export-subtitles ASSEMBLY_ROOT DESTINATION` writes WebVTT, SRT, a sealed
companion manifest, and a validation report. Supply `--revision-root` and
`--view current` for the corrected successor. `speech inspect-subtitles` and
`speech validate-subtitles` verify deterministic rendering, hashes, declared
version, timing, source mapping, cache contents, and report agreement.

Subtitle files are lossy presentation derivatives. The manifest remains the
authoritative record of source references, confidence/review evidence, policy,
segmentation, rounding, and known losses. Low-confidence text is retained, not
silently removed.

## Controlled transcript-evaluation qualification

Strict evaluation reports passed for corrected successor views of public lines
L001--L005 in all three Riverton variants. Corrected WER was 0.0415 and CER was
0.0360. The recorded human correction improved WER by 0.0052 and CER by 0.0009
without changing the original machine view. Segment timing metrics, three-bin
descriptive confidence reliability, review-region coverage, corrected subtitle
validity, represented strata, and stable cache replay were recorded for every
variant.

The public reference documents were authored and frozen before provider
selection and were never supplied to inference. Independently prepared word
timing and expected candidate labels are not present, so those metrics are
explicitly unavailable rather than estimated. These synthetic excerpt results
do not establish general quality or performance for noise, overlap, clipping,
quiet speech, or long-recording boundaries occurring elsewhere in the corpus.
See the [machine report](../reports/phase-2-transcript-evaluation-qualification.json),
[human report](../reports/phase-2-transcript-evaluation-qualification.md), and
[ADR 020](architecture/decisions/020-controlled-reference-transcript-evaluation.md).

## Transcript evaluation

`speech evaluate-transcript ASSEMBLY_ROOT REFERENCE DESTINATION` ingests a
strict source-addressed reference and persists a sealed machine/human report.
Supply `--revision-root REVISION_ROOT --view current` to evaluate a corrected
successor and calculate correction impact, and `--subtitle-export-root` to
validate a matching subtitle derivative. `speech inspect-evaluation` and
`speech validate-evaluation` verify the persisted result and cache.

Reports include aggregate and represented-stratum edit metrics, segment and
optional word timing, descriptive confidence reliability, optional candidate
selection, subtitle validity, correction impact, and explicit unavailability
reasons. References retain document hashes, source mapping, provenance, and an
independence statement.
## Cache, resume, and recovery qualification

Stage-local recovery passed after deliberate corruption of transcription report
metadata, a canonical assembly child, a correction difference artifact, an SRT
file, and an evaluation rendering. Every invalid artifact was preserved under
its stage-local `invalid/` directory before deterministic reconstruction. The
transcription report was rebuilt from validated request, normalized response,
and raw provider evidence without invoking Whisper.

Twelve protected Phase 1 source/normalized-audio and transcription
response/raw-evidence artifacts remained byte-identical. Provider timeout,
malformed output, and primary response corruption remain typed refusal paths in
the provider regression tests; report repair cannot bypass them. See the
[machine report](../reports/phase-2-recovery-qualification.json), [human
report](../reports/phase-2-recovery-qualification.md), and [ADR
021](architecture/decisions/021-stage-local-phase2-quarantine-and-recovery.md).

## Recovery operations

`speech repair-transcription-report TRANSCRIPTION_RUN_ROOT` validates primary
provider evidence and reconstructs only missing or corrupt report metadata.
`speech inspect-recovery` and `speech validate-recovery` verify sealed recovery
records. Deterministic downstream orchestration uses the stage-local recovery
controller to validate, quarantine, rebuild, and revalidate exactly one
artifact root while naming its validated parents and whether a provider ran.

Quarantine is diagnostic evidence, not an active cache entry. Recovery never
patches malformed evidence in place or treats incomplete output as trusted.
## Current boundary

Phase 2 now produces mapped speech activity, fallible provider observations,
deterministic original-machine assemblies, append-only corrected successors,
loss-declared WebVTT/SRT derivatives, strict controlled-reference evaluation,
and stage-local quarantine/recovery evidence. It does not perform external word
alignment when references lack word timing and makes no general quality claim
from the controlled excerpt. It creates no speaker identity, diarization,
argument, factual, rhetorical, adjudicative, or scoring artifact.

## Negative-proof and long-recording qualification

All 17 required negative cases pass through an asserted typed refusal or
conservative recovery result, with no selected test skipped. The normalized
[machine report](../reports/phase-2-negative-proofs.json) and [human
report](../reports/phase-2-negative-proofs.md) name every case, test, and
expected result.

The 7,201-second Phase 1 corpus passed Phase 2 ownership and assembly across 13
chunks and 12 transitions. Qualification produced 13 mapped segments and 13
timestamped words, replayed every cache, preserved the complete Phase 1 corpus
tree, and measured a 2,773,608-byte Python allocator peak. Script-local
synthetic markers qualify mechanics only and make no accuracy claim. See the
[machine report](../reports/phase-2-long-recording-qualification.json), [human
report](../reports/phase-2-long-recording-qualification.md), and [ADR
022](architecture/decisions/022-phase-2-closure-and-long-recording-control.md).

## Completion

All 13 Phase 2 exit gates are complete at application version 0.4.0. The
normalized [completion report](../reports/phase-2-completion.md) records
versions, repository state, providers, models, corpus and configuration
identifiers, counts, metrics, cache/recovery results, long-recording memory,
negative proofs, regressions, evidence inventory, and declared limitations.
