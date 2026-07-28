# Phase 2 completion report

Status: **COMPLETE**  
Date: 2026-07-26  
Application version: 0.4.0  
Contract version: 0.1.0

Phase 2 satisfies its success definition. Ratiocinatus can take a valid Phase 1
corpus and produce integrity-checked, source-addressed, timestamped transcript
evidence with explicit uncertainty, append-only correction, subtitle
derivatives, controlled evaluation, and stage-local recovery.

A transcript remains a fallible analytical derivative. It does not replace the
recording and is not an authoritative source record.

## Exit gates

| Gate | Status | Evidence |
|---|---|---|
| Stable source mapping | Complete | Every canonical segment and word carries normalized and source-media intervals plus Phase 1 lineage |
| Speech activity | Complete | Speech, non-speech, uncertain, boundaries, confidence origin, provider, and chunk ownership persist separately |
| Timestamped transcript and words | Complete | 69 controlled segments and 567 mapped words across three variants |
| Unknown and low confidence | Complete | 707 review regions, zero blocking regions, and no fabricated confidence |
| Alternatives | Complete | Bounded alternative contracts and explicit selection; restoration is regression-tested |
| Corrections | Complete | Three append-only human corrections, predecessor/successor chains, immutable original views, and no automated work represented as human |
| Subtitle export | Complete | Six validated WebVTT/SRT exports with 69 machine and 66 corrected cues |
| Evaluation | Complete | Controlled text, timing, confidence, subtitle, strata, and correction-impact reports |
| Cache and recovery | Complete | Five corrupted/missing stages recovered without provider reinvocation; 12 protected parents unchanged |
| Integrity | Complete | All 17 required negative cases pass through typed refusal or conservative recovery |
| Long recording | Complete | 7,201 seconds, 13 chunks, 12 transitions, inherited overlap ownership, cache replay, valid final assembly, 2,773,608-byte Python peak |
| Regression and boundary | Complete | 119 tests; no speaker identity, argument, factual conclusion, judgment, or scoring artifact |

## Controlled measurements

The pinned Silero activity provider represented 1,397,344,000 microseconds as
probable speech, 241,918,021 as probable non-speech, and 18,848,001 as
uncertain across 1,750 intervals in the three controlled variants.

The pinned local Whisper provider produced 23 observations and 189 word
observations per variant. Canonical assembly promoted all 69 observations and
567 mapped words. The controlled corrected view measured WER 0.04145 and CER
0.03597; the recorded correction changed WER by -0.00518 and CER by -0.00090.
Those figures describe only synthetic public lines L001-L005.

The long-recording gate reused the Apache-2.0 synthetic 7,201-second Phase 1
fixture. Qualification-only synthetic marker providers produced exactly one
owned activity interval, transcript segment, and timestamped word per chunk.
They prove addressing, overlap ownership, resumability, caching, and final
assembly mechanics; they make no speech-detection or recognition-quality claim.
The Phase 1 corpus tree hash was unchanged.

## Provider, licensing, and distribution

The qualified transcription provider is `local.openai_whisper` 1.0.0 with the
`openai/whisper-small` model and pinned model fingerprint
`9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794`.
The optional package/model is MIT-licensed, installed separately, and not
redistributed by this Apache-2.0 repository.

## Declared limits

- Controlled excerpt measurements do not establish general performance.
- The initial provider exposes one candidate; alternative preservation is
  implemented and tested, but no provider alternatives were available in the
  qualification run.
- Provider timestamps do not carry independent timing-confidence scores.
- External word alignment remains unavailable when references lack word timing.
- Long-recording markers qualify mechanics only, not recognition accuracy.

These limits do not block the Phase 2 success definition. Machine-readable
gate results, identifiers, inventories, metrics, negative cases, repository
state, and evidence references are in `phase-2-completion.json`.
