"""Inspection, validation, checksums, export, and comparison for proof fixtures."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .fixture_contracts import (
    FIXTURE_ID, AcousticPerturbation, EvidencePacket, FindingSeverity,
    FixtureReferenceAnnotation, FixtureValidationFinding,
    FixtureValidationReport, FixtureManifest, GenerationPolicy, LicenseManifest, LineSchedule,
    OverlapEvent, ProofFixture, ProofFixtureVariant, ScriptLine, ScriptSpeaker,
    VisualStateEvent, VoiceAssignment,
)

DEFAULT_FIXTURE_ROOT = Path("tests/fixtures/riverton_evening_access_v1")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse(model, value):
    """Parse JSON-shaped values while retaining strict runtime construction."""
    return model.model_validate_json(json.dumps(value, ensure_ascii=False))

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_lines(root: Path) -> tuple[ScriptLine, ...]:
    data = read_json(root / "script" / "line_definitions.json")
    return tuple(_parse(ScriptLine, item) for item in data["lines"])


def load_speakers(root: Path) -> tuple[ScriptSpeaker, ...]:
    data = read_json(root / "script" / "participants.json")
    return tuple(_parse(ScriptSpeaker, item) for item in data["participants"])


def inspect_fixture(root: Path = DEFAULT_FIXTURE_ROOT) -> dict[str, Any]:
    fixture = _parse(ProofFixture, read_json(root / "manifests" / "fixture.json"))
    lines = load_lines(root)
    license_manifest = _parse(LicenseManifest, 
        read_json(root / "manifests" / "license_manifest.json")
    )
    variants = {}
    for variant in ProofFixtureVariant:
        schedule_path = root / "schedules" / variant.value / "line_schedule.json"
        variants[variant.value] = {
            "generated": (root / "media" / variant.value / "forum.mp4").is_file(),
            "scheduled_lines": (
                len(read_json(schedule_path)["lines"]) if schedule_path.is_file() else 0
            ),
        }
    return {
        "fixture": fixture.model_dump(mode="json"),
        "line_count": len(lines),
        "license_status": license_manifest.distribution_status.value,
        "root": str(root),
        "variants": variants,
    }


def _probe(path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration,size:stream=index,codec_name,codec_type,width,height,r_frame_rate,sample_rate,channels",
            "-of", "json", str(path),
        ],
        check=True, capture_output=True, text=True,
    )
    return json.loads(completed.stdout)


def validate_fixture(
    root: Path = DEFAULT_FIXTURE_ROOT, *, media: bool = True
) -> FixtureValidationReport:
    findings: list[FixtureValidationFinding] = []

    def add(
        severity: FindingSeverity, code: str, message: str, subject: str | None = None
    ) -> None:
        digest = hashlib.sha256(
            f"{code}\0{message}\0{subject or ''}".encode()
        ).hexdigest()[:16]
        findings.append(FixtureValidationFinding(
            finding_id=f"fvf_{digest}", severity=severity, code=code,
            message=message, subject=subject,
        ))

    try:
        speakers = load_speakers(root)
        lines = load_lines(root)
        evidence = _parse(EvidencePacket, 
            read_json(root / "script" / "evidence_packet.json")
        )
        _parse(GenerationPolicy, 
            read_json(root / "generation" / "generation_policy.json")
        )
        license_manifest = _parse(LicenseManifest,
            read_json(root / "manifests" / "license_manifest.json")
        )
        voice_data = read_json(root / "generation" / "voice_policy.json")
        voices = tuple(_parse(VoiceAssignment, item) for item in voice_data["assignments"])
        fixture_manifest_path = root / "manifests" / "fixture_manifest.json"
        fixture_manifest = (
            _parse(FixtureManifest, read_json(fixture_manifest_path))
            if fixture_manifest_path.is_file() else None
        )
    except (OSError, KeyError, json.JSONDecodeError, ValidationError) as exc:
        add(FindingSeverity.FATAL, "CONTRACT_INVALID", str(exc))
        return FixtureValidationReport(
            valid=False, checked_media=media, findings=tuple(findings),
            line_count=0, variant_count=0,
        )

    speaker_ids = {speaker.speaker_id.value for speaker in speakers}
    line_ids = [line.line_id for line in lines]
    evidence_ids = {item.evidence_id for item in evidence.items}
    if len(lines) != 68:
        add(FindingSeverity.ERROR, "LINE_COUNT", "fixture must contain 68 lines")
    if len(line_ids) != len(set(line_ids)):
        add(FindingSeverity.ERROR, "DUPLICATE_LINE_ID", "line identifiers must be unique")
    expected_ids = [f"L{index:03d}" for index in range(1, 69)]
    if line_ids != expected_ids or [line.order for line in lines] != list(range(1, 69)):
        add(FindingSeverity.ERROR, "LINE_ORDER", "line identifiers/order are not contiguous L001-L068")
    for line in lines:
        if line.speaker_id.value not in speaker_ids:
            add(FindingSeverity.ERROR, "UNKNOWN_SPEAKER", "line has unknown speaker", line.line_id)
        actual = hashlib.sha256(line.text.encode("utf-8")).hexdigest()
        if actual != line.text_sha256:
            add(FindingSeverity.ERROR, "SCRIPT_HASH", "line text hash mismatch", line.line_id)
    required_text = {
        "L016": "three thousand six hundred dollars per month",
        "L026": "twenty-one thousand six hundred dollars",
        "L068": "controlled fictional fixture",
    }
    by_id = {line.line_id: line for line in lines}
    for line_id, phrase in required_text.items():
        if line_id not in by_id or phrase not in by_id[line_id].text:
            add(FindingSeverity.ERROR, "SPOKEN_NUMBER", f"required phrase absent: {phrase}", line_id)
    participant_names = {"L001": ("Mara Chen", "Daniel Price")}
    for line_id, names in participant_names.items():
        for name in names:
            if name not in by_id[line_id].text:
                add(FindingSeverity.ERROR, "PARTICIPANT_NAME", f"missing name {name}", line_id)

    if len(voices) != 3 or len({voice.speaker_id for voice in voices}) != 3:
        add(FindingSeverity.ERROR, "VOICE_ASSIGNMENT", "exactly one voice assignment per speaker is required")
    if any(voice.cloned_voice or voice.intentional_imitation for voice in voices):
        add(FindingSeverity.FATAL, "CLONED_VOICE", "cloned or intentionally imitated voices are prohibited")
    if len({voice.voice_id for voice in voices}) != 3:
        add(FindingSeverity.ERROR, "VOICE_DISTINCTION", "three distinct stock voice identifiers are required")
    if fixture_manifest is not None:
        hash_targets = (
            (fixture_manifest.script_sha256, root / "script" / "canonical_script.txt", "SCRIPT_VERSION_HASH"),
            (fixture_manifest.evidence_packet_sha256, root / "script" / "evidence_packet.json", "EVIDENCE_VERSION_HASH"),
            (fixture_manifest.voice_policy_sha256, root / "generation" / "voice_policy.json", "VOICE_VERSION_HASH"),
            (fixture_manifest.license_manifest_sha256, root / "manifests" / "license_manifest.json", "LICENSE_VERSION_HASH"),
        )
        for expected, target, code in hash_targets:
            if not target.is_file() or sha256_file(target) != expected:
                add(FindingSeverity.ERROR, code, "content changed without a fixture-manifest identity update", str(target))
    assets_root = root / "assets"
    if assets_root.is_dir() and any(path.is_file() for path in assets_root.rglob("*")):
        add(FindingSeverity.ERROR, "UNTRACKED_ASSET", "third-party asset directory is not permitted; graphics must be generated")
    annotations: list[FixtureReferenceAnnotation] = []
    for path in sorted((root / "reference").glob("*.json")):
        data = read_json(path)
        for item in data.get("annotations", []):
            try:
                annotation = _parse(FixtureReferenceAnnotation, item)
                annotations.append(annotation)
                unknown_lines = set(annotation.line_ids) - set(line_ids)
                unknown_evidence = set(annotation.evidence_ids) - evidence_ids
                if unknown_lines:
                    add(FindingSeverity.ERROR, "REFERENCE_LINE", f"unknown lines {sorted(unknown_lines)}", annotation.annotation_id)
                if unknown_evidence:
                    add(FindingSeverity.ERROR, "REFERENCE_EVIDENCE", f"unknown evidence {sorted(unknown_evidence)}", annotation.annotation_id)
                if annotation.category == "candidate_call" and not annotation.line_ids:
                    add(FindingSeverity.ERROR, "CALL_WITHOUT_SUPPORT", "candidate call lacks line support", annotation.annotation_id)
            except ValidationError as exc:
                add(FindingSeverity.ERROR, "REFERENCE_CONTRACT", str(exc), str(path))

    if license_manifest.distribution_status.value in {
        "blocked_pending_review", "locally_generatable_not_distributable"
    }:
        add(FindingSeverity.ERROR, "LICENSE_BLOCKED", "required fixture components are not distributable")
    for component in license_manifest.components:
        if component.required and component.license in {"unknown", "review_required"}:
            add(FindingSeverity.ERROR, "LICENSE_UNKNOWN", "required component license is unresolved", component.component_id)

    variant_count = 0
    if media and fixture_manifest is not None:
        for relative, expected in fixture_manifest.canonical_media_hashes:
            target = root / relative
            if not target.is_file() or sha256_file(target) != expected:
                add(FindingSeverity.ERROR, "CANONICAL_MEDIA_IDENTITY", "canonical media changed without fixture version replacement", relative)
    if media:
        for variant in ProofFixtureVariant:
            variant_root = root / "media" / variant.value
            schedule_root = root / "schedules" / variant.value
            required_media = [
                variant_root / "forum.mp4", variant_root / "mix.flac",
                variant_root / "stems" / "moderator.flac",
                variant_root / "stems" / "participant_a.flac",
                variant_root / "stems" / "participant_b.flac",
            ]
            if any(not path.is_file() for path in required_media):
                add(FindingSeverity.ERROR, "MEDIA_MISSING", "variant media is incomplete", variant.value)
                continue
            variant_count += 1
            try:
                schedules = tuple(_parse(LineSchedule, item) for item in read_json(
                    schedule_root / "line_schedule.json"
                )["lines"])
                overlaps = tuple(_parse(OverlapEvent, item) for item in read_json(
                    schedule_root / "overlap_schedule.json"
                )["overlaps"])
                visuals = tuple(_parse(VisualStateEvent, item) for item in read_json(
                    schedule_root / "visual_state_schedule.json"
                )["events"])
                perturbations = tuple(_parse(AcousticPerturbation, item) for item in read_json(
                    schedule_root / "perturbation_schedule.json"
                )["perturbations"])
                video_probe = _probe(required_media[0])
                audio_probe = _probe(required_media[1])
                duration_us = round(float(video_probe["format"]["duration"]) * 1_000_000)
                if not 480_000_000 <= duration_us <= 840_000_000:
                    add(FindingSeverity.ERROR, "MEDIA_DURATION", "video must be 8-14 minutes", variant.value)
                if len(schedules) != 68:
                    add(FindingSeverity.ERROR, "SCHEDULE_LINES", "schedule must contain all 68 lines", variant.value)
                for interval in (*schedules, *overlaps, *visuals, *perturbations):
                    end = interval.start_microseconds + interval.duration_microseconds
                    if end > duration_us + 100_000:
                        add(FindingSeverity.ERROR, "SCHEDULE_BOUNDS", "schedule exceeds media duration", variant.value)
                scheduled_ids = {line.line_id for line in schedules}
                for overlap in overlaps:
                    if overlap.first_line_id not in scheduled_ids or overlap.second_line_id not in scheduled_ids:
                        add(FindingSeverity.ERROR, "OVERLAP_LINE", "overlap references missing line", overlap.overlap_id)
                video_stream = next(s for s in video_probe["streams"] if s["codec_type"] == "video")
                if (
                    video_stream.get("width") != 1920
                    or video_stream.get("height") != 1080
                    or video_stream.get("r_frame_rate") != "30/1"
                ):
                    add(FindingSeverity.ERROR, "VIDEO_POLICY", "video dimensions/frame rate differ", variant.value)
                audio_stream = next(s for s in audio_probe["streams"] if s["codec_type"] == "audio")
                if audio_stream.get("sample_rate") != "48000":
                    add(FindingSeverity.ERROR, "AUDIO_POLICY", "mix sample rate differs", variant.value)
                if variant == ProofFixtureVariant.ADVERSARIAL:
                    if len(perturbations) < 4:
                        add(FindingSeverity.ERROR, "PERTURBATION_MISSING", "adversarial perturbations incomplete")
                    if sum(event.intentional_mismatch for event in visuals) != 1:
                        add(FindingSeverity.ERROR, "VISUAL_MISMATCH", "expected exactly one declared mismatch")
            except (OSError, KeyError, StopIteration, subprocess.SubprocessError, ValidationError) as exc:
                add(FindingSeverity.ERROR, "VARIANT_INVALID", str(exc), variant.value)

    checksum_path = root / "checksums" / "sha256sums.txt"
    if media and not checksum_path.is_file():
        add(FindingSeverity.ERROR, "CHECKSUM_MISSING", "checksum inventory is absent")
    elif media:
        for raw in checksum_path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            expected, relative = raw.split("  ", 1)
            target = root / relative
            if not target.is_file() or sha256_file(target) != expected:
                add(FindingSeverity.ERROR, "HASH_MISMATCH", "output hash mismatch", relative)

    if not findings:
        add(FindingSeverity.INFORMATION, "FIXTURE_VALID", "all requested fixture checks passed")
    valid = not any(
        item.severity in {FindingSeverity.ERROR, FindingSeverity.FATAL}
        for item in findings
    )
    return FixtureValidationReport(
        valid=valid, checked_media=media, findings=tuple(findings),
        line_count=len(lines), variant_count=variant_count,
    )


def write_checksums(root: Path = DEFAULT_FIXTURE_ROOT) -> Path:
    destination = root / "checksums" / "sha256sums.txt"
    destination.parent.mkdir(parents=True, exist_ok=True)
    excluded = {
        destination.resolve(),
        (root / "reports" / "fixture_validation_report.json").resolve(),
        (root / "reports" / "fixture_validation_report.txt").resolve(),
    }
    paths = [
        path for path in root.rglob("*")
        if path.is_file() and path.resolve() not in excluded
    ]
    lines = [
        f"{sha256_file(path)}  {path.relative_to(root).as_posix()}"
        for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix())
    ]
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return destination


def export_fixture(root: Path, destination: Path, *, replace: bool = False) -> Path:
    if destination.exists() and not replace:
        raise FileExistsError("refusing destructive overwrite of fixture export")
    if destination.exists():
        destination.unlink()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(root.parent))
    return destination


def compare_fixtures(left: Path, right: Path) -> dict[str, Any]:
    def inventory(root: Path) -> dict[str, str]:
        return {
            path.relative_to(root).as_posix(): sha256_file(path)
            for path in root.rglob("*") if path.is_file()
        }
    a, b = inventory(left), inventory(right)
    keys = sorted(set(a) | set(b))
    differences = [
        {"path": key, "left": a.get(key), "right": b.get(key)}
        for key in keys if a.get(key) != b.get(key)
    ]
    return {"equal": not differences, "differences": differences}


def run_generator(
    root: Path, variant: str, *, dry_run: bool = False,
    replace: bool = False, render_only: bool = False,
    line_id: str | None = None,
) -> int:
    executable = Path(".tools/tts/Scripts/python.exe")
    if not executable.is_file():
        raise FileNotFoundError("project-local TTS environment is unavailable")
    command = [
        str(executable), "scripts/generate_riverton.py",
        "--root", str(root), "--variant", variant,
    ]
    if dry_run: command.append("--dry-run")
    if replace: command.append("--replace")
    if render_only: command.append("--render-only")
    if line_id: command.extend(["--line", line_id])
    return subprocess.run(command, check=False).returncode

