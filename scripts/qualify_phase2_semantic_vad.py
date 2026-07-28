"""Qualify the pinned semantic VAD on controlled public references."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ratiocinatus.activity_evaluation import (
    evaluate_speech_activity,
    reference_from_line_schedule,
)
from ratiocinatus.ingestion import prepare_ingestion_request, run_ingestion
from ratiocinatus.kernel import canonical_bytes
from ratiocinatus.media import sha256_file
from ratiocinatus.phase2_contracts import SpeechActivityClassification
from ratiocinatus.silero_activity import SileroSpeechActivityProvider
from ratiocinatus.speech_activity import detect_corpus_activity

from qualify_phase2_activity import generate_nonsemantic_fixture


VARIANTS = ("clean", "naturalized", "adversarial")


def _corpus_for(source: Path, workspace: Path) -> Path:
    request = prepare_ingestion_request(source, workspace)
    run_ingestion(request)
    return workspace / "ingestions" / request.ingestion_id / "corpus"


def qualify_variant(
    fixture_root: Path,
    qualification_root: Path,
    variant: str,
    provider: SileroSpeechActivityProvider,
) -> dict[str, object]:
    source = fixture_root / "media" / variant / "mix.flac"
    schedule = fixture_root / "schedules" / variant / "line_schedule.json"
    before = sha256_file(source)
    corpus_root = _corpus_for(
        source, qualification_root / "phase1" / variant
    )
    phase2_root = qualification_root / "phase2" / variant
    run, report, stored, reused_first = detect_corpus_activity(
        corpus_root, phase2_root, provider=provider
    )
    repeated, repeated_report, _, reused_second = detect_corpus_activity(
        corpus_root, phase2_root, provider=provider
    )
    reference = reference_from_line_schedule(
        schedule,
        variant=variant,
        normalized_audio_sha256=run.request.normalized_audio_sha256,
        normalized_audio_duration_microseconds=(
            run.request.normalized_audio_duration_microseconds
        ),
    )
    evaluation = evaluate_speech_activity(run, reference)
    (stored / "evaluation.json").write_bytes(canonical_bytes(evaluation))
    metrics = evaluation.metrics.model_dump(mode="json")
    return {
        "variant": variant,
        "source_sha256": before,
        "source_unchanged": before == sha256_file(source),
        "run_id": run.run_id,
        "reference_id": reference.reference_id,
        "evaluation_id": evaluation.evaluation_id,
        "provider_id": run.provider.provider_id,
        "model_version": run.provider.model_version,
        "model_fingerprint": run.provider.model_fingerprint,
        "runtime_fingerprint": run.provider.runtime_fingerprint,
        "coverage_complete": report.coverage_complete,
        "cache_first_reused": reused_first,
        "cache_second_reused": reused_second,
        "stable_repeated_run": (
            repeated.run_id == run.run_id
            and repeated_report.report_id == report.report_id
        ),
        "duration_microseconds": (
            run.request.normalized_audio_duration_microseconds
        ),
        "chunk_count": len(run.request.chunks),
        "interval_count": len(run.intervals),
        "metrics": metrics,
        "stored_relative": stored.relative_to(qualification_root).as_posix(),
    }


def qualify_nonsemantic(
    qualification_root: Path,
    provider: SileroSpeechActivityProvider,
) -> dict[str, object]:
    source = qualification_root / "sources" / "nonsemantic-activity.wav"
    generate_nonsemantic_fixture(source)
    before = sha256_file(source)
    corpus_root = _corpus_for(
        source, qualification_root / "phase1" / "nonsemantic"
    )
    run, report, _, reused_first = detect_corpus_activity(
        corpus_root,
        qualification_root / "phase2" / "nonsemantic",
        provider=provider,
    )
    repeated, _, _, reused_second = detect_corpus_activity(
        corpus_root,
        qualification_root / "phase2" / "nonsemantic",
        provider=provider,
    )
    probable_speech = sum(
        item.normalized_audio_interval.duration_microseconds
        for item in run.intervals
        if item.classification
        == SpeechActivityClassification.PROBABLE_SPEECH
    )
    uncertain = sum(
        item.normalized_audio_interval.duration_microseconds
        for item in run.intervals
        if item.classification == SpeechActivityClassification.UNCERTAIN
    )
    return {
        "source_sha256": before,
        "source_unchanged": before == sha256_file(source),
        "run_id": run.run_id,
        "coverage_complete": report.coverage_complete,
        "cache_first_reused": reused_first,
        "cache_second_reused": reused_second,
        "stable_repeated_run": repeated.run_id == run.run_id,
        "duration_microseconds": (
            run.request.normalized_audio_duration_microseconds
        ),
        "probable_speech_microseconds": probable_speech,
        "uncertain_microseconds": uncertain,
    }


def qualify(root: Path, fixture_root: Path) -> dict[str, object]:
    root.mkdir(parents=True, exist_ok=True)
    provider = SileroSpeechActivityProvider()
    results = [
        qualify_variant(fixture_root, root, variant, provider)
        for variant in VARIANTS
    ]
    nonsemantic = qualify_nonsemantic(root, provider)
    assertions = {
        "all_coverage_complete": all(
            item["coverage_complete"] for item in results
        )
        and nonsemantic["coverage_complete"],
        "all_sources_unchanged": all(
            item["source_unchanged"] for item in results
        )
        and nonsemantic["source_unchanged"],
        "all_second_runs_reused": all(
            item["cache_second_reused"] for item in results
        )
        and nonsemantic["cache_second_reused"],
        "all_repeated_runs_stable": all(
            item["stable_repeated_run"] for item in results
        )
        and nonsemantic["stable_repeated_run"],
        "all_variants_have_true_positive_speech": all(
            item["metrics"]["true_positive_microseconds"] > 0
            for item in results
        ),
        "all_metrics_are_bounded": all(
            0 <= item["metrics"][metric] <= 1
            for item in results
            for metric in ("precision", "recall", "f1")
        ),
    }
    return {
        "qualification": "phase-2-semantic-vad-controlled-evaluation",
        "status": "passed" if all(assertions.values()) else "failed",
        "provider": provider.capabilities.model_dump(mode="json"),
        "reference_policy": (
            "Public project-authored line schedules prepared before semantic "
            "VAD selection; overlapping and adjacent lines are unioned."
        ),
        "results": results,
        "nonsemantic_control": nonsemantic,
        "assertions": assertions,
        "limitations": [
            "Metrics are controlled-fixture measurements, not a general "
            "performance claim.",
            "Schedule intervals include generated line audio and may include "
            "leading or trailing synthesis silence.",
            "Uncertain output is evaluated as non-positive.",
            "Nearest-boundary error is not an onset/offset assignment score.",
            "Hidden analytical references were not read.",
        ],
    }


def markdown(report: dict[str, object]) -> str:
    lines = [
        "# Phase 2 semantic VAD controlled evaluation",
        "",
        f"Status: **{str(report['status']).upper()}**",
        "",
        "| Variant | Precision | Recall | F1 | Mean boundary error (ms) |",
        "|---|---:|---:|---:|---:|",
    ]
    for item in report["results"]:
        metrics = item["metrics"]
        lines.append(
            f"| `{item['variant']}` | {metrics['precision']:.4f} | "
            f"{metrics['recall']:.4f} | {metrics['f1']:.4f} | "
            f"{metrics['mean_boundary_error_microseconds'] / 1000:.1f} |"
        )
    control = report["nonsemantic_control"]
    lines.extend(
        [
            "",
            "The speech-free control contains silence, a 440 Hz tone, and "
            "deterministic broadband noise. Its semantic VAD output was "
            f"{control['probable_speech_microseconds']} microseconds of "
            "probable speech and "
            f"{control['uncertain_microseconds']} microseconds uncertain.",
            "",
            "These are duration-weighted controlled-fixture measurements. "
            "They do not establish general-corpus performance. Hidden "
            "analytical references were not read.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("fixture_root", type=Path)
    parser.add_argument("json_output", type=Path)
    parser.add_argument("markdown_output", type=Path)
    args = parser.parse_args()
    report = qualify(
        args.root.resolve(),
        args.fixture_root.resolve(strict=True),
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
