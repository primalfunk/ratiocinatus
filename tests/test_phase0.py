from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from ratiocinatus.cli import EXIT_SUCCESS, main
from ratiocinatus.contracts import (
    Capability, CONTRACT_MODELS, OperationRequest, SourceFingerprint,
    SourceInterval, SourceReference, WorkspaceManifest,
)
from ratiocinatus.kernel import (
    DeterministicMockProvider, FixedClock, MalformedProviderOutput,
    ProviderError, ProviderRegistry, UnsupportedVersionError, Workspace,
    canonical_bytes, canonical_hash, load_contract, redact_secrets,
    resolve_configuration, typed_id,
)

NOW = datetime(2000, 1, 1, tzinfo=timezone.utc)


def make_workspace(tmp_path: Path) -> Workspace:
    root = tmp_path / "workspace"
    config = resolve_configuration(
        str(root), env={}, cli_values={"deterministic": True}
    )
    return Workspace.initialize(root, config, FixedClock(NOW))


def test_contract_schemas_are_derived_and_closed() -> None:
    for model in CONTRACT_MODELS:
        schema = model.model_json_schema()
        assert schema["title"] == model.__name__
        assert schema.get("additionalProperties") is False


def test_contracts_reject_unknown_malformed_and_naive_values() -> None:
    with pytest.raises(ValidationError):
        SourceFingerprint(digest="bad", byte_size=-1, surprise=True)
    with pytest.raises(ValidationError):
        SourceInterval(
            source_id="src_" + "0" * 32,
            start_microseconds=0, duration_microseconds=0,
        )
    with pytest.raises(ValidationError):
        WorkspaceManifest(
            workspace_id="ws_" + "0" * 32,
            created_at=datetime(2000, 1, 1),
            application_version="0.1.0",
            canonical_serialization_version="canonical-json-1",
            configuration_hash="0" * 64,
        )


def test_canonical_round_trip_hash_and_nonfinite_rejection() -> None:
    value = SourceReference(original="Ã©vidence.txt", display_name=None)
    raw = canonical_bytes(value)
    assert raw == canonical_bytes(value)
    assert load_contract(raw, SourceReference) == value
    assert canonical_hash(value) == canonical_hash(load_contract(raw, SourceReference))
    with pytest.raises(ValueError):
        canonical_bytes({"number": float("nan")})


def test_stable_identifiers_and_fixed_clock() -> None:
    assert typed_id("src", "same") == typed_id("src", "same")
    assert typed_id("src", "same") != typed_id("art", "same")
    clock = FixedClock(NOW)
    assert clock.now() == clock.now()
    with pytest.raises(ValueError):
        FixedClock(datetime(2000, 1, 1))


def test_configuration_precedence_and_secret_redaction(tmp_path: Path) -> None:
    cfg = resolve_configuration(
        str(tmp_path), file_values={"log_level": "DEBUG"},
        env={"RATIOCINATUS_LOG_LEVEL": "WARNING"},
        cli_values={"log_level": "ERROR"},
    )
    assert cfg.log_level == "ERROR"
    assert redact_secrets({"api_token": "secret"})["api_token"] == "[REDACTED]"
    assert "secret" not in canonical_bytes(cfg).decode()


def test_workspace_init_open_and_version_rejection(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    assert Workspace.open(ws.root).manifest == ws.manifest
    with pytest.raises(FileExistsError):
        Workspace.initialize(ws.root, ws.config, FixedClock(NOW))
    data = json.loads((ws.root / "manifest.json").read_text())
    data["workspace_version"] = "999.0.0"
    (ws.root / "manifest.json").write_text(json.dumps(data))
    with pytest.raises(UnsupportedVersionError):
        Workspace.open(ws.root)


def test_source_registration_duplicate_modified_and_integrity(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    a = tmp_path / "a"; b = tmp_path / "b"; c = tmp_path / "c"
    a.write_bytes(b"same"); b.write_bytes(b"same"); c.write_bytes(b"different")
    first = ws.register_source(a, FixedClock(NOW))
    second = ws.register_source(b, FixedClock(NOW))
    third = ws.register_source(c, FixedClock(NOW))
    assert first.source_id == second.source_id
    assert second.duplicate_of == first.source_id
    assert third.source_id != first.source_id
    assert a.read_bytes() == b"same"
    a.write_bytes(b"changed")
    assert not ws.verify_source(first.source_id)
    assert not ws.validate(FixedClock(NOW)).valid
    with pytest.raises(FileNotFoundError):
        ws.register_source(tmp_path / "missing", FixedClock(NOW))


def test_provider_registry_and_mock_negative_cases() -> None:
    registry = ProviderRegistry.with_mocks()
    assert {d.capabilities[0] for d in registry.list()} == set(Capability)
    provider = DeterministicMockProvider(Capability.TRANSCRIPTION)
    with pytest.raises(ValueError):
        registry.register(provider)
    assert provider.invoke(Capability.TRANSCRIPTION, "x") == provider.invoke(
        Capability.TRANSCRIPTION, "x"
    )
    with pytest.raises(ProviderError):
        provider.invoke(Capability.TRANSCRIPTION, "x", "failure")
    with pytest.raises(MalformedProviderOutput):
        provider.invoke(Capability.TRANSCRIPTION, "x", "malformed")


def test_artifact_commit_append_only_provenance_and_failure(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    provider = DeterministicMockProvider(Capability.EMBEDDING)
    artifact = ws.invoke_provider(provider, Capability.EMBEDDING, "input", FixedClock(NOW))
    assert (ws.root / "artifacts" / f"{artifact.artifact_id}.json").is_file()
    assert artifact.artifact.synthetic and ws.validate(FixedClock(NOW)).valid
    records = ws.root / "provenance" / "records.jsonl"
    assert len(records.read_bytes().splitlines()) == 1
    ws.invoke_provider(provider, Capability.EMBEDDING, "other", FixedClock(NOW))
    assert len(records.read_bytes().splitlines()) == 2
    with pytest.raises(ProviderError):
        ws.invoke_provider(provider, Capability.EMBEDDING, "x", FixedClock(NOW), "failure")
    assert '"status":"failed"' in (
        ws.root / "operations" / "results.jsonl"
    ).read_text()


def test_replay_match_mismatch_and_unsupported(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    registry = ProviderRegistry.with_mocks()
    artifact = ws.invoke_provider(
        registry.get("mock.transcription"), Capability.TRANSCRIPTION,
        "input", FixedClock(NOW),
    )
    assert ws.replay(
        artifact.creation_operation_id, registry, FixedClock(NOW)
    ).status.value == "match"
    path = ws.root / "artifacts" / f"{artifact.artifact_id}.json"
    data = json.loads(path.read_text()); data["content_hash"] = "f" * 64
    path.write_text(json.dumps(data))
    assert ws.replay(
        artifact.creation_operation_id, registry, FixedClock(NOW)
    ).status.value == "mismatch"
    source = tmp_path / "source"; source.write_bytes(b"x")
    ws.register_source(source, FixedClock(NOW))
    operation = next(
        o for o in ws._records("operations/requests.jsonl", OperationRequest)
        if o.operation_type == "source.register"
    )
    assert ws.replay(
        operation.operation_id, registry, FixedClock(NOW)
    ).status.value == "unsupported"


def test_lineage_integrity_export_and_cli(tmp_path: Path, capsys) -> None:
    ws = make_workspace(tmp_path)
    artifact = ws.invoke_provider(
        DeterministicMockProvider(Capability.DIARIZATION),
        Capability.DIARIZATION, "x", FixedClock(NOW),
    )
    path = ws.root / "artifacts" / f"{artifact.artifact_id}.json"
    data = json.loads(path.read_text())
    data["creation_operation_id"] = "op_" + "f" * 32
    path.write_text(json.dumps(data))
    report = ws.validate(FixedClock(NOW))
    assert not report.valid
    assert any(f.code == "MISSING_OPERATION" for f in report.findings)
    destination = tmp_path / "export"
    assert ws.export(destination) == destination
    root = tmp_path / "cli"
    assert main([
        "--json", "workspace", "init", str(root), "--deterministic"
    ]) == EXIT_SUCCESS
    assert json.loads(capsys.readouterr().out)["application_version"] == "0.2.0"
    assert main(["--json", "workspace", "validate", str(root)]) == EXIT_SUCCESS

