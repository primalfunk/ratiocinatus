"""Qualify deterministic WebVTT and SRT presentation derivatives."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from qualify_phase2_corrections import qualify as qualify_corrections
from ratiocinatus.correction_contracts import TranscriptRevision
from ratiocinatus.kernel import load_contract
from ratiocinatus.subtitle_contracts import (
    SubtitleExportPolicy,
    SubtitleLossClassification,
)
from ratiocinatus.subtitles import export_subtitles, validate_subtitle_export

VTT_TIMING = re.compile(
    r"^\d{2,}:\d{2}:\d{2}\.\d{3} --> "
    r"\d{2,}:\d{2}:\d{2}\.\d{3}$"
)
SRT_TIMING = re.compile(
    r"^\d{2,}:\d{2}:\d{2},\d{3} --> "
    r"\d{2,}:\d{2}:\d{2},\d{3}$"
)


def _syntax_counts(root: Path) -> tuple[int, int]:
    vtt_lines = (root / "transcript.vtt").read_text(
        encoding="utf-8"
    ).splitlines()
    srt_lines = (root / "transcript.srt").read_text(
        encoding="utf-8"
    ).splitlines()
    if not vtt_lines or vtt_lines[0] != "WEBVTT":
        raise RuntimeError("WebVTT signature is invalid")
    vtt_count = sum(bool(VTT_TIMING.fullmatch(line)) for line in vtt_lines)
    srt_count = sum(bool(SRT_TIMING.fullmatch(line)) for line in srt_lines)
    return vtt_count, srt_count


def qualify(root: Path, fixture_root: Path) -> dict[str, object]:
    corrections = qualify_corrections(root, fixture_root)
    policy = SubtitleExportPolicy(
        maximum_cue_duration_microseconds=3_000_000,
        maximum_cue_characters=30,
        maximum_line_characters=15,
        maximum_lines_per_cue=2,
    )
    results: list[dict[str, object]] = []
    for item in corrections["results"]:
        variant = item["variant"]
        revision_root = root / item["stored_relative"]
        revision = load_contract(
            (revision_root / "revision.json").read_bytes(),
            TranscriptRevision,
        )
        assembly_root = (
            root
            / "phase2"
            / variant
            / "transcript-assemblies"
            / revision.base_assembly_id
        )
        destination = root / "phase2" / variant
        machine, machine_report, machine_root, machine_reused = (
            export_subtitles(assembly_root, destination, policy=policy)
        )
        corrected, corrected_report, corrected_root, corrected_reused = (
            export_subtitles(
                assembly_root,
                destination,
                revision_root=revision_root,
                view_kind=revision.current_corrected_view.view_kind,
                policy=policy,
            )
        )
        machine_repeat = export_subtitles(assembly_root, destination, policy=policy)
        corrected_repeat = export_subtitles(
            assembly_root,
            destination,
            revision_root=revision_root,
            view_kind=revision.current_corrected_view.view_kind,
            policy=policy,
        )
        validate_subtitle_export(
            machine, machine_root, report=machine_report
        )
        validate_subtitle_export(
            corrected, corrected_root, report=corrected_report
        )
        machine_vtt, machine_srt = _syntax_counts(machine_root)
        corrected_vtt, corrected_srt = _syntax_counts(corrected_root)
        machine_text = " ".join(cue.text for cue in machine.cues)
        corrected_text = " ".join(cue.text for cue in corrected.cues)
        results.append(
            {
                "variant": variant,
                "machine_export_id": machine.export_id,
                "corrected_export_id": corrected.export_id,
                "machine_version_id": machine.transcript_version_id,
                "corrected_version_id": corrected.transcript_version_id,
                "base_assembly_id": machine.base_assembly_id,
                "revision_id": corrected.revision_id,
                "machine_view": machine.view_kind.value,
                "corrected_view": corrected.view_kind.value,
                "machine_cue_count": machine_report.cue_count,
                "corrected_cue_count": corrected_report.cue_count,
                "machine_vtt_timing_count": machine_vtt,
                "machine_srt_timing_count": machine_srt,
                "corrected_vtt_timing_count": corrected_vtt,
                "corrected_srt_timing_count": corrected_srt,
                "all_cues_source_addressed": all(
                    cue.source_artifact_ids for cue in machine.cues
                )
                and all(cue.source_artifact_ids for cue in corrected.cues),
                "low_confidence_retained": any(
                    cue.low_confidence_region_ids for cue in machine.cues
                ),
                "long_cue_strategy_recorded": any(
                    loss.classification in {
                        SubtitleLossClassification.WORD_TIMING_SEGMENTATION,
                        SubtitleLossClassification.LONG_CUE_RETAINED,
                    }
                    for loss in machine.losses
                ),
                "rounding_loss_bounded": (
                    machine_report.maximum_start_rounding_loss_microseconds
                    <= 999
                    and machine_report.maximum_end_rounding_loss_microseconds
                    <= 999
                    and corrected_report.maximum_start_rounding_loss_microseconds
                    <= 999
                    and corrected_report.maximum_end_rounding_loss_microseconds
                    <= 999
                ),
                "machine_text_retained": "8p." in machine_text,
                "corrected_text_visible": "8 p.m." in corrected_text,
                "first_machine_reused": machine_reused,
                "first_corrected_reused": corrected_reused,
                "second_machine_reused": machine_repeat[3],
                "second_corrected_reused": corrected_repeat[3],
                "machine_export_relative": machine_root.relative_to(
                    root
                ).as_posix(),
                "corrected_export_relative": corrected_root.relative_to(
                    root
                ).as_posix(),
            }
        )
    assertions = {
        "correction_qualification_passed": corrections["status"] == "passed",
        "all_exports_validate": all(
            item["machine_vtt_timing_count"]
            == item["machine_srt_timing_count"]
            == item["machine_cue_count"]
            and item["corrected_vtt_timing_count"]
            == item["corrected_srt_timing_count"]
            == item["corrected_cue_count"]
            for item in results
        ),
        "all_views_and_versions_declared": all(
            item["machine_view"] == "original_machine"
            and item["corrected_view"] == "current_corrected"
            and item["machine_version_id"] != item["corrected_version_id"]
            and item["revision_id"]
            for item in results
        ),
        "all_source_references_retained": all(
            item["all_cues_source_addressed"] for item in results
        ),
        "all_low_confidence_evidence_retained": all(
            item["low_confidence_retained"] for item in results
        ),
        "all_long_cue_handling_recorded": all(
            item["long_cue_strategy_recorded"] for item in results
        ),
        "all_rounding_loss_bounded": all(
            item["rounding_loss_bounded"] for item in results
        ),
        "all_machine_and_corrected_text_distinct": all(
            item["machine_text_retained"]
            and item["corrected_text_visible"]
            for item in results
        ),
        "all_second_runs_reused": all(
            item["second_machine_reused"]
            and item["second_corrected_reused"]
            for item in results
        ),
    }
    return {
        "qualification": "phase-2-subtitle-presentation-derivatives",
        "status": "passed" if all(assertions.values()) else "failed",
        "qualification_policy": policy.model_dump(mode="json"),
        "results": results,
        "assertions": assertions,
        "limitations": [
            "WebVTT and SRT are presentation derivatives; the companion "
            "manifest remains necessary for source, confidence, policy, and "
            "loss provenance.",
            "The controlled corpus demonstrates deterministic formatting and "
            "lineage, not general subtitle readability or transcript accuracy.",
            "Corrected text-changing cues intentionally omit invalidated word "
            "evidence until a later alignment establishes it.",
        ],
    }


def markdown(report: dict[str, object]) -> str:
    lines = [
        "# Phase 2 subtitle-export qualification",
        "",
        f"Status: **{str(report['status']).upper()}**",
        "",
        "| Variant | Machine cues | Corrected cues | Source refs | Cache |",
        "|---|---:|---:|---|---|",
    ]
    for item in report["results"]:
        lines.append(
            f"| `{item['variant']}` | {item['machine_cue_count']} | "
            f"{item['corrected_cue_count']} | "
            f"{item['all_cues_source_addressed']} | "
            f"{'reused' if item['second_machine_reused'] and item['second_corrected_reused'] else 'miss'} |"
        )
    lines.extend(
        [
            "",
            "Both WebVTT and SRT were deterministically rendered and parsed "
            "for the original-machine and corrected successor views. The "
            "companion manifest declares version lineage, source references, "
            "rounding policy, uncertainty, segmentation, and known losses.",
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
