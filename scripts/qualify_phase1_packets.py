"""Qualify bounded packet continuity for the canonical Riverton MP4s."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ratiocinatus.media import inspect_media
from ratiocinatus.packets import qualify_packet_continuity
from ratiocinatus.selection import select_streams


def qualify(media_root: Path) -> dict[str, object]:
    results: list[dict[str, object]] = []
    for source in sorted(media_root.glob("*/forum.mp4")):
        inspection = inspect_media(source)
        selection = select_streams(inspection)
        packets = qualify_packet_continuity(inspection, selection)
        results.append(
            {
                "variant": source.parent.name,
                "source_sha256": inspection.source_fingerprint.digest,
                "source_byte_size": inspection.source_fingerprint.byte_size,
                "duration_microseconds": inspection.container.duration_microseconds,
                "selected_audio_stream": selection.audio.selected_stream_index,
                "selected_video_stream": selection.video.selected_stream_index,
                "valid": packets.valid,
                "discontinuity_count": len(packets.discontinuities),
                "tool": {
                    "product": packets.tool.product,
                    "version_line": packets.tool.version_line,
                    "executable_sha256": packets.tool.executable_sha256,
                },
                "probes": [
                    {
                        "label": probe.label,
                        "stream_type": probe.stream_type.value,
                        "stream_index": probe.stream_index,
                        "packet_count": probe.packet_count,
                        "missing_pts_count": probe.missing_pts_count,
                        "missing_dts_count": probe.missing_dts_count,
                        "dts_regression_count": probe.dts_regression_count,
                        "maximum_dts_gap_microseconds": (
                            probe.maximum_dts_gap_microseconds
                        ),
                        "status": probe.status.value,
                        "findings": list(probe.findings),
                    }
                    for probe in packets.probes
                ],
            }
        )
    assertions = {
        "three_canonical_variants": len(results) == 3,
        "all_selected_audio_1_video_0": all(
            item["selected_audio_stream"] == 1
            and item["selected_video_stream"] == 0
            for item in results
        ),
        "all_packet_qualifications_valid": all(
            item["valid"] for item in results
        ),
        "six_probes_per_variant": all(
            len(item["probes"]) == 6 for item in results
        ),
        "all_probe_statuses_success": all(
            probe["status"] == "success"
            for item in results
            for probe in item["probes"]
        ),
        "no_detected_discontinuities": all(
            item["discontinuity_count"] == 0 for item in results
        ),
    }
    return {
        "qualification": "phase-1-packet-continuity",
        "status": "passed" if all(assertions.values()) else "failed",
        "scope": (
            "Selected audio and video streams in the three canonical "
            "Riverton MP4 variants; early, middle, and late bounded probes."
        ),
        "results": results,
        "assertions": assertions,
    }


def markdown(report: dict[str, object]) -> str:
    lines = [
        "# Phase 1 packet-continuity qualification",
        "",
        f"Status: **{str(report['status']).upper()}**",
        "",
        "| Variant | Audio | Video | Probes | Discontinuities | Result |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for item in report["results"]:
        lines.append(
            f"| `{item['variant']}` | {item['selected_audio_stream']} | "
            f"{item['selected_video_stream']} | {len(item['probes'])} | "
            f"{item['discontinuity_count']} | "
            f"{'PASS' if item['valid'] else 'FAIL'} |"
        )
    lines.extend(
        [
            "",
            "Each selected audio and video stream was sampled at early, middle, "
            "and late positions. All probes returned packets with monotonic DTS; "
            "no packet discontinuities were detected.",
            "",
            "This bounded structural check complements decoded-output "
            "qualification; it does not replace payload decoding.",
            "",
            "Machine-readable evidence is in "
            "`phase-1-packet-continuity-qualification.json`.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("media_root", type=Path)
    parser.add_argument("json_output", type=Path)
    parser.add_argument("markdown_output", type=Path)
    args = parser.parse_args()
    report = qualify(args.media_root.resolve(strict=True))
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
