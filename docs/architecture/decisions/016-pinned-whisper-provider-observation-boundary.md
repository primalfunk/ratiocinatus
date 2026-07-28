# ADR 016: Pinned Whisper provider-observation boundary

Status: Accepted  
Date: 2026-07-26

## Context

Phase 2 requires an initial local transcription provider, but model-generated
text must remain fallible evidence rather than become an authoritative or
canonical transcript merely because inference completed.

The provider boundary must preserve audio and activity lineage, raw output,
language claims, segment and word timing origins, confidence semantics,
timeouts, corruption detection, and cache identity. It must also avoid
fabricating alternatives or timing confidence that the provider does not
supply.

## Decision

Use `openai-whisper==20250625` with the multilingual `small` checkpoint through
provider identity `local.openai_whisper`. The integration:

- requires the exact package version and verifies the checkpoint SHA-256
  `9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794`
  before loading it;
- records model, package, device, PyTorch, FFmpeg, configuration, and
  integration identity in evidence-sensitive fingerprints;
- never downloads a model during evidence processing;
- does not redistribute the package or model in this repository;
- executes inference in an isolated child process with a request timeout;
- merges selected probable-speech evidence only across configured short gaps
  and splits processing clips at the configured maximum duration;
- retains unmodified worker JSON when policy and an evidence root permit;
- normalizes provider segments and words into mapped source-media and
  normalized-audio observations;
- marks segment timestamps and word timestamps as provider-native while
  leaving timing confidence unavailable;
- records Whisper word probability as provider-native and uncalibrated;
- records exponentiated segment average log probability as derived and
  uncalibrated, not as a correctness probability;
- exposes one candidate only and records why that candidate was selected; and
- creates explicit unresolved observations when selected evidence is too short
  or produces no lexical segment.

Provider observations may reference multiple speech-activity intervals when a
bounded merge creates one inference clip. The request therefore embeds the
selected activity evidence and normalized-audio identity rather than carrying
opaque interval identifiers alone.

Whisper's official repository states that its code and model weights are
released under the MIT License. The project also documents local FFmpeg and
PyTorch operation, multilingual language selection, segment processing, and
model-size tradeoffs:

- https://github.com/openai/whisper
- https://pypi.org/project/openai-whisper/

## Consequences

Transcription is an optional installation (`.[transcription]`), and the
checkpoint must be acquired separately at its official hash. A missing,
mismatched, or unqualified checkpoint cannot appear as the qualified provider.

The isolated worker provides a real timeout boundary and prevents a hung model
call from blocking the parent indefinitely. Completed transcription evidence is
cached separately from speech activity by audio, activity run, selected
intervals, provider/runtime fingerprint, and policy.

The resulting objects are `ProviderTranscriptObservation` and
`ProviderWordObservation` evidence. They are not yet canonical
`TranscriptSegment` or `TranscriptWord` artifacts. Alternative decoding,
low-confidence-region synthesis, correction history, transcript assembly, and
subtitle export remain later Phase 2 work.

Controlled WER/CER results are regression evidence for the synthetic excerpt
only. They do not establish general transcription quality.

## Alternatives considered

- Run Whisper in the parent process. Rejected because Python inference does not
  provide a reliable bounded timeout or termination boundary.
- Use a hosted transcription service. Rejected for the initial provider because
  it adds network, retention, service-version, and cancellation uncertainty.
- Treat Whisper log probability as calibrated correctness confidence. Rejected
  because no Ratiocinatus calibration has been performed.
- Generate multiple candidates by varying temperatures. Deferred; the initial
  slice must not imply provider-native alternatives where none are exposed.
- Promote successful output directly to canonical transcript segments.
  Rejected because provider inference and canonical assembly are distinct
  evidentiary stages.
