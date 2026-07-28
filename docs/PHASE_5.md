# Phase 5: Discourse-act construction

Phase 5 derives source-grounded proposals about conversational function from a
declared Phase 4 utterance corpus. It does not modify source media, transcript,
speaker evidence, utterance segmentation, text, attribution, quotation
evidence, or review history.

A discourse act is not an utterance, semantic claim, or argument role:

- an utterance is the immutable Phase 4 source-grounded speech unit;
- a discourse act proposes what a span appears to do conversationally;
- a relation links that act to a bounded conversational target;
- a semantic claim is later proposition-level content; and
- an argument role is a later support, attack, premise, or conclusion judgment.

An assertion label does not establish truth. An answer label does not establish
adequacy. A rebuttal label does not establish success. A procedural flag does
not establish violation or blame. Ambiguous and unclassified function are valid
outcomes.

## First slice: contracts and controlled vocabulary

The foundation slice provides:

- a closed, versioned vocabulary of 145 act types across thirteen families;
- assertive, question, answer, objection, rebuttal, concession,
  qualification, definition, example, quotation, procedural, other, and
  unknown families;
- exact evidence spans with Phase 4 text-view, character-offset,
  transcript-word, source-interval, role, and confidence addressing;
- explicit identified, probable, multiple-candidate, implicit, and unresolved
  relation-target states;
- multidimensional act, span, target, selection, question, answer, quotation,
  and procedural confidence;
- provider observations that remain non-authoritative proposals;
- multi-label candidate sets with compatible, excluded, selected, rejected,
  deferred, and unresolved candidates;
- canonical selected acts that retain their observations, candidates, spans,
  alternatives, targets, confidence, and review state;
- immutable discourse-run and corpus lineage over the exact Phase 4 corpus
  digest;
- explicit unclassified utterance coverage rather than forced labels;
- correction-propagation policy that invalidates affected spans while
  preserving justified unaffected identifiers;
- typed integrity findings and strict sealed persistence; and
- an explicit unavailable-provider boundary exposed through
  `discourse-provider list` and `discourse-provider inspect`.

The runtime validator reproduces exact evidence text from Phase 4 offsets,
checks transcript-word ownership and source-interval containment, refuses
unknown utterances and current artifact targets, verifies canonical candidate
selection, requires every Phase 4 utterance to be classified or explicitly
unclassified, and compares the complete Phase 4 corpus digest.

## Second slice: deterministic high-precision baseline

The deterministic baseline now:

- applies twenty-seven versioned lexical and structural rules without invoking
  a provider;
- detects explicit question forms, procedural formulas, concessions,
  qualifications, definitions, examples, assertive markers, and declared Phase
  4 quotation uses;
- requires more than punctuation or generic declarative form;
- emits exact Phase 4 display-text offsets and source-media evidence for every
  observation;
- supports multiple compatible observations from one utterance;
- preserves unsupported utterances in an explicit unclassified inventory;
- records uncalibrated rule strength separately across confidence dimensions;
- consumes Phase 4 quotation evidence without changing acoustic attribution;
- bounds observations per utterance;
- replays deterministically and persists sealed run/report pairs; and
- exposes `discourse baseline-build`, `baseline-validate`,
  `baseline-inspect`, `list-observations`, and `list-unclassified` operations.

Partial-span media timing remains at utterance resolution when no
word-to-character alignment is available. That limitation is explicit. The
baseline qualifies deterministic mechanics, not natural-conversation accuracy.

## Third slice: bounded provider-assisted classification

The provider-assisted slice now:

- serializes one target and the exact members of one bounded-temporal Phase 4
  context window into every request;
- retains Phase 4 corpus, context bundle, context window, text-view,
  source-interval, provider/model, seed, policy, and configuration lineage;
- accepts multiple ranked structured proposals with spans, targets,
  alternatives, supporting evidence, contrary evidence, modifiers, and native
  confidence;
- validates family/type compatibility while normalizing proposals into
  immutable, non-authoritative observations;
- requires every provider span to reproduce exact target display text;
- confines identified utterance targets and alternatives to the supplied
  context;
- preserves unavailable confidence instead of fabricating a score;
- retains a digest for raw structured output;
- retries timeouts only within the declared policy bound;
- records typed provider, model, timeout, malformed-output, and validation
  failures without forcing classification;
- persists and validates normalized provider evidence without reinvocation; and
- exposes `provider-build`, `provider-validate`, `provider-inspect`,
  `list-provider-observations`, and `list-provider-failures` operations under
  the `discourse` command.

No production discourse model is selected. Controlled provider fixtures qualify
request, normalization, retry, failure, persistence, and integrity mechanics,
not natural-conversation performance.

## Fourth slice: candidate consolidation

The consolidation slice now:

- groups same-type observations only when their Phase 4 evidence spans overlap
  by the declared threshold;
- retains deterministic-only, provider-only, and corroborated provenance;
- treats corroboration as an explicit uncalibrated ranking input rather than
  authority;
- selects compatible candidates together for genuinely multi-label utterances;
- models narrow, versioned mutually exclusive candidate groups;
- retains rejected and deferred alternatives;
- leaves close exclusive alternatives unresolved without a canonical act;
- preserves provider failures without allowing them to erase deterministic
  evidence;
- constructs the canonical discourse corpus with complete observation,
  candidate, span, target, confidence, review, and Phase 4 lineage;
- requires every Phase 4 utterance to be canonically classified or explicitly
  unclassified;
- replays and persists a sealed consolidation run, discourse corpus, and
  report; and
- exposes `consolidate-build`, `consolidate-validate`,
  `consolidate-inspect`, `list-candidates`, `list-canonical-acts`, and
  `list-ambiguous` operations under the `discourse` command.

Controlled fixtures qualify evidence grouping, selection, ambiguity,
persistence, and integrity mechanics. Selection scores are not probabilities,
and natural-conversation classification accuracy remains unqualified.

## Fifth slice: question-answer construction

The question-answer slice now:

- creates a stable question artifact from every canonical question act;
- retains exact question spans, structural type, requested information or
  decision wording, explicit alternatives, surface presupposition markers,
  addressee state, domain, scope, confidence, and review;
- treats surface presupposition markers as review evidence without inferring
  loadedness, fairness, misleadingness, or answerability;
- creates one relation artifact for every canonical answer act;
- gives explicit normalized targets precedence over temporal candidates;
- treats a single preceding question in the exact bounded-temporal context as
  probable and review-required rather than identified;
- retains multiple preceding questions as alternative targets;
- preserves unsupported targets as unresolved;
- refuses to link an answer to a later question without explicit target
  evidence;
- represents direct, partial, qualified, indirect, affirmative, negative,
  corrected, premise-rejecting, deferred, refused, inability, and unresolved
  answer forms;
- links qualification acts from the same answer utterance;
- represents several utterances jointly answering one question and supports
  explicitly grounded answers to several questions;
- emits no responsiveness, adequacy, completeness, or evasion score;
- replays and persists sealed question-answer run and report artifacts; and
- exposes `question-answer-build`, `question-answer-validate`,
  `question-answer-inspect`, `list-questions`, `list-answer-relations`, and
  `list-unresolved-answers` operations under the `discourse` command.

Controlled fixtures qualify structural construction, bounded targeting, state
preservation, persistence, and integrity mechanics. They do not qualify
natural-conversation question or answer accuracy.

## Sixth slice: objection, rebuttal, concession, and qualification

The argument-relation slice now:

- creates one bounded relation record from every canonical objection and
  rebuttal act;
- distinguishes challenge dimensions and rebuttal methods without assessing
  rebuttal success;
- retains exact supporting and challenged spans, target acts and utterances,
  qualifications, alternatives, temporal distance, confidence, review, and
  unresolved issues;
- gives explicit normalized targets precedence;
- treats a single canonical act in the nearest prior bounded-context utterance
  as probable and review-required;
- preserves multiple nearest acts as alternative targets;
- prevents an explicitly unresolved rebuttal from being promoted by temporal
  proximity;
- creates concession structures with exact conceded material, retained
  restrictions, conditions, exceptions, qualification links, and target state;
- creates qualification structures with typed dimension, exact scope, target
  spans, conditions, exceptions, and ambiguous same-utterance scope;
- performs no factual adjudication or intent inference;
- replays and persists sealed run and report artifacts; and
- exposes `argument-relations-build`, `argument-relations-validate`,
  `argument-relations-inspect`, `list-objections`, `list-rebuttals`,
  `list-concessions`, `list-qualifications`, and
  `list-unresolved-relations` operations under the `discourse` command.

Controlled fixtures qualify bounded targeting, ambiguity, modifier structure,
persistence, and integrity mechanics. They do not qualify natural-conversation
relational accuracy.

## Seventh slice: definitions, examples, and quotation uses

The lexical and quotation-use slice now:

- creates local definition records with defined expression, exact defining
  text, type, scope, applicable context, exclusions, competitors, challenge
  links, confidence, and review;
- prevents definition reuse outside declared scope without later evidence;
- keeps competing definitions linked without selecting a winner;
- creates example records with exact spans, example type, structural reality
  state, temporal references, candidate generalizations, confidence, and
  review;
- treats a single nearest prior generalization as probable and multiple acts
  as alternatives;
- explicitly prohibits example representativeness and proof findings;
- creates quotation-use records from every canonical quotation act;
- consumes matching Phase 4 quoted spans, attribution, speaker, source, and
  embedded-speech provenance;
- keeps acoustic speaker, quoting speaker, attributed speaker, and original
  source distinct;
- prohibits mutation of Phase 4 acoustic attribution;
- preserves unmatched quotation uses as review-required;
- replays and persists sealed run and report artifacts; and
- exposes `lexical-structures-build`, `lexical-structures-validate`,
  `lexical-structures-inspect`, `list-definitions`, `list-examples`,
  `list-quotation-uses`, and `list-unresolved-lexical-structures` operations
  under the `discourse` command.

Controlled fixtures qualify structural extraction, bounded targeting, Phase 4
quotation consumption, persistence, and integrity mechanics. They do not
qualify natural-conversation semantic accuracy.

## Eighth slice: descriptive procedural state

The procedural slice now:

- creates source-time-ordered events from canonical procedural acts and
  procedural questions;
- retains each source act, utterance, source intervals, evidence spans,
  observed Phase 4 attribution, target state, effects, confidence, and review;
- creates exactly one immutable state snapshot from every event;
- distinguishes observed acoustic speaker from procedurally recognized
  speaker;
- leaves pronoun-addressed floor recipients unresolved without explicit
  target evidence;
- represents pending questions, active response intervals, moderator
  instructions, warnings, expiration, clarification requests, topic
  transitions, technical interruptions, and unresolved events;
- opens response intervals on floor grants and closes them on explicit turn
  yield or time expiration;
- links every state change to a discourse act and source-media interval;
- constrains violation, fault, blame, and sanction assignments to false or
  zero;
- replays and persists sealed run and report artifacts; and
- exposes `procedural-state-build`, `procedural-state-validate`,
  `procedural-state-inspect`, `list-procedural-events`,
  `list-procedural-snapshots`, and `list-unresolved-procedural-events`
  operations under the `discourse` command.

Controlled fixtures qualify ordering, transition, attribution, persistence,
and integrity mechanics. They do not qualify natural-conversation procedural
accuracy.

## Ninth slice: append-only review and correction propagation

The review and propagation slice now:

- records approve, reject, add, revise, relink, unlink, and defer actions in
  immutable successor ledgers;
- retains prior and proposed state, author, timestamp, rationale, evidence,
  certainty, resulting review status, and a new discourse-view version;
- never modifies the Phase 4 utterance corpus;
- derives evidence-rich queues for low-confidence, incompatible, unresolved,
  correction-affected, and integrity-sensitive analytical problems;
- exposes source intervals, displayed text, speaker attribution, context, acts,
  spans, targets, alternatives, confidence, and proposed review actions;
- detects Phase 4 text, boundary, attribution, quotation, interruption, and
  continuation changes;
- invalidates dependent spans, observations, candidates, and acts for text or
  boundary changes;
- preserves classification identifiers for display-label-only speaker changes;
- requires explicit identity-specific dependency before substantive attribution
  changes invalidate classification;
- records relation-target, procedural-state, and review-queue rebuild work;
- preserves unaffected act identifiers and machine proposals;
- persists and validates sealed ledgers, queues, impact runs, and reports; and
- exposes review and propagation build, append, validate, and inspect operations
  under the `discourse` command.

Controlled fixtures qualify append-only history, source protection, selective
invalidation, identity-dependency behavior, evidence-rich queues, replay, cache
reuse, and tamper detection. They do not qualify reviewer agreement or
natural-conversation classification accuracy.

## Tenth slice, part one: controlled evaluation

The controlled evaluation layer now:

- defines sealed source-grounded reference acts, evidence spans, targets,
  alternatives, unresolved outcomes, preparation provenance, and strata;
- declares policy for span overlap, compatible multi-label acts, nested acts,
  unresolved targets, rhetorical questions, incomplete utterances, overlap,
  reviewed references, and confidence bins;
- reports every one of the 28 required metric dimensions;
- marks metrics without eligible reference evidence as not applicable rather
  than perfect;
- measures family and type precision, recall, and F1;
- measures exact and partial multi-label agreement;
- measures one-to-one evidence-span precision, recall, and IoU;
- measures relation, question, answer, objection, rebuttal, concession,
  qualification, definition, example, quotation, and procedural behavior;
- measures alternative recall, confidence reliability, unknown appropriateness,
  propagation completeness, unaffected-ID stability, and review impact;
- stratifies results by declared conversational condition;
- separates synthetic mechanics from measured natural-conversation evidence;
- persists, reloads, validates, and reuses sealed evaluation artifacts; and
- exposes `evaluate`, `evaluation-validate`, and `evaluation-inspect` commands.

Controlled fixtures qualify deterministic metric mechanics, not-applicable
handling, propagation and review measurement, persistence, and tamper refusal.
They do not qualify natural-conversation discourse accuracy.

## Tenth slice, part two: portable export and stage-local recovery

The export and recovery layer now:

- packages nineteen sealed artifacts representing all eleven required discourse
  views;
- includes the complete schema inventory and relative prior-phase references;
- records canonical byte sizes and SHA-256 digests in a sealed manifest;
- strict-loads and lineage-checks every artifact without provider execution;
- refuses missing, corrupt, unsupported, or mixed-version package entries;
- reloads the complete portable artifact inventory provider-free;
- separates fourteen material recovery boundaries, including deterministic and
  provider analysis caches;
- validates every cache entry before reuse;
- resumes missing stages and quarantines corrupt or lineage-invalid stages
  before rebuild;
- invalidates only dependency-graph descendants;
- preserves a valid provider cache after deterministic-only changes;
- fingerprints protected Phase 4 and source evidence before and after recovery;
- requires all twenty-five typed negative proofs for a complete recovery report;
- exposes `export`, `export-validate`, `export-reload`, and `recovery-inspect`
  commands; and
- persists recovery evidence without modifying prior-phase sources.

Controlled fixtures qualify complete provider-free reload, cache reuse, digest
and mixed-lineage refusal, quarantine/rebuild, missing-stage resume, transitive
invalidation, protected-source stability, and negative-proof inventory.

## Tenth slice, part three: long-recording and completion

The final qualification layer now:

- processes a virtual 7,201-second recording incrementally across 121 chunks;
- bounds active context at twelve utterances and relation search at twenty;
- proves deterministic context retrieval, cross-chunk continuity, unique act
  ownership, interruption/resume, cache replay, recovery, export/reload, final
  integrity, and bounded active-state memory;
- invokes no provider and makes no natural-discourse accuracy claim;
- aggregates corpus, configuration, Phase 4 lineage, act, span, relation,
  alternative, confidence, review, propagation, evaluation, recovery, memory,
  regression, and schema measurements;
- preserves separate evidence classes for deterministic rules, provider
  proposals, selected machine analysis, human review, measured evaluation,
  synthetic mechanics, integrity validation, and future expectations;
- evaluates exactly twenty-four ordered exit gates;
- leaves gates pending when evidence or regression coverage is missing;
- refuses tampered completion reports;
- persists paired machine-readable and human-readable completion reports; and
- exposes `phase5-long` and `phase5-report` build, validate, and inspect tools.

Controlled fixtures qualify long-recording and completion mechanics. Synthetic
marker acts do not establish natural-conversation discourse quality.

## Phase status

Phase 5 implementation and all twenty-four exit gates are complete. The
portable, integrity-checked discourse corpus is ready to serve as input to
later proposition, argument, rule, and adjudication phases without treating
conversational function as factual truth, argumentative success, speaker
intent, credibility, violation, or participant merit.
