# Phase 3: Speaker diarization and participant identity foundations

Status: Complete  
Target application version: 0.5.0  
Work order: [`work_orders/phase_03.txt`](work_orders/phase_03.txt)

Phase 3 converts Phase 1 source-addressed media and Phase 2 temporal speech
evidence into provisional speaker-participation evidence. It does not turn a
voice cluster into a person or an acoustic score into proof of identity.

## Governing distinctions

- Speech activity says that speech is probably present.
- A speaker observation is bounded acoustic evidence.
- A speaker turn is a temporal proposal about the primary speaking role.
- An overlap interval preserves evidence of simultaneous or possibly
  simultaneous voices.
- A speaker cluster proposes that observations may share a voice source.
- An identity hypothesis proposes a bounded participant interpretation.
- A manual binding is an attributable review decision.
- Unknown and conflict are valid outcomes.

A cluster is not a person. Acoustic similarity is not proof of identity.
Manual binding does not modify the recording or original diarization result.

## Implemented foundation and initial evidence kernel

The first Stage 1 slice provides:

- strict Phase 3 format, diarization-policy, embedding-policy, and
  identity-policy versions;
- provider-independent diarization request and response boundaries;
- explicit provider/model/runtime/device, licensing, and distribution fields;
- visible provider-unavailable, model-unavailable, timeout, cancellation,
  malformed-output, unsupported-audio, validation, and internal failure kinds;
- distinct turn segmentation, overlap, embedding, and clustering capabilities;
- source, normalized-corpus, and chunk-local observation intervals;
- inherited Phase 2 speech-activity and optional transcript lineage;
- provider observations, turn proposals, overlap proposals, and raw evidence;
- canonical speaker observations, change boundaries, turns, and overlap;
- embedding model-space identity, dimensionality, integrity, and protected
  storage references without embedding values in ordinary contracts or logs;
- provisional cluster and membership contracts with no participant-name field;
- separately scoped participant identity, hypothesis, and manual-binding
  contracts;
- separate acoustic, contextual, documentary, and manual hypothesis support;
- append-only predecessor requirements for binding revision and restoration;
- a conservative unconfigured diarization provider boundary; and
- `diarization-provider list` and `diarization-provider inspect` capability
  commands.
The first Stage 2 slice additionally provides:

- deterministic `DiarizationRequest` identities pinned to Phase 1 corpus,
  audio, stream, timeline, and chunk lineage plus selected Phase 2 speech
  intervals and optional transcript assembly/version lineage;
- embedded speech-interval evidence so a provider receives the exact validated
  temporal input, not unresolved identifiers;
- provider-independent normalized-evidence hashing and raw-evidence integrity
  checks;
- canonical `DiarizationRun` persistence containing separately sealed speaker
  observations, change boundaries, and provisional turns;
- strict source-time, normalized-time, chunk-local, canonical-ownership,
  speech-containment, turn-containment, and embedding-reference validation;
- cache reuse only for an identical evidence/configuration request and refusal
  of incomplete or incompatible caches;
- `diarization run`, `diarization inspect`, and `diarization validate`
  operations; and
- deterministic provider tests proving reuse, corruption refusal, immutable
  Phase 1 audio, and the absence of forced cluster or participant identity.

The next Stage 2/3 slice adds:

- self-contained canonical transcript-segment and word evidence in requests;
- temporally derived observation and turn links to transcript artifacts;
- explicit boundary uncertainty, confidence-threshold review, competing nearby
  proposals, inside-word/segment evidence, and overlap effects;
- deterministic reconciliation of non-owner chunk-window observations to the
  Phase 1 earliest-owner canonical observation;
- integrity-sealed canonical overlap intervals with supporting observations,
  classification, active-speaker-count confidence, and partial attribution;
- refusal of invalid ownership markers, missing canonical counterparts,
  duplicate canonical observations, and invalid overlap mappings;
- independent `list-turns`, `list-boundaries`, and `list-overlaps` CLI views;
  and
- overlap count/duration and review-boundary reporting.

The provisional clustering and consistency slice adds:

- eight strict clustering-policy, consistency, proposal, run, summary, and
  report contracts;
- capability-gated normalization of provider acoustic labels;
- stable cluster identities derived from configuration and observation
  membership rather than provider labels or participant names;
- explicit unclustered preservation for missing, unusable, or short evidence;
- unique canonical membership and complete clustered/unclustered partition
  validation;
- cluster temporal distribution, source coverage, model-space lineage,
  consistency, and append-only proposal references;
- refusal of mixed embedding spaces and undeclared clustering capability;
- likely-over-merged classification for simultaneous same-cluster members;
- review-required split proposals that cover every member without applying the
  split or mutating the source cluster;
- deterministic clustering persistence, integrity validation, and cache reuse;
  and
- clustering create, inspect, validate, list-clusters, and
  list-cluster-consistency CLI operations.

The controlled clustering-evaluation and embedding-qualification slice adds:

- seven strict policy, controlled-reference, pairwise-metric, embedding-
  qualification, evaluation, and report contracts;
- independently sealed fixture-local reference assignments that cannot rename
  clusters or become participant identities;
- unordered-pair false-merge, false-split, true-join, and true-separation
  counts with same-speaker precision, recall, F1, and explicit coverage;
- separate embedding model-space, fingerprint, dimension, format, storage,
  safe-path, byte-size, and content-integrity qualification;
- metadata-only qualification when protected vector values are omitted;
- immutable evaluation persistence, strict lineage validation, and partial-
  cache refusal; and
- evaluation create, inspect, and validate CLI operations.

The scoped participant-identity foundation slice adds:

- four strict identity-policy, conflict, append-only foundation-run, and
  participant-identity report contracts;
- minimal named, role-based, locally distinct, and unresolved identities with
  mandatory source, artifact scope, status, and provenance;
- immutable successor runs that retain every predecessor identity, hypothesis,
  and conflict without rewriting source clusters;
- bounded cluster, turn, observation, recording, and corpus scope validation;
- acoustic, contextual, documentary, and manual hypothesis support preserved
  as independent non-comparable measures;
- explicit contrary evidence and unresolved competing-hypothesis conflicts;
- refusal of unsupported scopes, unknown targets, predecessor rewrites, and
  premature reference-voice hypotheses; and
- identity create, propose, inspect, validate, and independent list CLI views.

The bounded reference-voice enrollment slice adds:

- five strict enrollment-policy, reference, lifecycle, append-only run, and
  report contracts;
- identity-foundation lineage and exact declared-scope validation;
- explicit source, recording provenance, licensing, consent or other lawful-
  use basis, source interval, usable speech duration, quality, and
  contamination evidence;
- protected representation references with model-space, fingerprint, and
  content-integrity metadata but no portable vector values;
- deterministic rejection of unauthorized, too-short, unusable, or
  contaminated references and warnings for marginal or uncertain evidence;
- multiple references per identity without deriving identifiers from names;
- append-only revocation and validated same-identity replacement events that
  retain every predecessor enrollment;
- immutable persistence, strict lineage validation, and partial-cache refusal;
  and
- reference enroll, inspect, list, validate, revoke, and lifecycle-history CLI
  operations.

The compatible reference-voice comparison slice adds:

- six strict threshold, calibration, target-representation, comparison, run,
  and report contracts;
- immutable clustering, diarization, identity-foundation, and active-enrollment
  lineage;
- exact model-space and fingerprint compatibility checks;
- explicit provider, method, score scale, ordered thresholds, cohort,
  calibration dataset, operating point, and estimated error-rate fields;
- target and reference quality, duration, channel, overlap, provenance,
  supporting evidence, contrary evidence, and uncertainty records;
- supports, weakly supports, inconclusive, weakly contradicts, contradicts,
  and comparison-invalid classifications;
- invalid classification for unknown or out-of-scope targets, missing or
  out-of-range scores, incompatible representations, unusable evidence, and
  rejected, revoked, replaced, or expired references;
- explicit uncalibrated-score limitations and a contract-level prohibition on
  automatic identity binding;
- immutable persistence, integrity validation, and partial-cache refusal; and
- reference compare, inspect, list, and validate CLI operations.

The comparison-backed identity-hypothesis slice adds:

- positive-comparison promotion limited to supports and weakly-supports
  classifications;
- full comparison, clustering, diarization, enrollment, and identity-foundation
  lineage revalidation;
- target, identity, and declared-scope compatibility checks;
- comparison, reference, target-provenance, supporting-evidence, and contrary-
  evidence references retained in the hypothesis;
- normalized within-scale acoustic strength explicitly distinguished from
  identity probability;
- supported disposition for strong support and proposed disposition for weak
  support;
- refusal of inconclusive, contradictory, and invalid comparisons;
- unchanged contextual, documentary, and manual evidence dimensions; and
- append-only successor persistence plus `identity-propose-from-comparison`.

The append-only manual identity-binding slice adds:

- three strict binding-policy, sealed successor-run, and derived-report
  contracts around the existing manual-decision contract;
- scoped bind, rejection, explicit unknown, revision, restoration, placeholder
  merge, and identity split actions;
- mandatory author, timestamp, rationale, supporting evidence, acknowledged
  contrary evidence, reviewer certainty, and resulting-view identifiers;
- active-predecessor requirements for revision and restoration, including
  bounded scope changes without rewriting an earlier decision;
- merge and split validation against existing identity-foundation entities,
  with unresolved-placeholder-only merge inputs and at least two split
  results;
- derived active state and explicit unresolved conflicts for incompatible
  parallel decision branches, with no silent winner;
- immutable persistence separate from diarization and clustering, exact cache
  reuse, partial-cache refusal, and source-output path protection; and
- identity bind, inspect, active-list, history, and validate CLI operations.

The reviewed identity-view assembly slice adds:

- five strict view-policy, entry, layered-view, sealed-assembly, and report
  contracts;
- exactly eight separately addressable provider, canonical, consistency,
  unresolved, hypothesis, comparison, reviewed, and binding-history views;
- content-pinned provider-response, diarization, clustering, identity-
  foundation, binding-ledger, and optional comparison lineage;
- turn-level manual assignment derived from both binding target and declared
  scope;
- separate original-machine and reviewed-label fields, with mandatory
  `REVIEWED: `, `REVIEWED: UNKNOWN`, and `REVIEWED: CONFLICT` presentation;
- blocking findings for incompatible active branches and impossible
  simultaneous assignment of one identity to independent overlapping turns;
- explicit preservation of unresolved cluster proposals, hypotheses,
  comparisons, unknown states, and complete binding history;
- independent reviewed-state reconstruction during validation, immutable
  persistence, exact cache reuse, and incomplete-cache refusal; and
- identity-view assemble, inspect, list, reviewed, and validate CLI operations.

The speaker-labeled transcript integration slice adds:

- five strict transcript-attribution policy, span, segment, view, and report
  contracts;
- explicit original-machine or current-corrected Phase 2 source-view lineage;
- corrected revision, version, base-assembly, and correction-history
  validation;
- normalized-time association of canonical turns with transcript segments and
  retained words;
- contiguous attribution spans that support segments crossing turns, turns
  crossing segments, and unattributed content without rewriting source text;
- distinct reviewed, machine-cluster, unknown, unattributed, multiple-
  candidate, and conflicted attribution states;
- mandatory disclosure when multiple turns overlap an attribution span;
- blocked trust when reviewed identity conflicts remain;
- deterministic reconstruction during validation, immutable persistence,
  exact cache reuse, incomplete-cache refusal, and text rendering; and
- speaker transcript render, inspect, span-list, and validate CLI operations.

The participant-labeled subtitle slice adds:

- four strict participant-subtitle policy, cue, manifest, and report contracts
  around the existing Phase 2 subtitle file and loss contracts;
- deterministic WebVTT and SRT with the participant label on the first line;
- complete speaker-transcript, transcript version/revision, identity-view,
  diarization, corpus, and source-addressing lineage;
- explicit reviewed, machine-cluster, unknown, unattributed, multiple-
  attribution, and overlap label presentation;
- `OVERLAP: ` disclosure without false sequential serialization;
- refusal before file creation when the reviewed speaker view is conflicted or
  blocked;
- declared timestamp rounding, normalized rendering, combined-attribution,
  retained-long-cue, line-capacity, and format-metadata losses;
- deterministic cue/loss reconstruction, safe-path, byte-size, content-hash,
  immutable-cache, and incomplete-cache validation; and
- participant subtitle export, inspect, cue-list, and validate CLI operations.

The cache, resume, and recovery slice adds:

- five strict recovery policy, fingerprint, invalidation-plan, stage-record,
  and sealed-report contracts;
- eleven independent boundaries from diarization provider response through
  participant subtitle export;
- deterministic topological execution even when recovery tasks are submitted
  out of order;
- validation before reuse, missing-stage resume, and stage-local corruption
  quarantine before rebuild;
- transitive downstream-only invalidation through an explicit dependency graph;
- provider-invocation accounting and reuse of valid upstream provider evidence;
- protected Phase 1 and Phase 2 fingerprints before and after recovery;
- typed refusal for unsafe paths and failed rebuilds while preserving
  quarantined bytes;
- integrity-sealed machine-readable and human-readable recovery reports; and
- recovery inspect, validate, record-list, and invalidation-plan CLI
  operations.

The controlled temporal-diarization evaluation slice adds:

- ten strict scoring-policy, temporal-reference, speaker-mapping, metrics,
  stratum, evaluation, and report contracts;
- independently sealed local-speaker turns, change boundaries, overlap
  intervals, provenance, duration, and diarization lineage;
- bounded maximum-duration one-to-one mapping from provider labels to
  controlled local-speaker keys;
- exact-duration diarization error rate with separate missed-speech,
  false-alarm, and speaker-confusion contributions;
- declared collar, boundary uncertainty, unknown-speaker, non-lexical,
  audience, background, replayed-speech, and overlap policies;
- speaker-change precision, recall, mean absolute timing error, and maximum
  timing error;
- duration-based overlap precision, recall, intersection, and duration error;
- controlled clean-alternating, overlap, and general stratum results;
- strict lineage, bounds, mapping-size, cache completeness, machine-report,
  and human-report validation; and
- temporal diarization evaluate, inspect, validate, and stratum-list CLI
  operations.

The integrity and completion-reporting slice adds:

- seven strict aggregation-policy, evidence, metric, provider-disclosure,
  gate, finding, and completion-report contracts;
- parsing, common-field validation, byte counts, and hashes for sixteen
  checked-in Phase 3 machine/human qualification pairs;
- separation of measured evaluation, synthetic mechanics, human-decision
  mechanics, presentation validation, provider claims, and expectations;
- all eighteen ordered work-order gates with evidence and blocking findings;
- conservative `in_progress` status for missing evidence and typed refusal of
  present but corrupt, failed, or mutated evidence;
- explicit provider/model, privacy/export, repository-state, limitation,
  concern, metric, and boundary disclosures;
- integrity-sealed completion reports with immutable reuse;
- append-only report succession with predecessor archiving; and
- completion build, inspect, validate, gate-list, and evidence-list CLI
  operations.

The long-recording operational slice additionally qualifies the persisted
7,201-second Phase 1/2 corpus across thirteen owned chunks; thirteen canonical
observations and turns; three recurring cross-chunk clusters; reviewed identity,
transcript, and subtitle assembly; seven cache hits; unchanged upstream
evidence; and a bounded 2,698,662-byte traced Python allocator peak.

The aggregate successor closes all eighteen gates and records Phase 3 as
`complete`.

No production diarization or clustering model has been selected or installed in this slice.

## Voice-embedding privacy policy

Voice embeddings are sensitive derived technical evidence. The default policy
stores only a protected artifact reference and excludes embeddings from
portable export. Direct values are never fields of the authoritative
`SpeakerEmbedding` contract and may not be logged.

Portable export is valid only when the embedding is actually stored and an
explicit export-authorization reference is recorded. Manual participant
binding does not provide that authorization.

## Current boundary

The repository now runs and validates provider-independent diarization,
provisional acoustic clustering, controlled partition evaluation, protected
embedding qualification, and append-only scoped participant-identity
hypotheses, bounded reference-voice enrollment, compatible reference-voice
comparison, positive comparison-backed hypotheses, and attributable manual
identity binding with deterministic layered reviewed views, speaker-labeled
transcript presentation, loss-declared participant WebVTT/SRT derivatives, and
stage-local recovery with transitive downstream-only invalidation. Controlled
temporal evaluation now measures exact speaker time, change boundaries, and
overlap against sealed local-speaker references. The integrity aggregate binds
sixteen qualification pairs and closes all eighteen gates. Clusters remain voice-compatibility hypotheses, enrolled
references remain validated evidence, acoustic support remains distinct from
identity decisions, and manual labels remain visibly separate from machine
labels. Recovery preserves valid upstream providers and Phase 1/2 evidence.
Evaluation does not promote provider labels to identities. No Phase 3
presentation derivative rewrites diarization or Phase 2 transcript evidence.
The built-in registry remains deliberately unavailable because no production
diarization, clustering, or comparison model has been selected or qualified.

The next project phase is Phase 4, speaker-attributed discourse corpus
construction.
