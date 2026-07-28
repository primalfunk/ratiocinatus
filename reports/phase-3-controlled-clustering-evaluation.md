# Phase 3 controlled clustering-evaluation qualification

Status: **PASSED**  
Application version: 0.4.0  
Target Phase 3 application version: 0.5.0

This slice implements controlled clustering evaluation and protected
embedding/model qualification without advancing into participant identity.

An independently supplied `DiarizationReference` assigns fixture-local speaker
keys to canonical observations. The reference is lineage-bound to one
diarization run and independently sealed. Its labels are evaluation-only and
do not appear in the source `SpeakerCluster` artifacts.

Partition accuracy uses unordered observation pairs and reports true same-
speaker joins, false merges, false splits, true separations, same-speaker
precision, recall, F1, reference coverage, and clustered-reference coverage.
Unclustered observations remain valid evidence and count as
predicted-different.

Embedding qualification separately checks compatible model space,
fingerprint, dimension, numeric format, storage disposition, safe protected
paths, content hash, and byte size. Omitted vectors may qualify only at the
metadata level. No vector values appear in contracts, reports, or CLI output.

Evaluation artifacts are immutable, integrity-sealed, cacheable only under
identical lineage and policy, and stored separately from diarization and
clustering evidence. CLI operations create, inspect, and validate evaluations.

Three focused evaluation tests, twenty focused Phase 3 tests, and all 139
repository tests passed. Schema export produced 187 runtime schemas plus 20
controlled-fixture schemas.

No production diarization or clustering provider, biometric identity claim,
participant identity, reference-voice comparison, or embedding export was
added.
