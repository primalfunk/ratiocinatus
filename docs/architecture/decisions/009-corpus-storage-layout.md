# ADR 009: Portable corpus storage layout

- Status: Accepted for Phase 1
- Date: 2026-07-26

## Context

The normalized corpus must connect every settled ingestion artifact, load
without relying on process memory, validate substitutions, and export to another
location without breaking source or derivative references. Passthrough video
also requires the authoritative original source to remain available.

## Decision

Each completed ingestion owns a content- and configuration-addressed directory:

```text
ingestions/<ingestion-id>/
  request.json
  checkpoint.json
  manifest.json
  input/original.<ext>
  state/*.json
  corpus/
    manifest.json
    source/original.<ext>
    derivatives/audio.flac
    metadata/*.json
    reports/*
```

The corpus directory is independently portable. Its manifest contains only
forward-slash relative artifact paths plus expected SHA-256 hashes and byte
sizes. It references:

- the immutable source copy;
- inspection and complete stream inventory;
- stream-selection decisions;
- decode qualification;
- source timeline;
- normalized audio and its derivative manifest;
- passthrough video-access plan;
- processing chunk plan;
- cache keys;
- configuration identity; and
- provenance-bearing metadata artifacts.

Source and normalized audio files are copied atomically into the corpus.
Metadata is written canonically and atomically. The manifest is written last and
the complete corpus is validated before ingestion can commit it.

Loading rebases portable source paths to the selected corpus root. Raw tool
invocations retain their original paths as provenance but are not used to
resolve corpus artifacts.

Ingestion checkpoints remain outside the portable corpus. They record every
committed, reused, invalidated, interrupted, and failed attempt. A stage is
reused only when its recorded hash and contract validate. Invalid artifacts are
preserved beneath the attempt history before rebuilding.

## Alternatives considered

- Absolute paths in the corpus manifest: simple locally but not portable.
- Embed all contracts in one large manifest: fewer files, but poor stage-level
  resume and corruption isolation.
- Reference cache files in place: avoids one copy but makes corpus validity
  depend on mutable workspace cache state.
- Omit the original source: saves storage but breaks portable passthrough video
  and original-evidence verification.

## Consequences

- A corpus can be copied, loaded, and validated independently.
- Source video remains byte-identical and needs no video derivative.
- Portable corpora intentionally duplicate the original source and normalized
  audio from ingestion/cache storage.
- Stage artifacts can be validated and reused separately during resume.

## Reversibility

Corpus and ingestion layouts have independent format versions. A future layout
can be exported from this one while retaining content identities.

## Qualification evidence

Controlled tests interrupt after inspection, resume with a validated inspection
reuse, complete an audio-only corpus, export it to a path containing spaces,
reload it, and detect post-commit audio substitution.
