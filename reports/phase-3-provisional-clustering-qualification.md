# Phase 3 provisional acoustic-clustering qualification

Status: **PASSED**  
Application version: 0.4.0  
Target Phase 3 application version: 0.5.0

This slice implements deterministic Stage 4 provisional clustering and the
initial Stage 5 consistency and split-proposal boundary.

Provider acoustic labels are normalized only behind declared clustering
capability. Cluster identifiers depend on configuration and canonical
observation membership, not provider labels, participant names, or identity
bindings. Missing labels and unusable or short evidence remain explicitly
unclustered.

Every cluster records membership and turn lineage, formation policy, embedding
model space when present, temporal distribution, source coverage, observation
duration, consistency result, proposal history, status, and an independent
integrity seal. Canonical memberships and unclustered observations form a
complete disjoint partition.

Consistency analysis distinguishes insufficient evidence, provisional
consistency, and likely over-merging. Simultaneous members in explicit overlap
produce a review-required split proposal covering every member. The proposal
does not modify or supersede its source cluster.

Typed refusals cover unavailable clustering capability, mixed embedding model
spaces, incomplete caches, invalid memberships, invalid proposal targets,
invalid split partitions, and cluster-lineage cycles. Accepted merge or split
proposals require an explicit successor transformation.

The CLI can create clustering runs and inspect, validate, list clusters, and
list consistency results. Reports expose cluster, membership, unclustered,
proposal, and unresolved-conflict counts.

Four focused clustering tests, twenty focused Phase 3 tests, and all 139
repository tests passed. Schema export produced 187 runtime schemas plus 20
controlled-fixture schemas.

No production clustering model, automatic merge, automatic split, participant
identity, reference-voice comparison, or embedding export was added.
