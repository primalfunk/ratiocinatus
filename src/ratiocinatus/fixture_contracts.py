"""Authoritative Phase 0.5 controlled-proof contracts."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

FIXTURE_CONTRACT_VERSION = "0.1.0"
FIXTURE_FORMAT_VERSION = "1.0.0"
FIXTURE_ID = "ratiocinatus-proof-riverton-evening-access-v1"


class FixtureContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    contract_version: str = FIXTURE_CONTRACT_VERSION


class ProofFixtureVariant(str, Enum):
    CLEAN = "clean"
    NATURALIZED = "naturalized"
    ADVERSARIAL = "adversarial"


class SpeakerRole(str, Enum):
    MODERATOR = "MODERATOR"
    PARTICIPANT_A = "PARTICIPANT_A"
    PARTICIPANT_B = "PARTICIPANT_B"


class LicenseStatus(str, Enum):
    SAFE = "safely_redistributable"
    WITH_NOTICES = "redistributable_with_notices"
    LOCAL_ONLY = "locally_generatable_not_distributable"
    BLOCKED = "blocked_pending_review"


class FindingSeverity(str, Enum):
    INFORMATION = "information"
    WARNING = "warning"
    ERROR = "error"
    FATAL = "fatal"


class ScriptSpeaker(FixtureContract):
    speaker_id: SpeakerRole
    display_name: str = Field(min_length=1)
    role: str = Field(min_length=1)
    fictional: Literal[True] = True


class ScriptLine(FixtureContract):
    line_id: str = Field(pattern=r"^L\d{3}$")
    order: int = Field(ge=1, le=999)
    speaker_id: SpeakerRole
    text: str = Field(min_length=1)
    text_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class EvidenceItem(FixtureContract):
    evidence_id: str = Field(pattern=r"^E-\d{2}$")
    title: str
    statements: tuple[str, ...]
    fictional: Literal[True] = True


class EvidencePacket(FixtureContract):
    fixture_id: Literal[FIXTURE_ID] = FIXTURE_ID
    items: tuple[EvidenceItem, ...]
    limitations: tuple[str, ...]


class VoiceAssignment(FixtureContract):
    speaker_id: SpeakerRole
    engine: Literal["kokoro-onnx"]
    engine_version: str
    model: Literal["hexgrad/Kokoro-82M-v1.0"]
    voice_id: str = Field(pattern=r"^[a-z]{2}_[a-z]+$")
    language: Literal["en-us"] = "en-us"
    speed: float = Field(gt=0.5, lt=2.0)
    cloned_voice: Literal[False] = False
    intentional_imitation: Literal[False] = False


class GenerationPolicy(FixtureContract):
    fixture_id: Literal[FIXTURE_ID] = FIXTURE_ID
    fixture_format_version: Literal[FIXTURE_FORMAT_VERSION] = FIXTURE_FORMAT_VERSION
    sample_rate_hz: Literal[48000] = 48000
    channels: Literal[2] = 2
    width: Literal[1920] = 1920
    height: Literal[1080] = 1080
    frames_per_second: Literal[30] = 30
    target_duration_seconds_min: Literal[480] = 480
    target_duration_seconds_max: Literal[840] = 840
    seed: int = 20260726
    regeneration_class: Literal["configuration_equivalent"] = "configuration_equivalent"


class SynthesisInvocation(FixtureContract):
    line_id: str = Field(pattern=r"^L\d{3}$")
    speaker_id: SpeakerRole
    voice_id: str
    text_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    output_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    sample_rate_hz: int = Field(gt=0)
    sample_count: int = Field(gt=0)
    duration_microseconds: int = Field(gt=0)


class LineAudioArtifact(FixtureContract):
    line_id: str = Field(pattern=r"^L\d{3}$")
    relative_path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    duration_microseconds: int = Field(gt=0)


class LineSchedule(FixtureContract):
    line_id: str = Field(pattern=r"^L\d{3}$")
    speaker_id: SpeakerRole
    start_microseconds: int = Field(ge=0)
    duration_microseconds: int = Field(gt=0)
    end_microseconds: int = Field(gt=0)

    @model_validator(mode="after")
    def consistent_interval(self) -> "LineSchedule":
        if self.end_microseconds != self.start_microseconds + self.duration_microseconds:
            raise ValueError("end must equal start plus duration")
        return self


class OverlapEvent(FixtureContract):
    overlap_id: str = Field(pattern=r"^O-\d{2}$|^I-\d{2}$")
    first_line_id: str = Field(pattern=r"^L\d{3}$")
    second_line_id: str = Field(pattern=r"^L\d{3}$")
    start_microseconds: int = Field(ge=0)
    duration_microseconds: int = Field(gt=0)


class AcousticPerturbation(FixtureContract):
    perturbation_id: str = Field(pattern=r"^P-\d{2}$")
    line_id: str = Field(pattern=r"^L\d{3}$")
    kind: Literal["gain", "broadband_noise", "initial_clip", "voice_similarity"]
    start_microseconds: int = Field(ge=0)
    duration_microseconds: int = Field(gt=0)
    parameters: tuple[tuple[str, str], ...]


class VisualStateEvent(FixtureContract):
    event_id: str
    start_microseconds: int = Field(ge=0)
    duration_microseconds: int = Field(gt=0)
    active_speaker: SpeakerRole | None
    actual_speaker: SpeakerRole | None
    intentional_mismatch: bool = False


class FixtureReferenceAnnotation(FixtureContract):
    annotation_id: str
    category: Literal[
        "discourse_act", "proposition", "argument_relation", "obligation",
        "candidate_call", "expected_non_call", "ambiguity",
    ]
    line_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...] = ()
    description: str
    status: Literal["intended", "candidate", "expected", "ambiguous"]


class ProofFixture(FixtureContract):
    fixture_id: Literal[FIXTURE_ID] = FIXTURE_ID
    family_name: Literal["Riverton Evening Access Forum"] = "Riverton Evening Access Forum"
    version: Literal["1.0.0"] = "1.0.0"
    discourse_format: Literal["moderated_civic_policy_forum"] = "moderated_civic_policy_forum"
    variants: tuple[ProofFixtureVariant, ...]
    speaker_count: Literal[3] = 3
    line_count: Literal[68] = 68


class ProofFixtureVariantRecord(FixtureContract):
    fixture_id: Literal[FIXTURE_ID] = FIXTURE_ID
    variant: ProofFixtureVariant
    media_duration_microseconds: int = Field(gt=0)
    line_count: Literal[68] = 68
    overlap_count: int = Field(ge=0)
    perturbation_count: int = Field(ge=0)
    visual_state_count: int = Field(gt=0)


class LicenseComponent(FixtureContract):
    component_id: str
    name: str
    version: str | None = None
    license: str
    source: str
    required: bool
    redistributed: bool
    notice: str | None = None


class LicenseManifest(FixtureContract):
    fixture_id: Literal[FIXTURE_ID] = FIXTURE_ID
    distribution_status: LicenseStatus
    components: tuple[LicenseComponent, ...]
    no_cloned_voices: Literal[True] = True
    no_third_party_media: Literal[True] = True


class FixtureManifest(FixtureContract):
    fixture: ProofFixture
    script_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    evidence_packet_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    voice_policy_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    license_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    canonical_media_frozen: bool
    canonical_media_hashes: tuple[tuple[str, str], ...]
    checksum_file: str


class FixtureValidationFinding(FixtureContract):
    finding_id: str
    severity: FindingSeverity
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]+$")
    message: str
    subject: str | None = None


class FixtureValidationReport(FixtureContract):
    fixture_id: Literal[FIXTURE_ID] = FIXTURE_ID
    valid: bool
    checked_media: bool
    findings: tuple[FixtureValidationFinding, ...]
    line_count: int = Field(ge=0)
    variant_count: int = Field(ge=0)


FIXTURE_CONTRACT_MODELS = (
    ScriptSpeaker, ScriptLine, EvidenceItem, EvidencePacket, VoiceAssignment,
    GenerationPolicy, SynthesisInvocation, LineAudioArtifact, LineSchedule,
    OverlapEvent, AcousticPerturbation, VisualStateEvent,
    FixtureReferenceAnnotation, ProofFixture, ProofFixtureVariantRecord,
    LicenseComponent, LicenseManifest, FixtureManifest,
    FixtureValidationFinding, FixtureValidationReport,
)

