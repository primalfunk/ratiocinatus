# ADR 062: Phase 5 export is provider-free and recovery is stage-local

## Status

Accepted.

## Context

The discourse corpus must remain inspectable after provider runtimes disappear,
and interrupted processing must resume without discarding valid evidence.
Exporting a mixture of corpus versions would create a plausible-looking but
invalid analytical package. Rebuilding every stage after any change would
unnecessarily invoke providers and churn stable artifacts.

## Decision

Portable Phase 5 export is a digest-addressed directory containing:

- nineteen sealed discourse artifacts;
- the eleven required logical discourse views;
- the complete JSON-schema inventory;
- a manifest with relative prior-phase references;
- and a sealed validation report.

Export never redistributes source media and never requires provider execution
for validation, inspection, or reload. Every entry has a relative path, byte
size, SHA-256 digest, and strict-load schema name. Validation rejects missing,
corrupt, unsupported, or mixed-version entries. Reload reconstructs all
artifacts using only the package and local contract code.

Recovery operates at fourteen persisted stage boundaries. Deterministic and
provider observations are separate cache stages. Each stage is validated before
reuse. Missing stages resume or rebuild; corrupt and lineage-invalid stages are
moved to a preserved quarantine before rebuilding. Invalidation follows an
explicit dependency graph and affects downstream stages only. A deterministic
classification change does not invalidate a still-valid provider-analysis
cache.

Recovery fingerprints protected Phase 4 and source evidence before and after
the run. A passing report requires identical fingerprints and a complete
inventory of the twenty-five required typed negative proofs.

## Consequences

Exports are portable, provider-free, and auditable. Mixed corpus versions
cannot silently enter a package. Recovery can reuse expensive provider evidence
when its exact inputs remain valid, while corrupt artifacts remain available
for diagnosis. Long-recording and final completion qualification can use the
same export and recovery evidence rather than introducing another persistence
model.
