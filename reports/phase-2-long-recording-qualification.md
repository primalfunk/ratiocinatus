# Phase 2 long-recording qualification

Status: **PASSED**

Synthetic ownership and boundary control; no speech or transcription-accuracy claim.

## Measurements

- Duration: 7201000000 microseconds
- Phase 1 chunks: 13
- Owned chunk transitions: 12
- Phase 2 activity intervals: 13
- Transcript segments: 13
- Timestamped words: 13
- Processing: 4.079543 seconds
- Python allocator peak: 2773608 bytes

## Gate results

- PASS — duration exceeds two hours
- PASS — phase1 corpus valid
- PASS — phase1 corpus unchanged
- PASS — multiple phase1 chunks
- PASS — chunk transitions contiguous
- PASS — activity coverage complete
- PASS — activity inherits every owned chunk
- PASS — overlap output not duplicated
- PASS — transcript observation per owned chunk
- PASS — canonical segment per owned chunk
- PASS — canonical word per owned chunk
- PASS — final assembly valid
- PASS — activity resume reused
- PASS — transcription resume reused
- PASS — assembly resume reused
- PASS — providers invoked once
- PASS — python peak below 256 mib

The qualification deliberately uses synthetic marker providers. It proves Phase 2 addressing, inherited overlap ownership, cache resume, integrity, and canonical assembly across the existing long Phase 1 corpus; it does not measure recognition quality.
