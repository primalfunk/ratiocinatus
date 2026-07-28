"""Deterministic serialization, identifiers, providers, workspace, and replay."""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import shutil
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from pydantic import BaseModel, ValidationError

from .contracts import (
    ArtifactEnvelope, ArtifactState, Capability, ConfigurationSnapshot,
    CONTRACT_MODELS, EvidenceArtifact, FailureKind, IntegrityReport,
    IntegrityState, OperationRequest, OperationResult, OperationStatus,
    PhaseReport, ProvenanceKind, ProvenanceRecord, ProviderDescriptor,
    ProviderInvocation, ProviderResult, RegisteredSource, ReplayRecord,
    ReplayStatus, Severity, SourceFingerprint, SourceReference,
    ValidationFinding, WorkspaceManifest,
)
from .version import (
    __version__, SERIALIZATION_VERSION, WORKSPACE_VERSION,
)


class RatiocinatusError(Exception):
    kind = FailureKind.INTERNAL_FAILURE


class UnsupportedVersionError(RatiocinatusError):
    kind = FailureKind.UNSUPPORTED_VERSION


class IntegrityError(RatiocinatusError):
    kind = FailureKind.INTEGRITY_FAILURE


class ProviderError(RatiocinatusError):
    kind = FailureKind.PROVIDER_FAILURE


class MalformedProviderOutput(ProviderError):
    kind = FailureKind.MALFORMED_PROVIDER_OUTPUT


def _plain(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=False)
    return value


def canonical_bytes(value: Any) -> bytes:
    """UTF-8 JSON: sorted keys, no insignificant whitespace, explicit nulls.

    Datetimes use RFC 3339 via contracts, durations use integer microseconds,
    enums use values, arrays retain contract-defined order, and NaN/Infinity
    are rejected.
    """
    return json.dumps(
        _plain(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def load_contract(data: bytes | str, model: type[BaseModel]) -> BaseModel:
    return model.model_validate_json(data)


def typed_id(namespace: str, *normalized_parts: Any) -> str:
    digest = hashlib.sha256(canonical_bytes(normalized_parts)).hexdigest()[:32]
    return f"{namespace}_{digest}"


class Clock(ABC):
    @abstractmethod
    def now(self) -> datetime: ...

    @property
    @abstractmethod
    def descriptor(self) -> str: ...


class SystemClock(Clock):
    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    @property
    def descriptor(self) -> str:
        return "system-utc"


@dataclass(frozen=True)
class FixedClock(Clock):
    value: datetime

    def __post_init__(self) -> None:
        if self.value.tzinfo is None:
            raise ValueError("fixed clock must be timezone-aware")

    def now(self) -> datetime:
        return self.value

    @property
    def descriptor(self) -> str:
        return f"fixed:{self.value.isoformat()}"


SECRET_KEYS = {"secret", "password", "token", "api_key", "apikey"}


def redact_secrets(data: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: ("[REDACTED]" if any(word in key.lower() for word in SECRET_KEYS)
              else value)
        for key, value in data.items()
    }


def resolve_configuration(
    workspace: str,
    file_values: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    cli_values: Mapping[str, Any] | None = None,
) -> ConfigurationSnapshot:
    """Resolve defaults < file < RATIOCINATUS_* environment < CLI."""
    values: dict[str, Any] = {
        "workspace": workspace, "serialization_policy": SERIALIZATION_VERSION,
        "log_level": "INFO", "provider_selection": (),
        "deterministic": False, "copy_sources": False,
        "report_output": "reports",
    }
    values.update(redact_secrets(file_values or {}))
    env = env or os.environ
    mapping = {
        "RATIOCINATUS_LOG_LEVEL": "log_level",
        "RATIOCINATUS_DETERMINISTIC": "deterministic",
        "RATIOCINATUS_COPY_SOURCES": "copy_sources",
        "RATIOCINATUS_REPORT_OUTPUT": "report_output",
    }
    for source, target in mapping.items():
        if source in env:
            raw: Any = env[source]
            if target in {"deterministic", "copy_sources"}:
                raw = raw.lower() in {"1", "true", "yes"}
            values[target] = raw
    values.update(redact_secrets(cli_values or {}))
    base = ConfigurationSnapshot(**values)
    return base.model_copy(update={"snapshot_hash": canonical_hash(base)})


class Provider(ABC):
    @property
    @abstractmethod
    def descriptor(self) -> ProviderDescriptor: ...

    @abstractmethod
    def invoke(self, capability: Capability, payload: str, mode: str = "success") -> EvidenceArtifact: ...


class DeterministicMockProvider(Provider):
    def __init__(self, capability: Capability):
        self.capability = capability

    @property
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            provider_id=f"mock.{self.capability.value}",
            display_name=f"Synthetic {self.capability.value} mock",
            provider_version="0.1.0",
            capabilities=(self.capability,), mock=True, deterministic=True,
            available=True,
        )

    def invoke(self, capability: Capability, payload: str, mode: str = "success") -> EvidenceArtifact:
        if capability != self.capability:
            raise ProviderError(f"unsupported capability: {capability.value}")
        if mode == "failure":
            raise ProviderError("intentional deterministic mock failure")
        if mode == "malformed":
            raise MalformedProviderOutput("intentional malformed mock output")
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        outputs: dict[Capability, Any] = {
            Capability.MEDIA_INSPECTION: {"media_type": "synthetic/opaque", "streams": []},
            Capability.TRANSCRIPTION: {"segments": [{"text": "[SYNTHETIC TRANSCRIPT]", "start_us": 0, "duration_us": 1}]},
            Capability.DIARIZATION: {"speakers": [{"label": "SYNTHETIC_SPEAKER_00"}]},
            Capability.EMBEDDING: {"vector": [0.0, 0.25, 0.5, 0.75]},
            Capability.STRUCTURED_GENERATION: {"synthetic_response": True, "input_digest": digest},
            Capability.RENDERING: {"outputs": [], "notice": "SYNTHETIC RENDER MANIFEST"},
        }
        return EvidenceArtifact(
            artifact_type=f"mock.{capability.value}.result",
            payload=outputs[capability], synthetic=True,
        )


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, Provider] = {}

    def register(self, provider: Provider) -> None:
        key = provider.descriptor.provider_id
        if key in self._providers:
            raise ValueError(f"duplicate provider identity: {key}")
        self._providers[key] = provider

    def list(self) -> tuple[ProviderDescriptor, ...]:
        return tuple(p.descriptor for p in sorted(
            self._providers.values(), key=lambda p: p.descriptor.provider_id
        ))

    def get(self, provider_id: str) -> Provider:
        try:
            return self._providers[provider_id]
        except KeyError as exc:
            raise ProviderError(f"provider unavailable: {provider_id}") from exc

    @classmethod
    def with_mocks(cls) -> "ProviderRegistry":
        registry = cls()
        for capability in Capability:
            registry.register(DeterministicMockProvider(capability))
        return registry


class Workspace:
    """Portable filesystem workspace with append-only canonical records."""

    DIRECTORIES = (
        "sources", "artifacts", "provenance", "operations",
        "validations", "replays", "reports", "exports",
    )

    def __init__(self, root: Path, manifest: WorkspaceManifest, config: ConfigurationSnapshot):
        self.root, self.manifest, self.config = root, manifest, config

    @classmethod
    def initialize(cls, root: Path, config: ConfigurationSnapshot, clock: Clock) -> "Workspace":
        root = root.resolve()
        if (root / "manifest.json").exists():
            raise FileExistsError(f"workspace already exists: {root}")
        root.mkdir(parents=True, exist_ok=True)
        for name in cls.DIRECTORIES:
            (root / name).mkdir()
        ws_id = typed_id("ws", config.snapshot_hash, clock.now().isoformat())
        manifest = WorkspaceManifest(
            workspace_id=ws_id, created_at=clock.now(),
            application_version=__version__,
            canonical_serialization_version=SERIALIZATION_VERSION,
            configuration_hash=config.snapshot_hash or canonical_hash(config),
        )
        (root / "manifest.json").write_bytes(canonical_bytes(manifest))
        (root / "configuration.json").write_bytes(canonical_bytes(config))
        return cls(root, manifest, config)

    @classmethod
    def open(cls, root: Path) -> "Workspace":
        root = root.resolve()
        manifest = load_contract((root / "manifest.json").read_bytes(), WorkspaceManifest)
        assert isinstance(manifest, WorkspaceManifest)
        if manifest.workspace_version != WORKSPACE_VERSION:
            raise UnsupportedVersionError(
                f"workspace {manifest.workspace_version}; supported {WORKSPACE_VERSION}"
            )
        config = load_contract((root / "configuration.json").read_bytes(), ConfigurationSnapshot)
        assert isinstance(config, ConfigurationSnapshot)
        return cls(root, manifest, config)

    @contextmanager
    def writer(self) -> Iterator[None]:
        lock = self.root / ".writer.lock"
        try:
            handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise RuntimeError("workspace already has an active writer") from exc
        os.close(handle)
        try:
            yield
        finally:
            lock.unlink(missing_ok=True)

    def _append(self, relative: str, value: BaseModel) -> None:
        path = self.root / relative
        with path.open("ab") as stream:
            stream.write(canonical_bytes(value) + b"\n")

    def _records(self, relative: str, model: type[BaseModel]) -> list[BaseModel]:
        path = self.root / relative
        if not path.exists():
            return []
        return [load_contract(line, model) for line in path.read_bytes().splitlines() if line]

    def register_source(self, source: Path, clock: Clock) -> RegisteredSource:
        source = source.resolve(strict=True)
        before = source.read_bytes()
        fingerprint = SourceFingerprint(
            digest=hashlib.sha256(before).hexdigest(), byte_size=len(before)
        )
        existing = self._records("sources/registry.jsonl", RegisteredSource)
        duplicate = next((r.source_id for r in existing if r.fingerprint.digest == fingerprint.digest), None)
        operation_id = typed_id("op", "source.register", fingerprint.digest, str(source), self.config.snapshot_hash)
        requested = OperationRequest(
            operation_id=operation_id, operation_type="source.register",
            requested_at=clock.now(), configuration=self.config,
            parameters=(("source_digest", fingerprint.digest),),
        )
        provenance_id = typed_id("prov", operation_id, 0)
        record = RegisteredSource(
            source_id=typed_id("src", fingerprint.digest),
            reference=SourceReference(original=str(source), display_name=source.name),
            fingerprint=fingerprint,
            media_type=mimetypes.guess_type(source.name)[0],
            registered_at=clock.now(),
            configuration_hash=self.config.snapshot_hash or canonical_hash(self.config),
            provenance_id=provenance_id, duplicate_of=duplicate,
        )
        provenance = ProvenanceRecord(
            provenance_id=provenance_id, sequence=0,
            kind=ProvenanceKind.IMPORT, recorded_at=clock.now(),
            operation_id=operation_id, input_ids=(fingerprint.digest,),
            output_ids=(record.source_id,),
            configuration_hash=self.config.snapshot_hash or canonical_hash(self.config),
            application_version=__version__, note=f"clock={clock.descriptor}",
        )
        result = OperationResult(
            operation_id=operation_id, status=OperationStatus.SUCCEEDED,
            completed_at=clock.now(), provenance_ids=(provenance_id,),
        )
        with self.writer():
            self._append("operations/requests.jsonl", requested)
            self._append("sources/registry.jsonl", record)
            self._append("provenance/records.jsonl", provenance)
            self._append("operations/results.jsonl", result)
            if self.config.copy_sources:
                destination = self.root / "sources" / "originals"
                destination.mkdir(exist_ok=True)
                target = destination / fingerprint.digest
                if not target.exists():
                    shutil.copyfile(source, target)
        if source.read_bytes() != before:
            raise IntegrityError("source changed during registration")
        return record

    def verify_source(self, source_id: str) -> bool:
        records = [
            record for record in self._records("sources/registry.jsonl", RegisteredSource)
            if record.source_id == source_id
        ]
        if not records:
            raise FileNotFoundError(source_id)
        return all(
            Path(record.reference.original).is_file()
            and hashlib.sha256(Path(record.reference.original).read_bytes()).hexdigest()
            == record.fingerprint.digest
            for record in records
        )

    def invoke_provider(
        self, provider: Provider, capability: Capability, payload: str,
        clock: Clock, mode: str = "success",
    ) -> ArtifactEnvelope:
        input_hash = hashlib.sha256(payload.encode()).hexdigest()
        operation_id = typed_id(
            "op", "provider.invoke", provider.descriptor.provider_id,
            capability.value, input_hash, self.config.snapshot_hash, mode,
        )
        request = OperationRequest(
            operation_id=operation_id, operation_type="provider.invoke",
            requested_at=clock.now(), configuration=self.config,
            provider_id=provider.descriptor.provider_id, capability=capability,
            parameters=(("input", payload), ("mode", mode)),
        )
        try:
            artifact = provider.invoke(capability, payload, mode)
        except RatiocinatusError as exc:
            failure = OperationResult(
                operation_id=operation_id, status=OperationStatus.FAILED,
                completed_at=clock.now(), failure=exc.kind, message=str(exc),
            )
            with self.writer():
                self._append("operations/requests.jsonl", request)
                self._append("operations/results.jsonl", failure)
            raise
        artifact_hash = canonical_hash(artifact)
        artifact_id = typed_id("art", artifact.artifact_type, artifact_hash, operation_id)
        provenance_id = typed_id("prov", operation_id, 0)
        envelope = ArtifactEnvelope(
            artifact_id=artifact_id, artifact_type=artifact.artifact_type,
            created_at=clock.now(), creation_operation_id=operation_id,
            provenance_ids=(provenance_id,), content_hash=artifact_hash,
            artifact=artifact,
        )
        invocation_id = typed_id("inv", operation_id, provider.descriptor.provider_id)
        invocation = ProviderInvocation(
            invocation_id=invocation_id, provider=provider.descriptor,
            capability=capability, operation_id=operation_id,
            input_hash=input_hash,
            configuration_hash=self.config.snapshot_hash or canonical_hash(self.config),
            seed=0, decoding_policy="deterministic", invoked_at=clock.now(),
        )
        provider_result = ProviderResult(
            invocation_id=invocation_id, success=True, output=artifact
        )
        provenance = ProvenanceRecord(
            provenance_id=provenance_id, sequence=0,
            kind=ProvenanceKind.PROVIDER, recorded_at=clock.now(),
            operation_id=operation_id, input_ids=(input_hash,),
            output_ids=(artifact_id,),
            configuration_hash=self.config.snapshot_hash or canonical_hash(self.config),
            application_version=__version__, provider_invocation_id=invocation_id,
            note=f"clock={clock.descriptor}",
        )
        result = OperationResult(
            operation_id=operation_id, status=OperationStatus.SUCCEEDED,
            completed_at=clock.now(), artifact_ids=(artifact_id,),
            provenance_ids=(provenance_id,),
        )
        with self.writer():
            self._append("operations/requests.jsonl", request)
            path = self.root / "artifacts" / f"{artifact_id}.json"
            if path.exists() and path.read_bytes() != canonical_bytes(envelope):
                raise IntegrityError("artifact identifier collision")
            path.write_bytes(canonical_bytes(envelope))
            self._append("provenance/records.jsonl", provenance)
            self._append("provenance/provider_invocations.jsonl", invocation)
            self._append("provenance/provider_results.jsonl", provider_result)
            self._append("operations/results.jsonl", result)
        return envelope

    def list_sources(self) -> list[RegisteredSource]:
        return list(self._records("sources/registry.jsonl", RegisteredSource))

    def list_artifacts(self) -> list[ArtifactEnvelope]:
        return [
            load_contract(path.read_bytes(), ArtifactEnvelope)
            for path in sorted((self.root / "artifacts").glob("art_*.json"))
        ]

    def validate(self, clock: Clock) -> IntegrityReport:
        findings: list[ValidationFinding] = []
        def add(severity: Severity, code: str, message: str, subject: str | None = None) -> None:
            findings.append(ValidationFinding(
                finding_id=typed_id("finding", code, message, subject),
                severity=severity, code=code, message=message, subject_id=subject,
            ))
        for source in self.list_sources():
            if not self.verify_source(source.source_id):
                add(Severity.ERROR, "SOURCE_HASH_MISMATCH", "source content no longer matches", source.source_id)
        provenance_ids = {r.provenance_id for r in self._records("provenance/records.jsonl", ProvenanceRecord)}
        operation_ids = {r.operation_id for r in self._records("operations/results.jsonl", OperationResult)}
        for artifact in self.list_artifacts():
            if canonical_hash(artifact.artifact) != artifact.content_hash:
                add(Severity.FATAL, "ARTIFACT_HASH_MISMATCH", "artifact payload hash mismatch", artifact.artifact_id)
            if artifact.creation_operation_id not in operation_ids:
                add(Severity.ERROR, "MISSING_OPERATION", "artifact creation operation missing", artifact.artifact_id)
            for prov in artifact.provenance_ids:
                if prov not in provenance_ids:
                    add(Severity.ERROR, "MISSING_PROVENANCE", "artifact provenance missing", artifact.artifact_id)
            known_artifacts = {a.artifact_id for a in self.list_artifacts()}
            for dependency in artifact.dependencies:
                if dependency.artifact_id not in known_artifacts:
                    add(Severity.ERROR, "MISSING_DEPENDENCY", "artifact dependency missing", artifact.artifact_id)
        if not findings:
            add(Severity.INFORMATION, "WORKSPACE_VALID", "all checked integrity constraints passed")
        report = IntegrityReport(
            report_id=typed_id("report", "integrity", self.manifest.workspace_id, tuple(f.finding_id for f in findings)),
            generated_at=clock.now(), workspace_id=self.manifest.workspace_id,
            findings=tuple(findings),
            valid=not any(f.severity in {Severity.ERROR, Severity.FATAL} for f in findings),
        )
        (self.root / "validations" / f"{report.report_id}.json").write_bytes(canonical_bytes(report))
        return report

    def replay(self, operation_id: str, registry: ProviderRegistry, clock: Clock) -> ReplayRecord:
        requests = self._records("operations/requests.jsonl", OperationRequest)
        request = next((r for r in requests if r.operation_id == operation_id), None)
        if request is None:
            raise FileNotFoundError(operation_id)
        originals = [a for a in self.list_artifacts() if a.creation_operation_id == operation_id]
        if request.operation_type != "provider.invoke" or request.provider_id is None or request.capability is None:
            record = ReplayRecord(
                report_id=typed_id("report", "replay", operation_id, "unsupported"),
                original_operation_id=operation_id, replayed_at=clock.now(),
                status=ReplayStatus.UNSUPPORTED,
                expected_hashes=tuple(a.content_hash for a in originals),
                reproduced_hashes=(), reason="operation type is not replayable in Phase 0",
            )
        else:
            params = dict(request.parameters)
            provider = registry.get(request.provider_id)
            reproduced = provider.invoke(request.capability, params["input"], params.get("mode", "success"))
            expected = tuple(a.content_hash for a in originals)
            actual = (canonical_hash(reproduced),)
            record = ReplayRecord(
                report_id=typed_id("report", "replay", operation_id, expected, actual),
                original_operation_id=operation_id, replayed_at=clock.now(),
                status=ReplayStatus.MATCH if expected == actual else ReplayStatus.MISMATCH,
                expected_hashes=expected, reproduced_hashes=actual,
                reason=None if expected == actual else "canonical artifact hashes differ",
            )
        (self.root / "replays" / f"{record.report_id}.json").write_bytes(canonical_bytes(record))
        return record

    def export(self, destination: Path) -> Path:
        destination.mkdir(parents=True, exist_ok=True)
        for name in ("manifest.json", "configuration.json"):
            shutil.copyfile(self.root / name, destination / name)
        for directory in self.DIRECTORIES:
            source = self.root / directory
            if source.exists():
                shutil.copytree(source, destination / directory, dirs_exist_ok=True)
        return destination


def export_schemas(destination: Path) -> list[Path]:
    from .addressing_contracts import ADDRESSING_CONTRACT_MODELS
    from .chunk_contracts import CHUNK_CONTRACT_MODELS
    from .corpus_contracts import CORPUS_CONTRACT_MODELS
    from .normalization_contracts import NORMALIZATION_CONTRACT_MODELS
    from .materialization_contracts import MATERIALIZATION_CONTRACT_MODELS
    from .phase1_contracts import PHASE1_CONTRACT_MODELS
    from .packet_contracts import PACKET_CONTRACT_MODELS
    from .phase2_contracts import PHASE2_CONTRACT_MODELS
    from .phase3_contracts import PHASE3_CONTRACT_MODELS
    from .phase4_contracts import PHASE4_CONTRACT_MODELS
    from .utterance_relation_contracts import (
        PHASE4_RELATION_CONTRACT_MODELS,
    )
    from .turn_repair_contracts import TURN_REPAIR_CONTRACT_MODELS
    from .quotation_contracts import QUOTATION_CONTRACT_MODELS
    from .utterance_view_contracts import UTTERANCE_VIEW_CONTRACT_MODELS
    from .context_window_contracts import CONTEXT_WINDOW_CONTRACT_MODELS
    from .phase4_review_contracts import PHASE4_REVIEW_CONTRACT_MODELS
    from .phase4_evaluation_contracts import PHASE4_EVALUATION_CONTRACT_MODELS
    from .phase4_export_contracts import PHASE4_EXPORT_CONTRACT_MODELS
    from .phase4_recovery_contracts import PHASE4_RECOVERY_CONTRACT_MODELS
    from .phase4_completion_contracts import (
        PHASE4_COMPLETION_CONTRACT_MODELS,
    )
    from .phase5_contracts import PHASE5_CONTRACT_MODELS
    from .phase5_provider_contracts import (
        PHASE5_PROVIDER_CONTRACT_MODELS,
    )
    from .phase5_baseline_contracts import (
        PHASE5_BASELINE_CONTRACT_MODELS,
    )
    from .phase5_provider_analysis_contracts import (
        PHASE5_PROVIDER_ANALYSIS_CONTRACT_MODELS,
    )
    from .phase5_consolidation_contracts import (
        PHASE5_CONSOLIDATION_CONTRACT_MODELS,
    )
    from .phase5_question_answer_contracts import (
        PHASE5_QUESTION_ANSWER_CONTRACT_MODELS,
    )
    from .phase5_argument_relation_contracts import (
        PHASE5_ARGUMENT_RELATION_CONTRACT_MODELS,
    )
    from .phase5_lexical_example_quotation_contracts import (
        PHASE5_LEXICAL_EXAMPLE_QUOTATION_CONTRACT_MODELS,
    )
    from .phase5_procedural_state_contracts import (
        PHASE5_PROCEDURAL_STATE_CONTRACT_MODELS,
    )
    from .phase5_review_contracts import (
        PHASE5_REVIEW_CONTRACT_MODELS,
    )
    from .phase5_evaluation_contracts import (
        PHASE5_EVALUATION_CONTRACT_MODELS,
    )
    from .phase5_export_contracts import (
        PHASE5_EXPORT_CONTRACT_MODELS,
    )
    from .phase5_recovery_contracts import (
        PHASE5_RECOVERY_CONTRACT_MODELS,
    )
    from .phase5_completion_contracts import (
        PHASE5_COMPLETION_CONTRACT_MODELS,
    )
    from .clustering_contracts import CLUSTERING_CONTRACT_MODELS
    from .clustering_evaluation_contracts import (
        CLUSTERING_EVALUATION_CONTRACT_MODELS,
    )
    from .diarization_evaluation_contracts import (
        DIARIZATION_EVALUATION_CONTRACT_MODELS,
    )
    from .identity_contracts import IDENTITY_CONTRACT_MODELS
    from .identity_binding_contracts import (
        IDENTITY_BINDING_CONTRACT_MODELS,
    )
    from .identity_view_contracts import (
        IDENTITY_VIEW_CONTRACT_MODELS,
    )
    from .speaker_transcript_contracts import (
        SPEAKER_TRANSCRIPT_CONTRACT_MODELS,
    )
    from .participant_subtitle_contracts import (
        PARTICIPANT_SUBTITLE_CONTRACT_MODELS,
    )
    from .reference_enrollment_contracts import (
        REFERENCE_ENROLLMENT_CONTRACT_MODELS,
    )
    from .reference_comparison_contracts import (
        REFERENCE_COMPARISON_CONTRACT_MODELS,
    )
    from .transcript_contracts import TRANSCRIPT_CONTRACT_MODELS
    from .correction_contracts import CORRECTION_CONTRACT_MODELS
    from .subtitle_contracts import SUBTITLE_CONTRACT_MODELS
    from .evaluation_contracts import EVALUATION_CONTRACT_MODELS
    from .recovery_contracts import RECOVERY_CONTRACT_MODELS
    from .phase3_recovery_contracts import (
        PHASE3_RECOVERY_CONTRACT_MODELS,
    )
    from .phase3_completion_contracts import (
        PHASE3_COMPLETION_CONTRACT_MODELS,
    )
    from .qualification_contracts import QUALIFICATION_CONTRACT_MODELS
    from .selection_contracts import SELECTION_CONTRACT_MODELS
    from .video_contracts import VIDEO_CONTRACT_MODELS

    destination.mkdir(parents=True, exist_ok=True)
    paths = []
    for model in (
        *CONTRACT_MODELS,
        *PHASE1_CONTRACT_MODELS,
        *PACKET_CONTRACT_MODELS,
        *PHASE2_CONTRACT_MODELS,
        *PHASE3_CONTRACT_MODELS,
        *PHASE4_CONTRACT_MODELS,
        *PHASE4_RELATION_CONTRACT_MODELS,
        *TURN_REPAIR_CONTRACT_MODELS,
        *QUOTATION_CONTRACT_MODELS,
        *UTTERANCE_VIEW_CONTRACT_MODELS,
        *CONTEXT_WINDOW_CONTRACT_MODELS,
        *PHASE4_REVIEW_CONTRACT_MODELS,
        *PHASE4_EVALUATION_CONTRACT_MODELS,
        *PHASE4_EXPORT_CONTRACT_MODELS,
        *PHASE4_RECOVERY_CONTRACT_MODELS,
        *PHASE4_COMPLETION_CONTRACT_MODELS,
        *PHASE5_CONTRACT_MODELS,
        *PHASE5_PROVIDER_CONTRACT_MODELS,
        *PHASE5_BASELINE_CONTRACT_MODELS,
        *PHASE5_PROVIDER_ANALYSIS_CONTRACT_MODELS,
        *PHASE5_CONSOLIDATION_CONTRACT_MODELS,
        *PHASE5_QUESTION_ANSWER_CONTRACT_MODELS,
        *PHASE5_ARGUMENT_RELATION_CONTRACT_MODELS,
        *PHASE5_LEXICAL_EXAMPLE_QUOTATION_CONTRACT_MODELS,
        *PHASE5_PROCEDURAL_STATE_CONTRACT_MODELS,
        *PHASE5_REVIEW_CONTRACT_MODELS,
        *PHASE5_EVALUATION_CONTRACT_MODELS,
        *PHASE5_EXPORT_CONTRACT_MODELS,
        *PHASE5_RECOVERY_CONTRACT_MODELS,
        *PHASE5_COMPLETION_CONTRACT_MODELS,
        *CLUSTERING_CONTRACT_MODELS,
        *CLUSTERING_EVALUATION_CONTRACT_MODELS,
        *DIARIZATION_EVALUATION_CONTRACT_MODELS,
        *IDENTITY_CONTRACT_MODELS,
        *IDENTITY_BINDING_CONTRACT_MODELS,
        *IDENTITY_VIEW_CONTRACT_MODELS,
        *SPEAKER_TRANSCRIPT_CONTRACT_MODELS,
        *PARTICIPANT_SUBTITLE_CONTRACT_MODELS,
        *REFERENCE_ENROLLMENT_CONTRACT_MODELS,
        *REFERENCE_COMPARISON_CONTRACT_MODELS,
        *TRANSCRIPT_CONTRACT_MODELS,
        *CORRECTION_CONTRACT_MODELS,
        *SUBTITLE_CONTRACT_MODELS,
        *EVALUATION_CONTRACT_MODELS,
        *RECOVERY_CONTRACT_MODELS,
        *PHASE3_RECOVERY_CONTRACT_MODELS,
        *PHASE3_COMPLETION_CONTRACT_MODELS,
        *SELECTION_CONTRACT_MODELS,
        *ADDRESSING_CONTRACT_MODELS,
        *CHUNK_CONTRACT_MODELS,
        *CORPUS_CONTRACT_MODELS,
        *NORMALIZATION_CONTRACT_MODELS,
        *MATERIALIZATION_CONTRACT_MODELS,
        *QUALIFICATION_CONTRACT_MODELS,
        *VIDEO_CONTRACT_MODELS,
    ):
        path = destination / f"{model.__name__}.schema.json"
        path.write_bytes(canonical_bytes(model.model_json_schema()))
        paths.append(path)
    return paths


def configure_logging(level: str = "INFO") -> None:
    class JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            return json.dumps({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "severity": record.levelname,
                "event": getattr(record, "event", record.getMessage()),
                "operation_id": getattr(record, "operation_id", None),
                "workspace_id": getattr(record, "workspace_id", None),
                "artifact_id": getattr(record, "artifact_id", None),
                "provider_id": getattr(record, "provider_id", None),
                "error_classification": getattr(record, "error_classification", None),
            }, sort_keys=True, separators=(",", ":"))
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)






