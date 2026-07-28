# Phase 1 corpus and resume qualification

Status: Partial Phase 1 qualification evidence  
Date: 2026-07-26  
Corpus format: 1.0.0  
Ingestion format: 1.0.0

## Canonical Riverton clean run

The clean Riverton MP4 was ingested with an intentional interruption immediately
after `audio_normalization_committed`.

| Measurement | Result |
|---|---|
| Ingestion ID | `ingestion_335158d99f075edba0c9e36663580847` |
| Interrupted run | 1.799 s |
| Resumed run | 0.482 s |
| Final corpus ID | `corpus_50a45a17039abc2c5d2d8447530d81b9` |
| Corpus integrity | valid |
| Independently checked artifacts | 9 |
| Portable source bytes | 14,448,161 |
| Portable normalized audio bytes | 9,033,659 |
| Video access | available, source passthrough |
| Chunk count | 1 |

Resume validated and reused:

1. source verification;
2. inspection;
3. stream selection;
4. decode qualification; and
5. normalized audio.

It then committed video access, timeline, chunk plan, corpus, reports, and the
complete stage.

## Portable corpus contents

The corpus contains:

- a byte-identical original source copy;
- normalized audio independent of the workspace cache;
- inspection and full stream inventory;
- selection decisions;
- decode qualification;
- source timeline;
- normalized-audio manifest and mapping;
- video-access plan;
- processing chunk plan;
- cache identities;
- canonical manifest; and
- machine- and human-readable integrity and normalized-source reports.

Every manifest path is relative to the corpus root. Raw tool invocation paths
remain provenance only.

## Controlled resume and negative evidence

Tests demonstrate:

- interruption after inspection;
- committed inspection reuse;
- interruption after normalized audio on the canonical source;
- reuse of every valid upstream stage;
- changed normalization policy creates a different ingestion identity;
- changed source content creates a different ingestion identity;
- export and reload from a path containing spaces;
- source, selection, timeline, audio, video, and chunk lineage validation; and
- detection of post-commit normalized-audio substitution.

Invalid stage artifacts are recorded as invalidated and preserved beneath the
attempt history before rebuilding. No stage is reported complete before corpus
and reports commit.

## Remaining gates

This is not the Phase 1 completion report. Remaining work includes broader
resume fault injection, materialized chunks, cache coverage for other
operations, generated edge-case video fixtures, two-hour bounded-memory
qualification, and final all-source reporting.
