# ADR 038: Phase 3 completion is gate-bound and evidence-classified

Status: Accepted  
Date: 2026-07-27  
Phase: 3

## Context

Phase 3 has many independently qualified artifacts. A list of passing tests is
not itself a completion proof, and combining synthetic mechanics, controlled
measurements, provider statements, and human review decisions into one
undifferentiated summary would overstate what was established.

The initial completion report left the long-recording operational gate
unqualified.

## Decision

The Phase 3 completion report inventories and hashes every required
machine-readable and human-readable qualification report. Evidence is
classified as:

- measured evaluation;
- synthetic mechanics;
- human-decision mechanics;
- presentation validation;
- provider claims; or
- future expectations.

All eighteen work-order gates are explicit and ordered. A report is complete
only when every gate is complete and no error or fatal integrity finding
exists. Missing evidence conservatively produces an `in_progress` report;
present but malformed, failed, contradictory, or mutated evidence is refused.

The report separately records provider/model disclosure, metrics, privacy and
export decisions, boundary statements, limitations, unresolved concerns,
repository state, and an integrity seal.

Completion reports are append-only successors. When new evidence changes the
report identity, the previous machine and human reports move into a
report-ID-addressed history directory, and the successor names its predecessor.

## Consequences

- Passing slices cannot silently imply phase completion.
- Synthetic provider mechanics remain distinct from measured accuracy.
- Human bindings remain decisions rather than observations.
- Provider claims cannot be presented as measured results.
- The initial report remained `in_progress` with Gate 17 pending.
- The successor incorporates the longer-than-two-hour operational
  qualification, closes Gate 17, and records Phase 3 as `complete`.
- The predecessor remains archived by report ID.
