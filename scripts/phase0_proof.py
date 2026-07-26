"""Run the clean deterministic Phase 0 proof and emit machine evidence."""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ratiocinatus.contracts import Capability
from ratiocinatus.kernel import (
    FixedClock, MalformedProviderOutput, ProviderRegistry, Workspace,
    canonical_bytes, canonical_hash, resolve_configuration,
)
from ratiocinatus.version import __version__


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path, default=Path("reports/phase-0-proof.json")
    )
    args = parser.parse_args()
    clock = FixedClock(datetime(2000, 1, 1, tzinfo=timezone.utc))
    fixture = Path("fixtures/sources/opaque.txt").resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="ratiocinatus-proof-") as temporary:
        root = Path(temporary) / "workspace"
        config = resolve_configuration(
            ".phase0-proof", env={},
            cli_values={"deterministic": True, "copy_sources": True},
        )
        workspace = Workspace.initialize(root, config, clock)
        source = workspace.register_source(fixture, clock)
        registry = ProviderRegistry.with_mocks()
        artifact = workspace.invoke_provider(
            registry.get("mock.transcription"),
            Capability.TRANSCRIPTION, "phase-0-proof-input", clock,
        )
        integrity = workspace.validate(clock)
        replay = workspace.replay(
            artifact.creation_operation_id, registry, clock
        )
        malformed_rejected = False
        try:
            workspace.invoke_provider(
                registry.get("mock.transcription"),
                Capability.TRANSCRIPTION, "phase-0-proof-input", clock,
                mode="malformed",
            )
        except MalformedProviderOutput:
            malformed_rejected = True
        original = fixture.read_bytes()
        changed = Path(temporary) / "changed.txt"
        changed.write_bytes(original)
        changed_source = workspace.register_source(changed, clock)
        changed.write_bytes(original + b"changed")
        modified_detected = not workspace.verify_source(changed_source.source_id)
        report = {
            "application_version": __version__,
            "artifact": {
                "canonical_envelope_hash": canonical_hash(artifact),
                "id": artifact.artifact_id,
                "payload_hash": artifact.content_hash,
                "synthetic": artifact.artifact.synthetic,
            },
            "clock": clock.descriptor,
            "configuration_hash": config.snapshot_hash,
            "integrity_before_negative_case": {
                "report_id": integrity.report_id, "valid": integrity.valid,
            },
            "negative_cases": {
                "malformed_provider_rejected": malformed_rejected,
                "modified_source_detected": modified_detected,
            },
            "replay": {
                "expected_hashes": replay.expected_hashes,
                "reproduced_hashes": replay.reproduced_hashes,
                "status": replay.status.value,
            },
            "source": {
                "byte_size": source.fingerprint.byte_size,
                "fingerprint": source.fingerprint.digest,
                "id": source.source_id,
            },
            "workspace": {
                "format_version": workspace.manifest.workspace_version,
                "id": workspace.manifest.workspace_id,
            },
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_bytes(report))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if (
        integrity.valid and replay.status.value == "match"
        and malformed_rejected and modified_detected
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())

