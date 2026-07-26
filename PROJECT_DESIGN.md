# Ratiocinatus Project Design

**Document:** `PROJECT_DESIGN.md`  
**Status:** Living design reference  
**Version:** 0.1.0  
**Project maturity:** Pre-implementation  
**Primary implementation language:** Python  
**Execution model:** Local-first  
**Current local model ceiling:** Approximately 14B parameters through LM Studio  

---

## 1. Purpose

This document defines the current design intent for **Ratiocinatus**.

It is not a frozen specification and should not be treated as one. It exists to give the project a durable point of reference while preserving the freedom to revise architecture, phase boundaries, implementation choices, and operating assumptions as evidence accumulates.

Its purposes are to:

- define the problem the project intends to solve;
- state the principles that should govern implementation;
- separate observation, interpretation, adjudication, scoring, review, and presentation;
- identify the major artifacts and subsystems likely to be required;
- establish an anticipated development sequence;
- record unresolved questions and known risks;
- prevent early implementation decisions from silently becoming permanent architecture;
- and give later work orders, completion reports, and corrective subphases a common frame of reference.

This document should become more precise as the project gains substance. It may be revised whenever implementation, evaluation, licensing, performance, or ethical considerations reveal that the current design is incomplete or mistaken.

Revision is expected. Silent architectural drift is not.

---

## 2. Project Vision

Ratiocinatus is a local-first audiovisual reasoning-analysis and adjudication system.

It is intended to ingest recorded discourse, potentially several hours in length, and construct an evidence-backed analytical representation of:

- who spoke;
- what was said;
- when it was said;
- which claims, questions, answers, objections, rebuttals, concessions, definitions, and conclusions were expressed;
- how those discourse acts relate to one another;
- which logical, evidential, dialectical, or procedural standards apply;
- which referee calls can be supported from the record;
- and how those calls contribute to transparent participant scorecards.

The system may then produce an annotated edition of the source recording containing:

- disclosure front matter;
- speaker-attributed captions;
- discourse and argument annotations;
- referee calls;
- score changes;
- uncertainty notices;
- and final back matter summarizing the analysis.

Ratiocinatus is intended to function as an inspectable referee of recorded reasoning, not as an opaque model that declares winners.

Its defining principle is:

> Every material judgment must be traceable to preserved evidence, an explicit interpretation, an applicable rule, and a reproducible calculation.

---

## 3. Name and Identity

**Ratiocinatus** derives from the Latin verb associated with reckoning, calculation, inference, and reasoned conclusion.

The name is intended to evoke:

- reasoning carried through;
- an account that has been reckoned;
- conclusions reached through explicit analysis;
- and a machine whose judgments arise from procedure rather than intuition alone.

Working descriptive line:

> **The argument, reckoned from the record.**

The project name does not imply infallibility, omniscience, perfect neutrality, or universal truth-detection.

---

## 4. Problem Statement

Recorded discussion is difficult to evaluate reliably.

A viewer may encounter:

- incomplete sentences;
- overlapping speakers;
- implied premises;
- shifting definitions;
- indirect answers;
- unanswered questions;
- delayed rebuttals;
- factual assertions;
- causal claims;
- appeals to authority;
- rhetorical questions;
- corrections;
- concessions;
- quotations;
- and contradictions separated by long intervals.

Human judgment is often affected by:

- agreement or disagreement with a speaker;
- confidence and charisma;
- speaking style;
- prior reputation;
- political or cultural alignment;
- selective memory;
- unequal attention;
- and unclear or inconsistently applied standards.

Existing automated systems commonly reduce the problem to one or more narrower tasks:

- transcription;
- summarization;
- sentiment analysis;
- fallacy labeling;
- fact checking;
- debate winner prediction;
- or general-purpose model commentary.

Ratiocinatus instead seeks to construct an accountable chain from audiovisual evidence to adjudicated result.

The intended chain is:

1. preserve and address the source;
2. identify speech and speakers;
3. transcribe what was said;
4. construct discourse acts;
5. normalize candidate propositions;
6. reconstruct argument relations;
7. apply explicit rules;
8. issue evidence-backed calls;
9. derive transparent scores;
10. allow review and appeal;
11. render an annotated audiovisual edition;
12. preserve the complete audit record.

---

## 5. Scope

### 5.1 Intended capabilities

Ratiocinatus is expected eventually to support:

- long-form audiovisual ingestion;
- timestamped transcription;
- speaker diarization;
- participant identity hypotheses;
- discourse-act classification;
- proposition construction;
- argument graph construction;
- logical and dialectical adjudication;
- transparent scoring;
- human review and appeals;
- annotated video rendering;
- companion reports and exports;
- replay and reproducibility;
- and evaluation against human-reviewed corpora.

### 5.2 Initial deployment assumptions

The initial system is expected to operate:

- locally;
- on consumer hardware;
- primarily in Python;
- with open-source or publicly available tools where suitable;
- with LM Studio as an initial local language-model interface;
- with models up to approximately 14B parameters used comfortably;
- and without dependence on mandatory commercial cloud services.

These assumptions are provisional and may be revised.

---

## 6. Non-Goals

Ratiocinatus is not initially intended to:

- determine ultimate truth across all factual domains;
- infer private beliefs, motives, or intentions;
- diagnose intelligence, morality, honesty, or personality;
- reward charisma, accent, fluency, or confidence as though they were logical quality;
- suppress or censor speech;
- make legal findings;
- replace domain experts;
- guarantee speaker identity from voice alone;
- treat every disagreement as formally decidable;
- assign authority merely because an output sounds analytical;
- or produce an unquestionable overall winner.

The system may identify evidential weakness or contradiction within the available record, but it must distinguish those findings from proof that a proposition is false.

The system may generate aggregate scores, but those scores must remain derived summaries rather than substitutes for the underlying analytical record.

---

## 7. Foundational Design Principles

### 7.1 Evidence before interpretation

The original audiovisual source must remain unchanged and addressable.

Every material derived artifact should retain links to:

- source file;
- source hash;
- source interval;
- transcript span;
- speaker hypothesis;
- processing configuration;
- provider version;
- and transformation provenance.

### 7.2 Interpretation before adjudication

The system must not issue referee calls directly from raw speech.

It must first represent what it believes the participant said and how that statement functions within the discourse.

### 7.3 Adjudication before scoring

Scores must be derived from committed calls and explicit formulas.

No language model may directly assign the authoritative final score.

### 7.4 Proposals are not facts

Machine-generated transcripts, identities, propositions, graph relations, and adjudications remain hypotheses until accepted by the applicable process.

### 7.5 Uncertainty is a first-class output

The system must represent states such as:

- unknown;
- ambiguous;
- low confidence;
- multiply interpretable;
- unsupported;
- unevaluable;
- unresolved;
- disputed;
- and malformed.

It must not force every passage into a definitive interpretation.

### 7.6 Same rule under equivalent conditions

Rules should apply consistently to participants occupying comparable roles.

Differences in role, format, burden, opportunity, speaking time, or exposure to challenge must be modeled explicitly.

### 7.7 Explanation is not authority

A fluent explanation generated by a model does not validate a call.

Authority must come from:

- preserved evidence;
- explicit interpretation;
- rule applicability;
- machine-readable validation;
- and reproducible execution.

### 7.8 Human correction preserves history

Human review may revise machine outputs, but revisions must not erase the original proposal or its provenance.

### 7.9 Provider independence

Transcription, diarization, embeddings, language models, visual analysis, and rendering should sit behind replaceable boundaries wherever practical.

### 7.10 Local-first operation

The initial architecture should support execution on local consumer hardware without requiring commercial cloud services.

### 7.11 Bounded model use

Language models should operate over small, explicit context packages and return schema-constrained proposals.

### 7.12 Deterministic authority

Where deterministic code can validate, derive, or reject an output, deterministic code should be authoritative over model prose.

### 7.13 Replayability

A completed run should preserve enough information to reproduce its material analytical results or clearly identify why exact reproduction is not possible.

### 7.14 Separation of layers

Observation, interpretation, adjudication, scoring, review, and rendering must remain architecturally distinct.

---

## 8. Design Commitments and Provisional Choices

This document distinguishes between enduring commitments and replaceable expectations.

### 8.1 Design commitments

The following should not change casually:

- preservation of source evidence;
- traceability of material judgments;
- explicit uncertainty;
- separation of interpretation from adjudication;
- separation of adjudication from scoring;
- provider-independent boundaries;
- versioned rules and contracts;
- preserved human-review history;
- reproducible score calculations;
- and visible disclosure in modified audiovisual outputs.

### 8.2 Current architectural expectations

The following are expected but revisable:

- Python as the main implementation language;
- local filesystem workspaces;
- SQLite for indexed persistence;
- JSON or JSON Lines for portable canonical artifacts;
- FFmpeg for audiovisual processing and rendering;
- Whisper-family transcription;
- pyannote-family diarization;
- local embeddings;
- LM Studio for local model access;
- graph structures implemented initially without a dedicated graph database;
- and a CLI-first development approach.

### 8.3 Candidate tools

Specific libraries, models, frameworks, and interfaces are replaceable unless and until a later decision record elevates them into a compatibility commitment.

---

## 9. Conceptual Architecture

Ratiocinatus is expected to contain the following major layers.

### 9.1 Source and evidence layer

Responsible for:

- media ingestion;
- source integrity;
- stream inspection;
- normalized working derivatives;
- timestamps;
- chunking;
- stable identifiers;
- and processing provenance.

### 9.2 Speech layer

Responsible for:

- voice activity;
- transcription;
- word and phrase timing;
- speaker diarization;
- overlap;
- speaker clustering;
- and speaker identity hypotheses.

### 9.3 Participant layer

Responsible for:

- persistent participant identities;
- named and unnamed speakers;
- visible participant tracks;
- voice and face evidence;
- participant roles;
- and uncertainty in identity binding.

### 9.4 Discourse layer

Responsible for:

- utterances;
- assertions;
- questions;
- answers;
- objections;
- rebuttals;
- concessions;
- qualifications;
- definitions;
- quotations;
- examples;
- procedural remarks;
- and non-argumentative speech.

### 9.5 Proposition and argument layer

Responsible for:

- normalized propositions;
- explicit and inferred premises;
- conclusions;
- support;
- attack;
- contradiction;
- qualification;
- dependency;
- burdens;
- and open obligations.

### 9.6 Adjudication layer

Responsible for:

- logical standards;
- evidential standards;
- dialectical rules;
- procedural rules;
- rule applicability;
- referee calls;
- alternatives;
- confidence;
- appeals;
- and reviewed dispositions.

### 9.7 Scoring layer

Responsible for:

- component metrics;
- opportunity normalization;
- confidence adjustment;
- configurable weights;
- score histories;
- aggregate scorecards;
- and scoring-policy provenance.

### 9.8 Review layer

Responsible for:

- transcript correction;
- speaker resolution;
- interpretation review;
- graph review;
- call review;
- appeals;
- adjudication history;
- and human sign-off.

### 9.9 Editorial rendering layer

Responsible for:

- front matter;
- subtitles;
- overlays;
- live call presentation;
- score presentation;
- back matter;
- companion reports;
- and export packages.

---

## 10. Epistemic Model

Major analytical artifacts should use explicit states rather than a simple true-or-false model.

Candidate states include:

- observed;
- proposed;
- validated;
- accepted;
- rejected;
- superseded;
- disputed;
- unresolved;
- indeterminate;
- malformed;
- unsupported;
- unevaluable;
- and withdrawn.

The final state vocabulary should be defined through versioned contracts.

An artifact's workflow state must not be confused with the truth of the proposition it represents.

Examples:

- a transcript may be accepted as the best available transcription;
- a proposition may be accurately reconstructed but factually false;
- an argument may be valid but rest on a disputed premise;
- a response may be relevant but insufficient;
- and a referee call may remain unresolved because two interpretations are comparably plausible.

---

## 11. Anticipated Major Artifacts

The following artifacts are anticipated. Their final names and boundaries may change.

### 11.1 Source artifacts

- `SourceRecording`
- `MediaStream`
- `ProcessingChunk`
- `SourceInterval`
- `IngestionManifest`
- `SourceIntegrityRecord`

### 11.2 Speech artifacts

- `SpeechSegment`
- `TranscriptToken`
- `TranscriptSpan`
- `SpeakerTurn`
- `SpeakerCluster`
- `OverlapInterval`
- `SpeakerIdentityHypothesis`
- `TranscriptCorrection`

### 11.3 Participant artifacts

- `Participant`
- `ParticipantRole`
- `VoiceReference`
- `VisibleTrack`
- `AudiovisualSpeakerAssociation`
- `ParticipantIdentityDecision`

### 11.4 Discourse artifacts

- `Utterance`
- `DiscourseAct`
- `Question`
- `Answer`
- `Claim`
- `Definition`
- `Objection`
- `Rebuttal`
- `Concession`
- `Qualification`
- `Quotation`
- `ProceduralMove`

### 11.5 Argument artifacts

- `Proposition`
- `Premise`
- `Conclusion`
- `ArgumentEdge`
- `ArgumentGraph`
- `ActiveBurden`
- `OpenObligation`
- `AlternativeInterpretation`
- `ArgumentSnapshot`

### 11.6 Adjudication artifacts

- `Rule`
- `Ruleset`
- `RuleApplicabilityResult`
- `AdjudicationCall`
- `CallEvidence`
- `CallDisposition`
- `Appeal`
- `ReviewDecision`

### 11.7 Scoring artifacts

- `ScoringPolicy`
- `ScoreComponent`
- `ScoreEvent`
- `ScoreNormalizationRecord`
- `ParticipantScorecard`
- `ScoreTimeline`

### 11.8 Rendering artifacts

- `CaptionTrack`
- `OverlayEvent`
- `FrontMatterPlan`
- `BackMatterPlan`
- `RenderManifest`
- `AnnotatedEdition`
- `CompanionReport`

---

## 12. Role of Local Language Models

Local language models are expected to assist with bounded interpretive tasks.

Initial available capacity is approximately 14B parameters through LM Studio.

### 12.1 Appropriate model uses

Possible uses include:

- classifying discourse acts;
- identifying candidate claims;
- proposing proposition normalizations;
- identifying possible premises and conclusions;
- proposing support or attack relations;
- detecting ambiguity;
- generating alternative interpretations;
- and drafting explanations from already established calls.

### 12.2 Prohibited silent authority

Language models must not silently:

- alter the transcript;
- invent missing evidence;
- merge distinct claims;
- resolve speaker identity;
- determine authoritative truth;
- assign final scores;
- rewrite the record to improve an argument;
- or issue unreviewable adjudications.

### 12.3 Model-request requirements

Model requests should be:

- bounded;
- schema-constrained;
- context-budgeted;
- evidence-linked;
- provider-recorded;
- validated;
- cacheable where appropriate;
- and rejectable.

The architecture should assume that local models will sometimes produce:

- malformed output;
- unsupported interpretations;
- inconsistent classifications;
- fabricated premises;
- overconfident conclusions;
- and persuasive but invalid explanations.

The system must contain these failures rather than rely on prompting alone to eliminate them.

---

## 13. Anticipated Technical Materials

Candidate tools include, but are not limited to:

- Python;
- FFmpeg and FFprobe;
- Whisper-family speech recognition;
- faster-whisper or comparable optimized inference;
- pyannote.audio or comparable diarization tooling;
- LM Studio;
- local embedding models;
- SQLite;
- JSON or JSON Lines;
- Pydantic, msgspec, dataclasses, or equivalent contract tooling;
- NetworkX or equivalent graph analysis;
- OpenCV and related visual tooling;
- ASS subtitle generation;
- and a local review interface, potentially web-based or desktop-based.

No candidate tool is authoritative merely because it appears in this document.

Each dependency should be evaluated for:

- license;
- redistribution rights;
- local operability;
- hardware requirements;
- determinism;
- model availability;
- performance;
- maintenance status;
- output quality;
- and replaceability.

Licensing review should occur before a dependency becomes architecturally central.

---

## 14. Referee and Rule System

The referee is expected to operate through multiple rule families.

### 14.1 Formal logical rules

Possible areas include:

- propositional validity;
- contradiction;
- conditional inference;
- conjunction;
- disjunction;
- quantification;
- equivalence;
- scope;
- and invalid formal transformations.

Formal adjudication should occur only where the propositions can be represented with sufficient confidence.

### 14.2 Informal reasoning rules

Possible areas include:

- relevance;
- adequacy of support;
- causal reasoning;
- analogy;
- statistical support;
- representativeness;
- source applicability;
- definitional consistency;
- omitted alternatives;
- and conclusion strength.

### 14.3 Dialectical rules

Possible areas include:

- responsiveness;
- burden satisfaction;
- objection handling;
- question answering;
- concession;
- correction;
- misrepresentation;
- evasion;
- and unresolved challenges.

### 14.4 Evidential rules

Possible areas include:

- cited support;
- support from the record;
- corroboration;
- contradiction by available evidence;
- source quality;
- uncertainty;
- and unsupported factual assertion.

### 14.5 Procedural rules

Procedural obligations depend on discourse format.

Potential formats include:

- formal debate;
- interview;
- hearing;
- panel discussion;
- moderated forum;
- lecture and questions;
- adversarial examination;
- and informal conversation.

Participant obligations must be derived partly from role and format.

### 14.6 Rule requirements

Each rule should eventually define:

- stable identifier;
- name;
- version;
- family;
- purpose;
- applicability conditions;
- required evidence;
- exclusions;
- counterexamples;
- severity behavior;
- uncertainty behavior;
- review guidance;
- and possible scoring effect.

A named fallacy should not become a penalty merely because a model recognizes a familiar pattern. The system must identify the actual defect and prove applicability.

---

## 15. Scoring Philosophy

The score is a derived view of the adjudication record.

It should not be treated as the sole or most authoritative output.

Expected score dimensions may include:

- inferential execution;
- evidential support;
- responsiveness;
- consistency;
- burden management;
- correction and concession discipline;
- and uncertainty calibration.

Scoring must account for:

- number of evaluable moves;
- speaking time;
- participant role;
- opportunity;
- exposure to challenge;
- confidence;
- unresolved calls;
- and variation in argument difficulty.

A participant must not receive a superior score merely by:

- speaking less;
- making fewer testable claims;
- avoiding direct answers;
- or occupying a less demanding role.

Weights and formulas are policy choices. They must be:

- versioned;
- disclosed;
- configurable where appropriate;
- and separable from the underlying calls.

Component scores should remain primary. Aggregate scores should be treated cautiously.

---

## 16. Human Review and Appeals

Review is expected to be architectural rather than incidental.

At minimum, the system should eventually support review queues for:

- low-confidence transcription;
- uncertain speaker identity;
- ambiguous proposition reconstruction;
- contested graph relations;
- and disputed adjudication calls.

A reviewer should be able to:

- play the exact source interval;
- inspect transcript alternatives;
- inspect speaker evidence;
- inspect the local argument neighborhood;
- accept or revise a proposition;
- sustain, overturn, remand, or leave unresolved a call;
- and provide a reason.

Review must preserve:

- the original machine proposal;
- the reviewer decision;
- the rationale;
- the time of decision;
- the responsible reviewer identity;
- and the resulting downstream invalidations or recomputations.

---

## 17. Annotated Video Design

The rendered edition should disclose that it has been modified.

### 17.1 Front matter may include

- project version;
- ruleset version;
- source information;
- transcription limitations;
- identity limitations;
- review status;
- scoring-policy summary;
- and an explanation of visual notation.

### 17.2 During-video presentation may include

- speaker captions;
- discourse-role labels;
- claim identifiers;
- active questions;
- open objections;
- referee calls;
- confidence;
- score movement;
- and uncertainty indicators.

### 17.3 Back matter may include

- final scorecards;
- score history;
- strongest and weakest passages;
- sustained and overturned calls;
- unresolved interpretations;
- review status;
- and audit information.

### 17.4 Output modes

The system should support multiple editions rather than forcing all information into one display:

- clean transcript edition;
- referee edition;
- full analytical edition;
- and companion interactive report.

Accessibility, legibility, and interpretive restraint must take priority over maximal annotation density.

---

## 18. Anticipated Development Phases

The phase plan below is provisional.

Phases may be split, merged, reordered, narrowed, repeated, or supplemented by corrective subphases.

### Phase 0: Project foundation and evidentiary kernel

**Goal:** Establish repository structure, contracts, provenance, deterministic foundations, provider boundaries, and the canonical evidence model.

Expected work:

- repository initialization;
- Python package structure;
- configuration;
- versioned contracts;
- stable identifiers;
- source hashing;
- deterministic serialization;
- immutable or append-only artifact policy;
- provider abstractions;
- structured logging;
- replay foundations;
- CLI foundations;
- fixture recordings;
- baseline reports;
- dependency inventory;
- and license inventory.

No substantive logical adjudication or scoring should be implemented.

### Phase 1: Audiovisual ingestion and source addressing

**Goal:** Convert long recordings into stable, addressable audiovisual corpora.

Expected work:

- media inspection;
- stream selection;
- audio normalization;
- processing chunks;
- source interval mapping;
- working derivatives;
- cache;
- integrity validation;
- ingestion manifest;
- long-recording resume and recovery;
- and normalized-source reports.

### Phase 2: Transcription and temporal speech evidence

**Goal:** Create a timestamped, confidence-bearing transcript.

Expected work:

- speech activity;
- transcription;
- word and segment timestamps;
- low-confidence regions;
- alternative transcript candidates;
- correction records;
- subtitle export;
- and transcription evaluation.

### Phase 3: Speaker diarization and participant identity foundations

**Goal:** Determine who appears to be speaking without forcing identity certainty.

Expected work:

- speaker turns;
- overlap;
- speaker clustering;
- cluster consistency;
- identity hypotheses;
- reference-voice enrollment;
- manual identity binding;
- unknown state;
- and diarization evaluation.

### Phase 4: Speaker-attributed discourse corpus

**Goal:** Produce a stable corpus of speaker-attributed utterances.

Expected work:

- utterance segmentation;
- turn repair;
- interrupted and incomplete speech;
- quotation handling;
- speaker-attributed transcript;
- context windows;
- correction propagation;
- and review tools.

### Phase 5: Discourse-act construction

**Goal:** Represent what each utterance is doing in the conversation.

Expected work:

- assertions;
- questions;
- answers;
- objections;
- rebuttals;
- concessions;
- qualifications;
- definitions;
- examples;
- quotations;
- procedural speech;
- evidence spans;
- alternatives;
- and confidence.

### Phase 6: Proposition normalization

**Goal:** Represent discourse content as inspectable propositions without erasing original wording.

Expected work:

- candidate propositions;
- explicit and inferred content;
- source-span alignment;
- proposition alternatives;
- omitted-premise representation;
- contradiction candidates;
- normalization reports;
- and human review.

### Phase 7: Argument graph construction

**Goal:** Represent support, attack, dependency, contradiction, and unresolved obligations.

Expected work:

- premises;
- conclusions;
- support edges;
- attack edges;
- qualification;
- dependency;
- question-answer relations;
- active burdens;
- open objections;
- graph reports;
- and visualization.

### Phase 8: Rules of adjudication

**Goal:** Create the first explicit, versioned rulebook.

Expected work:

- rule contracts;
- rule identifiers;
- applicability conditions;
- exclusions;
- counterexamples;
- evidence requirements;
- severity;
- uncertainty behavior;
- review guidance;
- and human-readable documentation.

The first ruleset should be intentionally small.

Candidate initial rules:

- explicit contradiction;
- unanswered direct question;
- nonresponsive answer;
- unsupported conclusion;
- misrepresentation of a recorded claim;
- and invalid deductive form where formalization is sufficiently clear.

### Phase 9: Initial adjudication engine

**Goal:** Apply rules to committed analytical artifacts and produce reproducible calls.

Expected work:

- rule applicability;
- call construction;
- evidence packages;
- alternative interpretation handling;
- confidence;
- call disposition;
- deterministic replay;
- and adjudication reports.

### Phase 10: Human review and appeals

**Goal:** Make uncertain interpretations and calls inspectable and revisable.

Expected work:

- review queues;
- transcript review;
- identity review;
- proposition review;
- graph review;
- call review;
- sustain, overturn, remand, and unresolved dispositions;
- appeals;
- history;
- and reviewer provenance.

### Phase 11: Scoring framework

**Goal:** Derive transparent scorecards from committed calls.

Expected work:

- score dimensions;
- score events;
- normalization;
- role adjustment;
- opportunity adjustment;
- confidence adjustment;
- configurable weights;
- policy versions;
- participant reports;
- and aggregate scorecards.

### Phase 12: Annotated rendering

**Goal:** Produce a modified audiovisual edition from committed analysis.

Expected work:

- disclosure front matter;
- speaker captions;
- discourse captions;
- referee-call overlays;
- score timelines;
- confidence warnings;
- back matter;
- render manifests;
- and multiple edition modes.

### Phase 13: Visual participant evidence

**Goal:** Use visual evidence to strengthen participant and speaking-state analysis.

Expected work:

- shot detection;
- visible face tracks;
- mouth-motion evidence;
- visible-speaker association;
- listening-state evidence;
- off-screen speech;
- multiple-face handling;
- and uncertainty.

This phase may move earlier if audio-only limitations materially block participant analysis.

### Phase 14: Evidential and factual grounding

**Goal:** Distinguish inferential quality from factual support and contradiction.

Expected work:

- source citation;
- external-reference boundaries;
- evidence claims;
- factual-verification status;
- disputed sources;
- temporal validity;
- domain limitations;
- and provenance-preserving grounding.

This phase must not collapse disagreement into automated truth declaration.

### Phase 15: Extended reasoning coverage

**Goal:** Expand beyond the first conservative ruleset.

Possible areas:

- causal arguments;
- analogies;
- probabilistic reasoning;
- statistical interpretation;
- source authority;
- definitional drift;
- scope changes;
- suppressed alternatives;
- and complex burden interactions.

Each extension should be separately evaluated.

### Phase 16: Long-form and multi-session discourse

**Goal:** Support arguments and participant positions that develop across hours or multiple recordings.

Expected work:

- persistent claims;
- long-distance contradiction;
- topic segmentation;
- session linkage;
- position evolution;
- correction history;
- and cross-recording comparison.

### Phase 17: Evaluation and calibration program

**Goal:** Measure whether outputs are reliable, useful, and consistently applied.

Expected work:

- annotated evaluation corpus;
- independent reviewers;
- inter-annotator agreement;
- adjudication agreement;
- rule-specific precision and recall;
- confidence calibration;
- demographic and format analysis;
- adversarial cases;
- and published limitations.

### Phase 18: Operational packaging

**Goal:** Prepare Ratiocinatus for repeatable local use.

Expected work:

- installation;
- model management;
- hardware inspection;
- job orchestration;
- resumable execution;
- project workspaces;
- export;
- documentation;
- diagnostics;
- and user-facing application design.

---

## 19. Phase Policy

The phase sequence is guidance, not an immutable contract.

A phase may be:

- split;
- merged;
- narrowed;
- deferred;
- reordered;
- repeated;
- or replaced by a corrective subphase.

Each implementation work order should state:

- which sections of this design document it implements;
- what remains out of scope;
- which assumptions it tests;
- which artifacts it may create or alter;
- which compatibility boundaries must be preserved;
- what evidence constitutes completion;
- and what findings should trigger design revision.

Completion of a phase should not be declared merely because code exists.

Each phase should normally include:

- implementation;
- tests;
- fixtures;
- reports;
- replay evidence;
- negative cases;
- documentation;
- and a clear statement of limitations.

---

## 20. Initial Technical Expectations

The initial implementation is expected to use:

- Python;
- local filesystem workspaces;
- SQLite where indexed query is useful;
- canonical JSON or JSON Lines artifacts;
- versioned schemas;
- command-line operations;
- local model providers;
- and FFmpeg-based media processing.

The project should prefer:

- explicit contracts over loosely structured dictionaries;
- append-only provenance over destructive mutation;
- resumable stages over monolithic runs;
- deterministic code over model judgment where both are feasible;
- evidence references over copied prose;
- bounded recomputation over full-pipeline repetition;
- and provider boundaries over direct dependency coupling.

A graphical review interface will likely become necessary, but it should not precede stable underlying artifacts and operations.

---

## 21. Major Risks

### 21.1 Transcript error

Incorrect words may produce incorrect propositions and invalid calls.

Possible mitigations:

- confidence thresholds;
- review queues;
- alternative transcripts;
- source playback;
- and prohibition on penalties from insufficiently reliable spans.

### 21.2 Speaker misattribution

A valid call assigned to the wrong participant is materially harmful.

Possible mitigations:

- strict separation of clustering from identity;
- explicit unknown state;
- review;
- reference evidence;
- and conservative identity binding.

### 21.3 Argument reconstruction error

The system may strengthen, weaken, complete, or misread an argument.

Possible mitigations:

- source-linked propositions;
- inferred-premise marking;
- alternative interpretations;
- bounded context;
- and human review.

### 21.4 False formalization

Natural-language reasoning may be forced into a formal structure that does not represent the speaker's actual position.

Possible mitigations:

- formalize only when sufficiently supported;
- retain informal representations;
- expose assumptions;
- and allow indeterminate outcomes.

### 21.5 Fallacy-label abuse

Named fallacies may be applied mechanically without establishing the actual defect.

Possible mitigations:

- explicit applicability conditions;
- defect-specific explanation;
- separation of labels from findings;
- counterexamples;
- and rule-specific evaluation.

### 21.6 Score false precision

Numerical outputs may imply more certainty than the analysis supports.

Possible mitigations:

- component scores;
- confidence bands;
- unresolved-call counts;
- policy disclosure;
- and restrained numerical precision.

### 21.7 Automation bias

Viewers may defer to the referee because it appears technical or neutral.

Possible mitigations:

- visible uncertainty;
- appeal history;
- disclosure;
- review status;
- evidence access;
- and avoidance of claims of perfect neutrality.

### 21.8 Model inconsistency

The same model may classify similar passages differently.

Possible mitigations:

- deterministic settings where possible;
- constrained schemas;
- repeated evaluation;
- caching;
- model versioning;
- and rule-based validation.

### 21.9 Long-recording scale

Hours of video may exceed memory, context, or practical processing limits.

Possible mitigations:

- chunking;
- incremental artifacts;
- resumable stages;
- bounded retrieval;
- caching;
- and staged GPU use.

### 21.10 Licensing and distribution

Models, datasets, and dependencies may limit redistribution or commercial use.

Possible mitigations:

- dependency inventory;
- license review;
- provider boundaries;
- optional components;
- and separation of code from externally acquired model files.

### 21.11 Defamation and reputational harm

Incorrect public-facing calls or scores may materially affect participants.

Possible mitigations:

- conservative release policy;
- confidence thresholds;
- mandatory review for publication;
- appeals;
- evidence access;
- and prominent disclosure of limitations.

### 21.12 Privacy and consent

Recorded material may include people who did not consent to biometric or behavioral analysis.

Possible mitigations:

- source eligibility policy;
- local-only processing;
- restricted identity features;
- retention controls;
- and explicit publication standards.

---

## 22. Open Questions

The following questions should remain explicitly open at project inception:

- Which discourse formats should be supported first?
- Should the first proof use a debate, interview, hearing, or controlled recording?
- How should the system distinguish factual grounding from logical execution?
- Which first rules can be adjudicated reliably?
- What constitutes sufficient confidence for a public-facing call?
- When is an omitted premise permissible to infer?
- How should charitable interpretation be balanced against fidelity to the spoken record?
- How should burden of proof be assigned?
- How should question quality affect responsiveness calls?
- How should interruptions and incomplete turns be treated?
- Which score dimensions are useful without becoming misleading?
- Should aggregate scores be shown by default?
- What level of review is required before rendering?
- How should external factual sources be selected and versioned?
- Which open-source licenses are compatible with intended distribution?
- How should privacy, consent, defamation, and reputational risk be addressed?
- What parts of the analytical package should be portable and independently verifiable?
- Which outputs should be considered machine proposals, reviewer findings, or publication-ready conclusions?
- How should later corrections propagate into already rendered editions?

These questions should be resolved through implementation evidence and explicit policy, not buried in code.

---

## 23. Initial Proof Strategy

The first convincing proof should be deliberately small.

It should not attempt to adjudicate a multi-hour political debate.

A suitable proof may use:

- a short recording;
- two or three clearly identified speakers;
- clean audio;
- several explicit claims;
- at least one direct question;
- one clear answer;
- one clear contradiction;
- one supported conclusion;
- and one unresolved ambiguous exchange.

The proof should demonstrate the complete chain:

1. source ingestion;
2. timestamped transcript;
3. speaker attribution;
4. discourse construction;
5. proposition construction;
6. argument graph construction;
7. rule application;
8. referee call;
9. score effect;
10. rendered annotation;
11. replay;
12. audit report.

The value of the proof lies in traceability, not spectacle.

---

## 24. Design Document Maintenance

This document should use disciplined versioning.

Each revision should record:

- date;
- responsible author or agent;
- sections changed;
- reason for change;
- implementation or evaluation evidence motivating the change;
- compatibility implications;
- and unresolved consequences.

Implementation reports may recommend design changes.

A work order should not silently redefine project architecture. Material changes should first be reflected here or recorded as an explicit provisional deviation.

Detailed contracts, rule definitions, dependency decisions, ethics policy, and evaluation procedures should eventually live in separate referenced documents.

---

## 25. Decision Records

Material design decisions should eventually be recorded as separate architecture or design decision records.

Candidate subjects include:

- canonical artifact format;
- persistence model;
- stable identifier scheme;
- provider boundary contracts;
- initial transcription provider;
- initial diarization provider;
- ruleset versioning;
- review authority;
- score aggregation policy;
- publication eligibility;
- and rendering disclosure standards.

This document should remain readable as a project-level design reference rather than becoming a repository for every low-level decision.

---

## 26. Current Design Position

Ratiocinatus is presently an architectural concept with a viable local-first implementation path.

The materials currently available are adequate for initial development:

- Python;
- open-source audiovisual processing;
- local transcription;
- local diarization;
- local embeddings;
- local structured generation through models up to approximately 14B parameters;
- deterministic rules;
- graph structures;
- and local rendering.

The primary difficulty is not raw model capacity.

The primary difficulty is maintaining a trustworthy separation among:

- what was observed;
- what was inferred;
- what was adjudicated;
- what was scored;
- what was reviewed;
- and what was presented to the viewer.

The project should proceed only by preserving that separation.

---

## 27. Expected Next Documents

Following acceptance of this design document, the expected next documents are:

1. `docs/work_orders/phase_00.txt`
2. Initial dependency and licensing assessment
3. Contract and artifact naming guide
4. Initial rules-of-adjudication outline
5. Evaluation-fixture proposal
6. Risk, ethics, and publication policy
7. Architecture decision record template

The Phase 0 work order should implement the project foundation and evidentiary kernel without prematurely implementing debate judgment or scoring.

---

## 28. Revision History

| Version | Status | Summary |
|---|---|---|
| 0.1.0 | Initial design reference | Establishes project vision, principles, architecture, provisional phase plan, risks, and maintenance policy. |
