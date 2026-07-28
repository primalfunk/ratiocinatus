# Initial licensing assessment

Date: 2026-07-26. This is an inventory, not legal advice or final approval.

| Material | Status | Restrictions / action |
|---|---|---|
| Ratiocinatus source | Confirmed Apache-2.0 | Selected by the project owner on 2026-07-26; see `LICENSE` |
| Pydantic and pydantic-core | Confirmed MIT | Preserve notices when distribution requires them |
| pytest (development) | Confirmed MIT | Development-only |
| coverage.py (development) | Confirmed Apache-2.0 | Development-only; attribution/notice review for redistribution |
| setuptools (build) | Confirmed MIT | Build-time only |
| Python standard library | PSF License | Runtime prerequisite, not bundled |
| Repository fixtures | Confirmed Apache-2.0 | Project-authored synthetic materials; third-party generation inputs retain separate terms |
| Documentation assets | Confirmed Apache-2.0 | No third-party assets present unless separately identified |
| Silero VAD 6.2.1 software and packaged model | Confirmed MIT | Optional local provider; installed separately and not redistributed |
| PyTorch | Confirmed BSD-3-Clause | Transitive optional Silero runtime; not bundled |
| TorchAudio | Confirmed BSD-2-Clause | Transitive optional Silero runtime; not bundled |
| FFmpeg (anticipated) | Further review | LGPL/GPL configuration and codec patent questions; not bundled |
| OpenAI Whisper 20250625 code and `small` weights | Confirmed MIT | Optional local provider; checkpoint acquired separately and not redistributed |
| Other Whisper-family software/models | Further review | Each implementation and model-weight license must be assessed separately |
| pyannote-family software/models | Further review | Software, model, dataset, and access terms differ |
| LM Studio / hosted local models | Further review | Provider software and each model weight license are separate |
| Future embeddings | Unknown | Select and review implementation and model separately |
| Future datasets | Unknown | Consent, redistribution, commercial-use, and attribution review |

The optional pinned Silero speech-activity provider and OpenAI Whisper `small` transcription provider are approved for local use but are not bundled or redistributed. No other transcription model, dataset, or third-party media is approved or bundled. Commercial use and redistribution are
unresolved wherever the row says further review or unknown.


