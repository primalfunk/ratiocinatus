# ADR 027: Controlled clustering evaluation and embedding qualification

Status: Accepted  
Date: 2026-07-26

## Decision

Evaluate a provisional clustering partition only against an independently
supplied, integrity-sealed controlled reference. Reference speaker keys are
fixture-local partition labels. They are not participant identities, are not
copied into cluster artifacts, and cannot rename a cluster.

Measure clustering with unordered observation pairs. A pair is classified by
whether the controlled reference says it has the same speaker key and whether
the clustering run assigns both observations to the same canonical cluster.
An unclustered observation is treated as predicted-different. Report pairwise
precision, recall, F1, all four pair counts, reference coverage, and clustered
reference coverage.

Qualify embeddings separately from partition accuracy. Retain model-space,
model-fingerprint, dimension, numeric-format, storage-disposition, and artifact
integrity results without including vector values. Stored artifacts must use
safe run-relative paths and match their declared hashes and byte sizes.
Comparison eligibility requires at least two compatible, integrity-verified
stored embeddings. Omitted embeddings may qualify only at the metadata level.

Persist evaluation and report artifacts outside their source diarization and
clustering roots. Seal references, embedding qualifications, and evaluations
independently. Refuse incompatible lineage, invalid integrity, unsafe artifact
paths, and partial caches.

## Rationale

Pairwise partition metrics do not require mapping machine cluster identifiers
to names and expose false merges and false splits symmetrically. Keeping the
controlled reference inside the evaluation artifact makes its limited purpose
visible without allowing it to become an operational identity source.

Embedding integrity and embedding accuracy are different questions. A valid
protected artifact may still be unsuitable for identity inference, while
omitted vectors can preserve useful model provenance without permitting
comparison.

## Consequences

- Controlled labels never become participant identities.
- Partial references remain measurable with explicit coverage.
- False merges and false splits are separately countable.
- Model spaces and formats cannot be silently mixed.
- Protected embedding values remain outside ordinary contracts and reports.
- Qualification does not establish cross-corpus performance, biometric
  identity accuracy, or portable score calibration.
- Production provider selection remains a separate future decision.
