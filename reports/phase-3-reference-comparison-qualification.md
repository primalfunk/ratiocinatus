# Phase 3 compatible reference-voice comparison qualification

Status: **PASSED**  
Application version: 0.4.0  
Target Phase 3 application version: 0.5.0

This slice implements compatible reference-voice comparison as immutable,
explicitly non-binding identity-hypothesis evidence.

Each comparison is lineage-bound to clustering, diarization, participant
identity, and enrollment artifacts. It records a canonical cluster or
observation target, active reference enrollment, protected representation
metadata, exact model space and fingerprint, provider and method, score,
ordered threshold policy, calibration or cohort context, target and reference
quality, channel and overlap conditions, supporting and contrary evidence,
uncertainty, limitations, and result classification.

Compatible scores produce supports, weakly supports, inconclusive, weakly
contradicts, or contradicts classifications. Incompatible model spaces,
unknown targets, out-of-scope targets, missing or out-of-scale scores, unusable
evidence, and rejected, revoked, replaced, or expired references produce an
explicit invalid comparison.

Uncalibrated comparisons state that scores are not identity probabilities and
have no established error rate. Threshold contracts prohibit automatic
identity binding. No representation values enter portable contracts.

CLI operations compare, inspect, list, and validate comparison evidence. Four
focused comparison tests and all 147 repository tests passed. Schema export
produced 198 runtime schemas plus 20 controlled-fixture schemas.

No definitive identity decision, automatic binding, manual binding,
participant-labeled transcript, participant-labeled subtitle export, or
production comparison provider was added.
