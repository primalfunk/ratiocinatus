# Phase 4: Speaker-attributed utterance corpus

Status: In progress  
Target application version: 0.6.0  
Work order: [`work_orders/phase_04.txt`](work_orders/phase_04.txt)

Phase 4 derives stable, source-addressed utterance records from compatible
Phase 2 transcript evidence and Phase 3 participant-speech evidence. An
utterance is an analytical grouping: it need not be a sentence, a complete
thought, a transcript segment, a speaker turn, or a proposition.

## Evidence boundary

Phase 4 does not rewrite source media, transcript evidence, diarization,
clusters, identity hypotheses, or manual bindings. It records the exact
transcript and identity-view versions used by every utterance corpus.

Speaker attribution may remain machine-clustered, hypothesized, manually bound,
conflicting, or unknown. A quoted speaker is not necessarily the acoustic
speaker. An interruption flag describes temporal structure and does not
establish intent, blame, dominance, or conversational quality.

## First slice: contracts and policy

The foundation slice defines strict versioned contracts for:

- deterministic segmentation and text normalization policy;
- source-addressed utterance components;
- raw, corrected, display, minimally normalized, and review text views;
- explicit speaker attribution and uncertainty;
- complete and incomplete speech classifications;
- interruption, repair, overlap, quotation, review, and speech-source states;
- stable utterance runs and portable utterance corpora;
- canonical transcript-word ownership;
- typed integrity findings and results; and
- machine-readable corpus reports.

The contracts refuse unsupported versions, incompatible lineage, duplicate
canonical word ownership, invalid interval domains, forced targets for unknown
attribution, insufficient conflicting candidates, incoherent display views,
and interrupted completeness without an interruption state.

## Second slice: deterministic initial segmentation

The initial segmentation slice now:

- aligns canonical Phase 2 words to Phase 3 attribution spans;
- records direct segment, word, speaker-turn, and speaker-observation lineage;
- gives every canonical word exactly one utterance owner;
- resolves cross-boundary words by maximum temporal intersection;
- flags equal-support ties for review;
- merges adjacent compatible spans only within the declared gap policy;
- preserves reviewed, machine, conflicting, and unknown attribution;
- persists, reloads, validates, and reuses stable corpus artifacts; and
- exposes structured `utterance build`, `validate`, `inspect`, and `list`
  operations.

The segmentation is a deterministic structural proposal, not a claim of
natural-language segmentation accuracy. No linguistic model, claim extraction,
argument analysis, adjudication, credibility analysis, intent inference, or
participant judgment is introduced.

## Third slice: completeness and disfluency analysis

The structural-analysis slice now:

- creates one sealed completeness assessment per utterance;
- uses only lexical presence, duration, punctuation, and source-boundary
  evidence for deterministic classifications;
- preserves `unknown` whenever bounded signals are insufficient;
- detects source-addressed filler, hesitation, repetition, false-start, and
  explicit-correction candidates;
- represents bounded self-repair candidates with distinct reparandum, marker,
  and repair word identifiers;
- preserves raw utterance wording and all canonical word ownership;
- validates that candidates never cross utterance ownership boundaries;
- persists, reloads, validates, and safely reuses analysis artifacts; and
- exposes `utterance analyze`, `analysis-validate`, `analysis-inspect`,
  `list-incomplete`, `list-disfluencies`, and `list-self-repairs`.

These labels describe observable structural candidates. They do not diagnose
a speech condition, infer intent or mental state, score a participant, or
establish linguistic accuracy. Grammatical and discourse-level completion
remain unresolved rather than being guessed.

## Fourth slice: interruption, overlap, and continuation

The temporal-relation slice now:

- records deterministic adjacency with signed gaps and explicit simultaneous
  intervals;
- projects every Phase 3 overlap interval into the utterance corpus;
- distinguishes separated, mixed, uncertain-attribution, and untranscribed
  overlap evidence;
- constructs simultaneous interruption candidates only with explicit overlap
  support;
- constructs immediate-takeover candidates only from bounded temporal and
  incomplete-terminal evidence;
- links possible resumptions using explicit attribution, bounded elapsed time,
  and intervening activity without semantic similarity;
- rejects continuation cycles and impossible temporal ordering;
- persists, reloads, validates, and safely reuses relation artifacts; and
- exposes `utterance relate`, `relations-validate`, `relations-inspect`, and
  relation-specific review-list operations.

Supportive interjection, backchannel, moderator cutoff, technical cutoff, and
audience interruption remain representable but are not inferred. Temporal
relations do not establish intent, blame, dominance, or conversational quality.

## Fifth slice: bounded turn repair

The turn-repair slice now:

- detects source-addressed conflicts among transcript words and segments,
  speaker boundaries and turns, attribution spans, and utterance ownership;
- records supporting and contrary evidence for every conflict and proposal;
- represents split, merge, boundary move, word reassignment, detachment,
  unattributed assignment, mixed preservation, and unresolved actions;
- emits concrete boundary moves and turn splits only from bounded timestamp
  evidence;
- preserves mixed, overlap-affected, unknown, and equal-support evidence;
- prohibits automated word reassignment and source mutation;
- appends accepted, rejected, and deferred manual decisions;
- requires accepted decisions to create sealed predecessor-linked successors;
- persists, reloads, validates, and safely reuses repair runs; and
- exposes `repair-build`, `repair-validate`, `repair-decide`, `repair-inspect`,
  and repair-specific review queues.

Successors project accepted changes while retaining every predecessor artifact.
They do not rewrite Phase 2 transcripts, Phase 3 diarization or speaker views,
or the original utterance corpus.

## Sixth slice: quotation and embedded speech

The quotation and source-evidence slice now:

- records bounded quotation spans with character, word, and media addressing;
- requires an explicit attribution or structural cue in addition to quotation
  marks;
- distinguishes direct, partial, paraphrase, attributed proposition, reported
  speech, reading, recitation, imitation, hypothetical, self, and uncertain
  quotation types in strict contracts;
- keeps acoustic and quoted-speaker targets in separate fields;
- prohibits automatic paraphrase inference and quoted-identity binding;
- represents embedded, replayed, remote, synthesized, and uncertain sources;
- requires explicit transcript markers for automatic source candidates;
- persists, reloads, validates, and safely reuses quotation evidence; and
- exposes `quotation-build`, `quotation-validate`, `quotation-inspect`, and
  quotation/source review queues.

A quotation or embedded-source candidate never changes the original utterance
text, acoustic speaker attribution, or source classification.

## Seventh slice: canonical speaker-attributed transcript views

The transcript-view slice now:

- projects all utterances into machine-cluster, reviewed-identity,
  unknown-preserving, correction-aware, overlap-expanded, and compact views;
- retains utterance identifiers, source and normalized intervals, attribution
  status, review status, and evidence references in every view;
- renders interruption, continuation, overlap, quotation, embedded-source,
  repair, uncertainty, conflict, and review markers;
- preserves temporal partial order through explicit overlap groups and lanes;
- emits sealed loss records whenever a sequential view linearizes overlap or a
  requested label/text surface is unavailable;
- preserves unknown and conflicting speakers rather than guessing identity;
- persists, reloads, validates, and safely reuses all six views; and
- exposes `view-build`, `view-validate`, `view-inspect`, `view-list`, and
  `view-render` operations.

These are presentation derivatives, not replacements for the utterance corpus
or any upstream transcript, diarization, repair, or quotation evidence.

## Eighth slice: deterministic bounded context windows

The context-window slice now:

- generates preceding, following, same-speaker history, current-turn,
  exchange, question-response, interruption, quotation, and bounded-temporal
  windows for every utterance;
- preserves source intervals, canonical sequence positions, temporal groups,
  overlap lanes, and simultaneous-utterance references;
- enforces maximum utterance-count, token-estimate, and source-duration
  budgets through deterministic selection;
- supports speaker balancing and question, interruption, quotation, and
  simultaneous-overlap preservation priorities;
- refuses to clip a target utterance that cannot fit the declared budget;
- distinguishes structural unavailability from budget truncation;
- records every budget-omitted utterance and states when the complete exchange
  was not considered;
- persists, reloads, validates, and safely reuses policy-specific windows; and
- exposes `context-build`, `context-validate`, `context-inspect`,
  `context-list`, `context-show`, and `list-truncated-context` operations.

Context windows are source projections for later consumers, not free-form
prompts or replacements for the utterance corpus.

## Ninth slice: correction propagation and append-only review

The propagation and review slice now:

- compares validated predecessor and rebuilt successor Phase 4 chains;
- maps utterances by canonical word ownership with bounded temporal fallback;
- distinguishes text, timing, speaker-attribution, segmentation,
  display-label, and source-lineage changes;
- records unchanged, rebuilt, split, merged, removed, added, and unresolved
  mapping dispositions;
- selectively invalidates affected analysis, relation, repair, quotation,
  transcript-view, and context-window artifacts;
- preserves every predecessor artifact and explicitly records corpus-scoped
  identifier changes;
- represents all fifteen required manual review actions through sealed,
  predecessor-linked append-only ledgers;
- rejects unknown targets and inconsistent review lineage;
- builds evidence-complete problem queues with source intervals, media
  extraction commands, local context, speaker evidence, proposed actions, and
  competing alternatives; and
- exposes propagation, review-ledger, and review-queue CLI operations.

Manual review never erases the machine proposal, and propagation never treats
stale dependent views or windows as current successor evidence.

## Tenth slice: evaluation, recovery, export, and completion

The closure slice now:

- evaluates all twenty required metrics against controlled, source-addressed
  references and reports non-applicable metrics honestly;
- exports provider-free portable bundles with relative prior-phase references,
  complete schemas, typed reload, digest validation, and deterministic replay;
- exercises reuse, resume, quarantine, rebuild, and transitive invalidation at
  all ten Phase 4 processing boundaries;
- passes the exact twenty-two required negative proofs without modifying
  protected source or prior-phase evidence;
- qualifies 7,201,000,000 microseconds across 121 virtual chunks with bounded
  working state, stable cross-chunk construction, continuation, boundary
  interruption, contexts, cache replay, recovery, export reload, and no
  duplicate ownership;
- inventories thirteen machine-and-human qualification pairs by evidence class;
- exports 320 runtime contract schemas;
- passes the complete 250-test repository regression suite; and
- closes all nineteen exit gates in an integrity-sealed completion report.

Long-recording evidence qualifies deterministic mechanics, not natural-speech
accuracy. Controlled evaluation does not establish general performance, and
optional analytical providers remain outside the portable evidence boundary.

## Completion

Phase 4 is complete. The canonical evidence is
`reports/phase-4-completion.json` with its human-readable companion. Phase 5 may
consume the utterance corpus but must preserve Phase 4 source lineage,
uncertainty, quotation/acoustic-speaker separation, and non-judgment boundary.