"""Qualify generated Phase 1 technical edge fixtures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ratiocinatus.media import inspect_media
from ratiocinatus.packets import qualify_packet_continuity
from ratiocinatus.qualification import FFmpegDecodeQualificationProvider
from ratiocinatus.selection import select_streams
from ratiocinatus.video import create_video_access_plan
from ratiocinatus.video_contracts import VideoAccessStatus


def qualify(root: Path, repeat_root: Path) -> dict[str, object]:
    root = root.resolve()
    generation = json.loads(
        (root / "generation-manifest.json").read_text(encoding="utf-8")
    )
    repeat_generation = json.loads(
        (repeat_root.resolve() / "generation-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    first_hashes = {
        item["name"]: item["sha256"] for item in generation["artifacts"]
    }
    repeat_hashes = {
        item["name"]: item["sha256"]
        for item in repeat_generation["artifacts"]
    }
    results: list[dict[str, object]] = []
    for source in sorted(root.glob("*.mp4")):
        inspection = inspect_media(source)
        selection = select_streams(inspection)
        qualification = FFmpegDecodeQualificationProvider().qualify(
            inspection, selection
        )
        packets = qualify_packet_continuity(inspection, selection)
        plan = create_video_access_plan(
            inspection, selection, qualification
        )
        result = {
            "source": source.name,
            "source_sha256": inspection.source_fingerprint.digest,
            "source_byte_size": inspection.source_fingerprint.byte_size,
            "decode_valid": qualification.valid,
            "packet_continuity_valid": packets.valid,
            "packet_probe_statuses": [
                probe.status.value for probe in packets.probes
            ],
            "packet_discontinuity_count": len(packets.discontinuities),
            "status": plan.status.value,
            "variable_frame_rate": plan.variable_frame_rate,
            "rotation_degrees": plan.rotation_degrees,
            "time_base": plan.time_base,
            "pixel_format": plan.pixel_format,
            "sample_aspect_ratio": plan.sample_aspect_ratio,
            "policy_findings": list(plan.policy_findings),
        }
        expected = {
            "variable-frame-rate.mp4": (
                plan.status == VideoAccessStatus.AVAILABLE
                and packets.valid
                and plan.variable_frame_rate
            ),
            "rotation-90.mp4": (
                plan.status == VideoAccessStatus.AVAILABLE
                and packets.valid
                and plan.rotation_degrees == 90
                and plan.transformations == ()
            ),
            "unusual-time-base.mp4": (
                plan.status == VideoAccessStatus.AVAILABLE
                and packets.valid
                and plan.time_base == "1/1000000"
            ),
            "non-square-pixels.mp4": (
                plan.status == VideoAccessStatus.AVAILABLE
                and packets.valid
                and plan.sample_aspect_ratio == "4:3"
            ),
            "unsupported-pixel-format.mp4": (
                plan.status == VideoAccessStatus.REFUSED
                and packets.valid
                and "unsupported pixel format: yuv444p"
                in plan.policy_findings
            ),
            "damaged-truncated.mp4": (
                not qualification.valid
                and packets.valid
                and plan.status == VideoAccessStatus.REFUSED
                and "video decode or timestamp qualification failed"
                in plan.policy_findings
            ),
        }[source.name]
        result["passed"] = expected
        results.append(result)
    expected_names = {
        "variable-frame-rate.mp4",
        "rotation-90.mp4",
        "unusual-time-base.mp4",
        "non-square-pixels.mp4",
        "unsupported-pixel-format.mp4",
        "damaged-truncated.mp4",
    }
    assertions = {
        "all_expected_fixtures_present": {
            item["source"] for item in results
        }
        == expected_names,
        "all_policy_outcomes_passed": all(
            item["passed"] for item in results
        ),
        "independent_repeat_byte_match": first_hashes == repeat_hashes,
    }
    return {
        "qualification": "phase-1-edge-media-policy",
        "status": "passed" if all(assertions.values()) else "failed",
        "generation_manifest": generation,
        "independent_repeat_hashes": repeat_hashes,
        "fixture_results": results,
        "assertions": assertions,
    }


def markdown(report: dict[str, object]) -> str:
    lines = [
        "# Phase 1 edge-media policy qualification",
        "",
        f"Status: **{str(report['status']).upper()}**",
        "",
        "| Fixture | Decode | Packets | Video outcome | Result |",
        "|---|---|---|---|---|",
    ]
    for item in report["fixture_results"]:
        findings = "; ".join(item["policy_findings"]) or "none"
        lines.append(
            f"| `{item['source']}` | "
            f"{'valid' if item['decode_valid'] else 'failed'} | "
            f"{'valid' if item['packet_continuity_valid'] else 'failed'} | "
            f"`{item['status']}` ({findings}) | "
            f"{'PASS' if item['passed'] else 'FAIL'} |"
        )
    lines.extend(
        [
            "",
            "VFR, rotation, pixel aspect, and supported unusual time bases remain "
            "source-passthrough metadata. Unsupported pixel formats and failed "
            "decode/timestamp qualification are explicitly refused. The truncated "
            "fixture retains structurally continuous container packet timestamps, "
            "while decoded-output qualification independently detects the damaged "
            "payload and prevents access.",
            "",
            "An independent second generation matched all six SHA-256 values.",
            "",
            "Machine-readable evidence is in "
            "`phase-1-edge-media-policy-qualification.json`.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixtures", type=Path)
    parser.add_argument("repeat_fixtures", type=Path)
    parser.add_argument("report_json", type=Path)
    parser.add_argument("report_markdown", type=Path)
    args = parser.parse_args()
    report = qualify(args.fixtures, args.repeat_fixtures)
    args.report_json.parent.mkdir(parents=True, exist_ok=True)
    args.report_json.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.report_markdown.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
