# Phase 3 deterministic diarization evidence-kernel qualification

Status: **PASSED**  
Application version: 0.4.0  
Target Phase 3 application version: 0.5.0

This slice implements deterministic request preparation and provider-independent
orchestration from validated Phase 1 corpus lineage and canonical Phase 2 speech
activity. Requests embed the exact selected speech intervals and may pin an
optional canonical transcript assembly/version.

Provider responses are checked for normalized-evidence integrity, source and
chunk-local mapping, speech containment, canonical chunk ownership, turn
containment, embedding lineage, and retained raw-evidence integrity. Canonical
speaker observations and provisional turns receive independent integrity seals
and are persisted in a separately sealed `DiarizationRun`.

Complete compatible runs are reused without invoking the provider. Partial
caches, incompatible requests, substituted evidence, and invalid mappings
refuse. CLI inspection and validation reload and recheck persisted evidence.

Three focused integration tests use a deterministic in-process provider boundary.
Together with seven foundation tests, they prove stable request identity,
configuration sensitivity, persistence, reuse, incomplete-cache refusal,
immutable Phase 1 audio, and no forced cluster or participant identity.

All 139 repository tests passed. Schema export produced 187 runtime schemas
plus 20 controlled-fixture schemas.

No production diarization model, voice clustering, reference-voice comparison,
participant identity decision, biometric enrollment, or embedding export was
added.
