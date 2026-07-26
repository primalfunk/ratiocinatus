"""Freeze hashes, export fixture schemas, and write validation reports."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ratiocinatus.fixture_contracts import (
    FIXTURE_CONTRACT_MODELS, ProofFixtureVariant,
)
from ratiocinatus.fixture_tools import (
    DEFAULT_FIXTURE_ROOT, sha256_file, validate_fixture, write_checksums,
)


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )


def main() -> int:
    root = DEFAULT_FIXTURE_ROOT
    schema_root = Path("schemas/fixture")
    schema_root.mkdir(parents=True, exist_ok=True)
    for model in FIXTURE_CONTRACT_MODELS:
        write_json(schema_root / f"{model.__name__}.schema.json", model.model_json_schema())
    invocations = json.loads(
        (root / "generation" / "synthesis_invocations.json").read_text(encoding="utf-8")
    )["invocations"]
    write_json(root / "generation" / "line_audio_manifest.json", {
        "artifacts": [
            {
                "contract_version": "0.1.0",
                "duration_microseconds": item["duration_microseconds"],
                "line_id": item["line_id"],
                "relative_path": f"generation/line_audio/{item['line_id']}.wav",
                "sha256": item["output_sha256"],
            }
            for item in invocations
        ],
        "fixture_id": "ratiocinatus-proof-riverton-evening-access-v1",
    })
    canonical_media = sorted(
        path for path in (root / "media").rglob("*")
        if path.is_file() and path.suffix in {".mp4", ".flac"}
    )
    manifest = {
        "canonical_media_frozen": True,
        "canonical_media_hashes": [
            [path.relative_to(root).as_posix(), sha256_file(path)]
            for path in canonical_media
        ],
        "checksum_file": "checksums/sha256sums.txt",
        "contract_version": "0.1.0",
        "evidence_packet_sha256": sha256_file(root / "script" / "evidence_packet.json"),
        "fixture": json.loads((root / "manifests" / "fixture.json").read_text(encoding="utf-8")),
        "license_manifest_sha256": sha256_file(root / "manifests" / "license_manifest.json"),
        "script_sha256": sha256_file(root / "script" / "canonical_script.txt"),
        "voice_policy_sha256": sha256_file(root / "generation" / "voice_policy.json"),
    }
    write_json(root / "manifests" / "fixture_manifest.json", manifest)
    write_checksums(root)
    report = validate_fixture(root, media=True)
    report_root = root / "reports"
    write_json(
        report_root / "fixture_validation_report.json",
        report.model_dump(mode="json"),
    )
    lines = [
        "Ratiocinatus Phase 0.5 fixture validation",
        f"Fixture: {report.fixture_id}",
        f"Valid: {report.valid}",
        f"Lines: {report.line_count}",
        f"Generated variants: {report.variant_count}",
        f"Media checked: {report.checked_media}",
        "",
        "Findings:",
        *[
            f"- {finding.severity.value.upper()} {finding.code}: "
            f"{finding.message}"
            + (f" [{finding.subject}]" if finding.subject else "")
            for finding in report.findings
        ],
    ]
    report_root.mkdir(parents=True, exist_ok=True)
    (report_root / "fixture_validation_report.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0 if report.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())

