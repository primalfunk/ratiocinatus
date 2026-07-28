# ADR 033: Reviewed identity state is a layered derived view

Status: Accepted  
Date: 2026-07-27  
Phase: 3

## Context

Provider labels, canonical turns, acoustic clusters, identity hypotheses,
reference comparisons, and manual decisions have different evidentiary
meanings. A single mutable speaker-label map would erase those distinctions
and could make a manual label appear model-generated—or a model label appear
reviewed.

The manual binding ledger also permits explicit unknown outcomes and parallel
conflicting branches. View assembly must not hide either.

## Decision

Identity-view assembly produces one sealed artifact with exactly eight layers:

- raw provider diarization;
- canonical machine diarization;
- cluster consistency;
- unresolved speakers and unapplied cluster proposals;
- identity hypotheses;
- reference comparisons;
- manually reviewed identity assignments; and
- complete binding history.

The assembly pins the provider response, canonical diarization, clustering,
identity foundation, binding ledger, and optional reference-comparison run.
Each layer remains separately addressable.

The reviewed layer is derived per canonical speaker turn. A decision applies
only when both its target and its declared scope cover that turn. Original
machine labels remain in `original_machine_label`; manual labels occupy
`reviewed_label` and always begin with `REVIEWED: `. Unknown and conflict use
the reserved labels `REVIEWED: UNKNOWN` and `REVIEWED: CONFLICT`.

Independent active decisions with incompatible outcomes block the reviewed
view from participant rendering. The same participant assigned to overlapping,
independent turns also produces a blocking finding. Unresolved merge or split
proposals remain explicit findings and are never applied during view assembly.

Validation independently reconstructs the reviewed projection from the pinned
ledger. Re-sealing altered rendered labels is therefore insufficient to make a
forged view valid.

## Consequences

- Machine, inferential, comparative, and manual evidence remain distinct.
- Rendering consumers receive an explicit trust boundary.
- Unknown and conflict remain visible presentation states.
- Renaming or reviewing a participant does not force acoustic reprocessing.
- Phase 2 transcript evidence remains unchanged.
- Speaker-labeled transcript and subtitle derivatives can now declare a stable
  identity-view version in the next slice.
