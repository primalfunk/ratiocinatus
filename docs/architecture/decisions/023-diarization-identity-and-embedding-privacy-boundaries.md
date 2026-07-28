# ADR 023: Diarization, identity, and embedding privacy boundaries

Status: Accepted  
Date: 2026-07-26

## Decision

Represent diarization, acoustic clustering, participant identity hypotheses,
and manual identity binding as separate evidence stages.

A diarization provider may emit provider-local voice labels, temporal turns,
overlap proposals, voice representations, and acoustic clusters. It may not
emit an authoritative participant identity. Canonical cluster identifiers are
derived independently of participant names, and changing a display label must
not invalidate acoustic evidence.

Preserve acoustic, contextual, documentary, and manual support as separate
confidence-bearing fields. Unknown or conflicting identity remains a
successful, explicit result.

Treat voice embeddings as sensitive technical evidence. The default policy
stores protected references, excludes embeddings from portable export, and
forbids embedding values in logs. An export requires a stored artifact plus an
explicit authorization reference. Manual identity binding does not itself
authorize biometric enrollment or export.

## Rationale

Diarization answers which intervals may share a voice source. Identity binding
answers which participant label a reviewer is prepared to apply within a
declared scope. Collapsing those questions would turn provider consistency into
false identity certainty and would make harmless label edits invalidate
expensive acoustic evidence.

Voice embeddings can enable reproducibility and controlled comparison, but
their biometric sensitivity requires a stricter storage and export boundary
than ordinary report metadata.

## Consequences

- Provider response contracts contain no participant identity field.
- Clusters remain usable when every participant is unknown.
- Identity hypotheses can retain competing and contrary evidence.
- Binding revisions and restorations require append-only predecessor records.
- Embedding comparisons must share an explicit model space and fingerprint.
- A later provider-selection ADR must document model provenance, licensing,
  redistribution, runtime, calibration, and controlled qualification results.
