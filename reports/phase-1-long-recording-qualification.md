# Phase 1 long-recording qualification

Status: **PASSED**

A reproducibly generated Apache-2.0 synthetic audiovisual source was ingested with an intentional interruption after audio normalization, then resumed from committed evidence.

## Measurements

- Source duration: 7201000000 microseconds
- Source size: 233429346 bytes
- Source SHA-256: `a7a06422d18fb729ddb6eb1477c34ca52142c6c2f726bfb850dfd91f9ba2464b`
- Operational chunks: 13
- End-to-end processing: 7.66981 seconds
- Resume pass: 2.762143 seconds
- Python allocator peak: 2495017 bytes
- Corpus plus materialization output: 469902759 bytes
- Output/source ratio: 2.013041

The Python peak is measured with `tracemalloc`. FFmpeg and FFprobe run as bounded-time streaming subprocesses, so their native allocations are not included in that Python allocator figure.

## Gate results

- PASS — source at least two hours
- PASS — at least twelve chunks
- PASS — coverage complete
- PASS — integrity valid
- PASS — interruption observed
- PASS — resume complete
- PASS — resume reused committed stages
- PASS — mapping start middle end exact
- PASS — materialized chunks valid
- PASS — materialized cache hits
- PASS — python peak below 256 mib

Three chunks (start, middle, and end) were materialized as FLAC, validated, hashed, and immediately re-requested to prove cache hits. Start, middle, and end corpus timestamps mapped exactly to source time.

Machine-readable measurements are in `phase-1-long-recording-qualification.json`.
