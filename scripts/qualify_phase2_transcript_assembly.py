"""Qualify canonical transcript assembly on controlled provider evidence."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from qualify_phase2_transcription_provider import qualify as qualify_provider
from ratiocinatus.transcript_assembly import assemble_transcript


def qualify(root: Path, fixture_root: Path) -> dict[str, object]:
    provider = qualify_provider(root, fixture_root)
    results: list[dict[str, object]] = []
    for item in provider["results"]:
        variant = item["variant"]
        corpus_roots = list(
            (root / "phase1" / variant / "ingestions").glob("*/corpus")
        )
        if len(corpus_roots) != 1:
            raise RuntimeError(
                f"expected one {variant} corpus, found {len(corpus_roots)}"
            )
        transcription_root = root / item["stored_relative"]
        assembly, report, stored, reused_first = assemble_transcript(
            corpus_roots[0],
            transcription_root,
            root / "phase2" / variant,
        )
        repeated = assemble_transcript(
            corpus_roots[0],
            transcription_root,
            root / "phase2" / variant,
        )
        classifications = Counter(
            region.classification.value
            for region in assembly.low_confidence_regions
        )
        results.append(
            {
                "variant": variant,
                "assembly_id": assembly.assembly_id,
                "version_id": assembly.version.version_id,
                "status": assembly.status.value,
                "segment_count": len(assembly.segments),
                "word_count": len(assembly.words),
                "low_confidence_region_count": len(
                    assembly.low_confidence_regions
                ),
                "low_confidence_classifications": dict(
                    sorted(classifications.items())
                ),
                "review_region_count": report.review_region_count,
                "blocking_region_count": report.blocking_region_count,
                "validation_findings": list(
                    assembly.validation_findings
                ),
                "cache_first_reused": reused_first,
                "cache_second_reused": repeated[3],
                "stable_repeated_assembly": repeated[0] == assembly,
                "segments_match_provider_observations": (
                    len(assembly.segments) == item["observation_count"]
                ),
                "words_match_provider_observations": (
                    len(assembly.words) == item["word_observation_count"]
                ),
                "stored_relative": stored.relative_to(root).as_posix(),
            }
        )
    assertions = {
        "provider_qualification_passed": provider["status"] == "passed",
        "all_assemblies_review_required_not_blocked": all(
            item["status"] == "review_required"
            and item["blocking_region_count"] == 0
            for item in results
        ),
        "all_provider_observations_promoted": all(
            item["segments_match_provider_observations"]
            for item in results
        ),
        "all_timestamped_words_promoted": all(
            item["words_match_provider_observations"]
            for item in results
        ),
        "all_uncertainty_machine_readable": all(
            item["low_confidence_region_count"] > 0
            and "unavailable_temporal_alignment_confidence"
            in item["low_confidence_classifications"]
            for item in results
        ),
        "all_second_runs_reused": all(
            item["cache_second_reused"] for item in results
        ),
        "all_repeated_assemblies_stable": all(
            item["stable_repeated_assembly"] for item in results
        ),
        "no_assembly_validation_findings": all(
            not item["validation_findings"] for item in results
        ),
    }
    return {
        "qualification": "phase-2-canonical-transcript-assembly",
        "status": "passed" if all(assertions.values()) else "failed",
        "source_provider_qualification": {
            "qualification": provider["qualification"],
            "status": provider["status"],
            "reference_policy": provider["reference_policy"],
        },
        "results": results,
        "assertions": assertions,
        "limitations": [
            "Canonical promotion preserves provider output; it does not prove "
            "that proposed text is correct.",
            "Whisper does not supply calibrated segment or word timing "
            "confidence, so every affected interval remains reviewable.",
            "Assembly creates only the original machine transcript version; "
            "corrections and subtitle exports are separate successor or "
            "presentation artifacts.",
        ],
    }


def markdown(report: dict[str, object]) -> str:
    lines = [
        "# Phase 2 canonical transcript-assembly qualification",
        "",
        f"Status: **{str(report['status']).upper()}**",
        "",
        "| Variant | Segments | Words | Review regions | Blocking | Cache |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for item in report["results"]:
        lines.append(
            f"| `{item['variant']}` | {item['segment_count']} | "
            f"{item['word_count']} | {item['review_region_count']} | "
            f"{item['blocking_region_count']} | "
            f"{'reused' if item['cache_second_reused'] else 'miss'} |"
        )
    lines.extend(
        [
            "",
            "Every validated provider observation and mapped provider-native "
            "word timestamp was promoted with stable lineage. Unavailable "
            "timing and boundary confidence remains explicit machine-readable "
            "review evidence; it is not presented as certainty.",
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
        args.root.resolve(), args.fixture_root.resolve(strict=True)
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
