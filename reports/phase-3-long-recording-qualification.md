# Phase 3 long-recording operational qualification

Status: **PASSED**

- Duration: 7201000000 microseconds
- Speaker observations: 13
- Speaker turns: 13
- Cross-chunk clusters: 3
- Cache hits: 7
- Peak Python memory: 2698662 bytes

## Assertions

- [x] duration_exceeds_two_hours
- [x] phase1_corpus_valid
- [x] phase1_corpus_unchanged
- [x] phase2_transcript_reused
- [x] every_owned_chunk_observed_once
- [x] provider_invocation_bounded
- [x] diarization_resume_reused
- [x] cross_chunk_clusters_continuous
- [x] clustering_resume_reused
- [x] no_duplicate_observations_or_turns
- [x] reviewed_identity_view_complete
- [x] speaker_transcript_complete
- [x] participant_subtitles_complete
- [x] all_persisted_stages_replay
- [x] python_peak_below_256_mib

This is a synthetic operational mechanics control. It does not establish diarization or participant-identification accuracy.
