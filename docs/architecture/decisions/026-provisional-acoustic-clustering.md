# ADR 026: Provisional acoustic clustering and consistency

Status: Accepted  
Date: 2026-07-26

## Decision

Normalize provider acoustic labels into provisional clusters only when the
provider explicitly declares available speaker-clustering capability. Derive
cluster identifiers from the clustering configuration and member observation
identifiers, never from participant names or display labels.

Preserve observations with missing labels, unusable evidence, or insufficient
duration as explicitly unclustered. Require clustered and unclustered evidence
to form a complete, disjoint partition of canonical speaker observations.

Refuse a proposed cluster whose embeddings use incompatible model spaces,
fingerprints, dimensions, or numeric formats. Do not invent similarity values
when embedding values are protected or omitted.

Evaluate each cluster independently. A singleton has insufficient internal
evidence. A multi-observation provider-label group without independent
similarity measurements is only provisionally consistent. Multiple members of
the same cluster appearing in one explicit overlap interval are likely
over-merged.

For a simultaneous-self conflict, create an integrity-sealed, review-required
split proposal covering every member. Do not apply the split. Automatic merge
and split behavior remains disabled, and accepted proposals require a separate
successor transformation.

## Rationale

Provider acoustic labels can preserve useful within-recording voice grouping,
but they are neither calibrated identity evidence nor participant names.
Keeping cluster formation, internal consistency, and transformation proposals
separate prevents a convenient label partition from becoming false certainty
or silently rewriting the original machine result.

## Consequences

- Clusters remain valid when every participant is unknown.
- Renaming or binding a participant cannot change an acoustic cluster ID.
- Unclustered observations are successful explicit outcomes.
- Mixed embedding spaces fail before clustering.
- Every canonical membership is unique and source-addressed.
- Over-merge evidence remains unresolved until reviewed.
- Merge and split proposals preserve original clusters and do not mutate them.
- A production clustering provider still requires separate selection and
  controlled qualification.
