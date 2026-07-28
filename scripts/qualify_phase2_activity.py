"""Qualify the initial Phase 2 energy-activity baseline."""

from __future__ import annotations

import argparse
import json
import math
import random
import wave
from array import array
from pathlib import Path

from ratiocinatus.ingestion import prepare_ingestion_request, run_ingestion
from ratiocinatus.media import sha256_file
from ratiocinatus.speech_activity import detect_corpus_activity


def generate_nonsemantic_fixture(path: Path) -> None:
    """Silence, tone, deterministic noise, silence; no speech."""

    randomizer = random.Random(20260726)
    samples = array("h")
    for index in range(4 * 48_000):
        second = index / 48_000
        if 1 <= second < 2:
            value = int(
                0.25 * 32767 * math.sin(2 * math.pi * 440 * second)
            )
        elif 2 <= second < 3:
            value = randomizer.randint(-9_000, 9_000)
        else:
            value = 0
        samples.append(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(48_000)
        output.writeframes(samples.tobytes())


def qualify_source(
    source: Path,
    workspace: Path,
    phase2_root: Path,
    label: str,
) -> dict[str, object]:
    source = source.resolve(strict=True)
    before = sha256_file(source)
    request = prepare_ingestion_request(source, workspace)
    run_ingestion(request)
    corpus_root = (
        workspace / "ingestions" / request.ingestion_id / "corpus"
    )
    run, report, stored, reused_first = detect_corpus_activity(
        corpus_root, phase2_root
    )
    repeated, repeated_report, _, reused_second = detect_corpus_activity(
        corpus_root, phase2_root
    )
    after = sha256_file(source)
    measured = {
        item.classification.value: {
            "interval_count": item.interval_count,
            "duration_microseconds": item.duration_microseconds,
        }
        for item in report.measured
    }
    return {
        "label": label,
        "source_sha256": before,
        "source_byte_size": source.stat().st_size,
        "corpus_id": run.request.corpus_id,
        "run_id": run.run_id,
        "request_id": run.request.request_id,
        "status": report.status,
        "coverage_complete": report.coverage_complete,
        "addressable_duration_microseconds": (
            run.request.normalized_audio_duration_microseconds
        ),
        "interval_count": len(run.intervals),
        "boundary_count": len(run.boundaries),
        "chunk_count": len(run.request.chunks),
        "invocation_count": len(run.invocations),
        "measured": measured,
        "cache_first_reused": reused_first,
        "cache_second_reused": reused_second,
        "stable_repeated_run": (
            repeated.run_id == run.run_id
            and repeated_report.report_id == report.report_id
        ),
        "source_unchanged": before == after,
        "stored_relative": stored.relative_to(phase2_root).as_posix(),
    }


def qualify(root: Path, riverton: Path) -> dict[str, object]:
    root.mkdir(parents=True, exist_ok=True)
    synthetic = root / "sources" / "nonsemantic-activity.wav"
    generate_nonsemantic_fixture(synthetic)
    results = [
        qualify_source(
            synthetic,
            root / "phase1-synthetic",
            root / "phase2-synthetic",
            "synthetic_nonsemantic_activity",
        ),
        qualify_source(
            riverton,
            root / "phase1-riverton",
            root / "phase2-riverton",
            "riverton_clean",
        ),
    ]
    synthetic_result, riverton_result = results
    assertions = {
        "all_coverage_complete": all(
            item["coverage_complete"] for item in results
        ),
        "all_sources_unchanged": all(
            item["source_unchanged"] for item in results
        ),
        "all_second_runs_reused": all(
            item["cache_second_reused"] for item in results
        ),
        "stable_repeated_runs": all(
            item["stable_repeated_run"] for item in results
        ),
        "silence_detected_in_nonsemantic_fixture": (
            synthetic_result["measured"]["probable_non_speech"][
                "duration_microseconds"
            ]
            > 0
        ),
        "energy_false_positive_exposed": (
            synthetic_result["measured"]["probable_speech"][
                "duration_microseconds"
            ]
            > 0
        ),
        "riverton_contains_probable_activity": (
            riverton_result["measured"]["probable_speech"][
                "duration_microseconds"
            ]
            > 0
        ),
    }
    return {
        "qualification": "phase-2-energy-activity-baseline",
        "status": "passed" if all(assertions.values()) else "failed",
        "provider_status": "qualified_with_known_semantic_limit",
        "synthetic_fixture": {
            "description": (
                "Project-authored silence, 440 Hz tone, deterministic "
                "broadband noise, silence; contains no speech."
            ),
            "license": "Apache-2.0",
            "seed": 20260726,
        },
        "results": results,
        "assertions": assertions,
        "limitations": [
            "Energy activity is not a semantic voice activity detector.",
            "Tone and noise are intentionally exposed as probable-speech "
            "false positives.",
            "Scores are derived and uncalibrated.",
            "No speech precision, recall, or general quality claim is made.",
            "Hidden Riverton analytical references were not read.",
        ],
    }


def markdown(report: dict[str, object]) -> str:
    lines = [
        "# Phase 2 energy-activity baseline qualification",
        "",
        f"Status: **{str(report['status']).upper()}**",
        "",
        "| Source | Duration (µs) | Intervals | Chunks | Cache reuse | Result |",
        "|---|---:|---:|---:|---|---|",
    ]
    for item in report["results"]:
        lines.append(
            f"| `{item['label']}` | "
            f"{item['addressable_duration_microseconds']} | "
            f"{item['interval_count']} | {item['chunk_count']} | "
            f"{'yes' if item['cache_second_reused'] else 'no'} | "
            f"{'PASS' if item['coverage_complete'] else 'FAIL'} |"
        )
    lines.extend(
        [
            "",
            "The project-authored nonsemantic fixture contains silence, a tone, "
            "and deterministic noise but no speech. The baseline correctly "
            "exposes tone/noise as probable-speech false positives. This is a "
            "qualification of deterministic activity processing, coverage, "
            "ownership, persistence, and reuse—not transcription quality or "
            "semantic speech-detection accuracy.",
            "",
            "The Riverton clean source demonstrates operation over canonical "
            "Phase 1 media without reading hidden analytical references.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("riverton", type=Path)
    parser.add_argument("json_output", type=Path)
    parser.add_argument("markdown_output", type=Path)
    args = parser.parse_args()
    report = qualify(
        args.root.resolve(),
        args.riverton.resolve(strict=True),
    )
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.markdown_output.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
