# Phase 2 negative-proof qualification

Status: **PASSED**

| Required negative case | Expected result | Status |
|---|---|---|
| `unsupported_audio_or_corpus_version` | strict contract ValidationError | PASSED |
| `missing_normalized_audio_derivative` | invalid CorpusIntegrityReport with explicit missing finding | PASSED |
| `corrupted_audio_evidence` | invalid CorpusIntegrityReport with hash/substitution finding | PASSED |
| `provider_unavailable` | SpeechProviderUnavailable | PASSED |
| `model_unavailable` | SpeechProviderUnavailable for unqualified model fingerprint | PASSED |
| `provider_timeout` | SpeechEvidenceFailureKind.TIMEOUT | PASSED |
| `malformed_provider_result` | SpeechEvidenceFailureKind.MALFORMED_OUTPUT | PASSED |
| `timestamps_outside_requested_interval` | TranscriptionIntegrityError | PASSED |
| `invalid_confidence_values` | strict ConfidenceMeasure ValidationError | PASSED |
| `word_timestamps_reverse_order` | strict ProviderTranscriptObservation ValidationError | PASSED |
| `duplicated_overlap_output` | TranscriptionIntegrityError | PASSED |
| `incompatible_transcript_and_corpus_ids` | strict TranscriptionRequest ValidationError | PASSED |
| `invalid_correction_target` | TranscriptCorrectionIntegrityError | PASSED |
| `conflicting_correction_history` | TranscriptCorrectionIntegrityError | PASSED |
| `invalid_subtitle_timing` | strict SubtitleCue ValidationError | PASSED |
| `unsupported_subtitle_export_version` | strict SubtitleExportManifest ValidationError | PASSED |
| `incomplete_cached_artifacts` | RecoveryAction.REBUILT_MISSING | PASSED |

Selected tests: 9
Required cases: 17
Processing: 17.055419 seconds

A case passes only through its asserted typed refusal or conservative degraded/recovery result. Selected tests may not be skipped.
