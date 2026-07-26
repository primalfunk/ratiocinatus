from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from ratiocinatus.fixture_cli import main as fixture_main
from ratiocinatus.fixture_contracts import (
    AcousticPerturbation, FIXTURE_CONTRACT_MODELS, LineSchedule,
    OverlapEvent, ProofFixtureVariant, SpeakerRole, VisualStateEvent,
)
from ratiocinatus.fixture_tools import (
    DEFAULT_FIXTURE_ROOT, export_fixture, inspect_fixture, load_lines,
    sha256_file, validate_fixture,
)
from ratiocinatus.fixture_tts import (
    DeterministicMockTTS, TTSProviderError, TTSRequest, orchestrate_lines,
)


def static_fixture(tmp_path: Path) -> Path:
    destination = tmp_path / "fixture"
    destination.mkdir()
    for directory in ("script", "generation", "reference", "manifests"):
        shutil.copytree(DEFAULT_FIXTURE_ROOT / directory, destination / directory)
    # Generated waveform/frame inputs are not needed by metadata-only tests.
    shutil.rmtree(destination / "generation" / "line_audio", ignore_errors=True)
    shutil.rmtree(destination / "generation" / "visual_frames", ignore_errors=True)
    return destination


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def test_fixture_contract_schemas_are_closed() -> None:
    for model in FIXTURE_CONTRACT_MODELS:
        assert model.model_json_schema().get("additionalProperties") is False


def test_script_evidence_and_stable_line_identifiers() -> None:
    lines = load_lines(DEFAULT_FIXTURE_ROOT)
    assert len(lines) == 68
    assert [line.line_id for line in lines] == [
        f"L{index:03d}" for index in range(1, 69)
    ]
    assert all(len(line.text_sha256) == 64 for line in lines)
    assert validate_fixture(DEFAULT_FIXTURE_ROOT, media=False).valid


def test_deterministic_mock_tts_and_per_line_orchestration(tmp_path: Path) -> None:
    provider = DeterministicMockTTS()
    requests = [
        TTSRequest("L001", "Synthetic one.", "mock_mod"),
        TTSRequest("L002", "Synthetic two.", "mock_a"),
    ]
    first = orchestrate_lines(provider, requests, tmp_path / "audio")
    hashes = [sha256_file(path) for path in first]
    second = orchestrate_lines(provider, requests, tmp_path / "audio", resume=False)
    assert hashes == [sha256_file(path) for path in second]
    assert provider.descriptor.mock and provider.descriptor.deterministic


def test_failed_line_recovery_preserves_completed_lines(tmp_path: Path) -> None:
    destination = tmp_path / "audio"
    requests = [
        TTSRequest("L001", "First.", "mock_mod"),
        TTSRequest("L002", "Second.", "mock_a"),
        TTSRequest("L003", "Third.", "mock_b"),
    ]
    with pytest.raises(TTSProviderError):
        orchestrate_lines(
            DeterministicMockTTS(fail_line="L002"), requests, destination
        )
    first_hash = sha256_file(destination / "L001.wav")
    assert not (destination / "L002.wav").exists()
    orchestrate_lines(DeterministicMockTTS(), requests, destination, resume=True)
    assert sha256_file(destination / "L001.wav") == first_hash
    assert (destination / "L003.wav").is_file()


def test_schedules_overlaps_perturbations_and_visual_states() -> None:
    expected_overlaps = {"clean": 0, "naturalized": 2, "adversarial": 3}
    for variant in ProofFixtureVariant:
        root = DEFAULT_FIXTURE_ROOT / "schedules" / variant.value
        lines = json.loads((root / "line_schedule.json").read_text())["lines"]
        overlaps = json.loads((root / "overlap_schedule.json").read_text())["overlaps"]
        visuals = json.loads((root / "visual_state_schedule.json").read_text())["events"]
        perturbations = json.loads(
            (root / "perturbation_schedule.json").read_text()
        )["perturbations"]
        parsed_lines = [
            LineSchedule.model_validate_json(json.dumps(item)) for item in lines
        ]
        parsed_overlaps = [
            OverlapEvent.model_validate_json(json.dumps(item)) for item in overlaps
        ]
        parsed_visuals = [
            VisualStateEvent.model_validate_json(json.dumps(item)) for item in visuals
        ]
        parsed_perturbations = [
            AcousticPerturbation.model_validate_json(json.dumps(item))
            for item in perturbations
        ]
        assert len(parsed_lines) == 68
        assert len(parsed_overlaps) == expected_overlaps[variant.value]
        assert all(
            parsed_lines[index].start_microseconds
            <= parsed_lines[index + 1].start_microseconds
            for index in range(67)
        )
        if variant == ProofFixtureVariant.ADVERSARIAL:
            assert len(parsed_perturbations) == 4
            assert sum(event.intentional_mismatch for event in parsed_visuals) == 1
        else:
            assert not parsed_perturbations


def test_manifests_checksums_references_and_license() -> None:
    report = validate_fixture(DEFAULT_FIXTURE_ROOT, media=True)
    assert report.valid and report.variant_count == 3
    checksum_lines = (
        DEFAULT_FIXTURE_ROOT / "checksums" / "sha256sums.txt"
    ).read_text().splitlines()
    assert len(checksum_lines) >= 100
    inspected = inspect_fixture(DEFAULT_FIXTURE_ROOT)
    assert inspected["license_status"] == "redistributable_with_notices"
    assert all(item["generated"] for item in inspected["variants"].values())


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("duplicate_line", "DUPLICATE_LINE_ID"),
        ("missing_line", "LINE_COUNT"),
        ("changed_script", "SCRIPT_VERSION_HASH"),
        ("changed_voice", "VOICE_VERSION_HASH"),
        ("unknown_evidence", "REFERENCE_EVIDENCE"),
        ("unsupported_call", "CALL_WITHOUT_SUPPORT"),
        ("missing_license", "LICENSE_UNKNOWN"),
        ("cloned_voice", "CONTRACT_INVALID"),
        ("untracked_asset", "UNTRACKED_ASSET"),
    ],
)
def test_controlled_metadata_negative_cases(
    tmp_path: Path, mutation: str, expected_code: str
) -> None:
    root = static_fixture(tmp_path)
    if mutation in {"duplicate_line", "missing_line"}:
        path = root / "script" / "line_definitions.json"
        data = json.loads(path.read_text())
        if mutation == "duplicate_line":
            data["lines"][1]["line_id"] = "L001"
        else:
            data["lines"].pop()
        write_json(path, data)
    elif mutation == "changed_script":
        path = root / "script" / "canonical_script.txt"
        path.write_text(path.read_text() + "changed")
    elif mutation in {"changed_voice", "cloned_voice"}:
        path = root / "generation" / "voice_policy.json"
        data = json.loads(path.read_text())
        if mutation == "changed_voice":
            data["assignments"][0]["voice_id"] = "am_michael"
        else:
            data["assignments"][0]["cloned_voice"] = True
        write_json(path, data)
    elif mutation in {"unknown_evidence", "unsupported_call"}:
        path = root / "reference" / "candidate_calls.json"
        data = json.loads(path.read_text())
        if mutation == "unknown_evidence":
            data["annotations"][0]["evidence_ids"] = ["E-99"]
        else:
            data["annotations"][0]["line_ids"] = []
        write_json(path, data)
    elif mutation == "missing_license":
        path = root / "manifests" / "license_manifest.json"
        data = json.loads(path.read_text())
        data["components"][1]["license"] = "unknown"
        write_json(path, data)
    else:
        asset = root / "assets" / "untracked.bin"
        asset.parent.mkdir(); asset.write_bytes(b"third party")
    report = validate_fixture(root, media=False)
    assert not report.valid
    assert expected_code in {finding.code for finding in report.findings}


def test_interval_contract_negative_cases() -> None:
    with pytest.raises(ValidationError):
        LineSchedule(
            line_id="L001", speaker_id=SpeakerRole.MODERATOR,
            start_microseconds=0, duration_microseconds=10,
            end_microseconds=11,
        )
    known = {f"L{index:03d}" for index in range(1, 69)}
    overlap = OverlapEvent(
        overlap_id="O-01", first_line_id="L001", second_line_id="L999",
        start_microseconds=0, duration_microseconds=10,
    )
    assert overlap.second_line_id not in known
    duration = 500
    schedule = LineSchedule(
        line_id="L001", speaker_id=SpeakerRole.MODERATOR,
        start_microseconds=490, duration_microseconds=20,
        end_microseconds=510,
    )
    assert schedule.end_microseconds > duration


def test_cli_and_destructive_export_refusal(tmp_path: Path, capsys) -> None:
    assert fixture_main(["--json", "fixture", "inspect"]) == 0
    assert json.loads(capsys.readouterr().out)["line_count"] == 68
    destination = tmp_path / "fixture.zip"
    export_fixture(DEFAULT_FIXTURE_ROOT, destination)
    with pytest.raises(FileExistsError):
        export_fixture(DEFAULT_FIXTURE_ROOT, destination)

