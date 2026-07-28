# Phase 3 controlled temporal-diarization evaluation qualification

Date: 2026-07-27  
Phase: 3  
Target Phase 3 application version: 0.5.0  
Status: **PASSED**

## Qualified boundary

This slice adds independently sealed temporal references and exact-duration
evaluation of provider speaker labels against controlled local-speaker keys.
It does not evaluate participant identity.

Ten strict runtime contracts cover scoring policy, reference turns,
speaker-change boundaries, overlap intervals, reference lineage, speaker
mapping, aggregate temporal metrics, stratum metrics, the evaluation, and its
summary report.

## Measured behavior

The evaluator reports:

- diarization error rate;
- missed-speech, false-alarm, and speaker-confusion contributions;
- maximum-duration one-to-one system/reference speaker mapping;
- speaker-change precision and recall;
- boundary mean and maximum timing error;
- overlap precision, recall, intersection duration, and duration error; and
- controlled fixture strata.

An exact two-local-speaker overlap case scores zero DER, perfect boundary
matching, and perfect overlap recovery. A controlled one-label over-merge
produces nonzero confusion and missed simultaneous-speaker time without
inventing false-alarm time.

Audience, background, and non-lexical annotations are explicitly excluded by
policy. Unknown and replayed speech treatments, collar size, boundary
tolerance, overlap scoring, mapping method, and reference-label semantics are
persisted.

## Integrity and operation

Evaluation refuses incompatible reference lineage, invalid seals, evidence
outside the reference duration, an oversized mapping problem, partial caches,
and corrupt human reports. Persistence provides exact cache reuse and keeps
evaluation outside protected diarization evidence.

CLI operations evaluate, inspect, validate, and list strata.

Five focused tests and all 184 repository tests passed. Runtime schema export
contains 230 schemas plus 20 controlled-fixture schemas.

The existing Silero VAD and Torch deprecation warnings remain non-failing and
unrelated to this slice.

## Limitation

This qualifies evaluation mechanics on controlled evidence. It does not claim
general diarization, biometric recognition, or participant-identification
performance. Broader Phase 3 completion reporting and the long-recording gate
remain separate work.
