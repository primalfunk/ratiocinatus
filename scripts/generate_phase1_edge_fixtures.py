"""Generate small technical edge fixtures for Phase 1 qualification."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

FIXTURE_VERSION = "1.0.0"
DURATION_SECONDS = 4


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(ffmpeg: str, arguments: list[str]) -> None:
    completed = subprocess.run(
        [ffmpeg, *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        shell=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"FFmpeg fixture generation failed ({completed.returncode}): "
            f"{completed.stderr.strip()}"
        )


def base_inputs() -> list[str]:
    return [
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size=160x120:rate=30:duration={DURATION_SECONDS}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:sample_rate=16000:duration={DURATION_SECONDS}",
    ]


def common_output(output: Path) -> list[str]:
    return [
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "30",
        "-c:a",
        "aac",
        "-b:a",
        "48k",
        "-shortest",
        "-map_metadata",
        "-1",
        "-movflags",
        "+faststart",
        "-n",
        str(output),
    ]


def generate(destination: Path) -> dict[str, object]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required")
    root = destination.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise FileExistsError(
            "edge fixture destination is not empty; generation never overwrites"
        )
    prefix = ["-hide_banner", "-nostdin", "-v", "error"]
    commands: dict[str, list[str]] = {}

    vfr = root / "variable-frame-rate.mp4"
    commands[vfr.name] = [
        *prefix,
        *base_inputs(),
        "-vf",
        "select='if(lt(t,2),not(mod(n,2)),not(mod(n,3)))'",
        "-fps_mode",
        "vfr",
        *common_output(vfr),
    ]

    rotation_base = root / "rotation-base.partial.mp4"
    rotation = root / "rotation-90.mp4"
    commands[rotation_base.name] = [
        *prefix,
        *base_inputs(),
        "-pix_fmt",
        "yuv420p",
        *common_output(rotation_base),
    ]
    commands[rotation.name] = [
        *prefix,
        "-display_rotation:v:0",
        "90",
        "-i",
        str(rotation_base),
        "-map",
        "0",
        "-c",
        "copy",
        "-metadata:s:v:0",
        "rotate=90",
        "-movflags",
        "+faststart",
        "-n",
        str(rotation),
    ]

    timebase = root / "unusual-time-base.mp4"
    commands[timebase.name] = [
        *prefix,
        *base_inputs(),
        "-pix_fmt",
        "yuv420p",
        "-video_track_timescale",
        "1000000",
        *common_output(timebase),
    ]

    nonsquare = root / "non-square-pixels.mp4"
    commands[nonsquare.name] = [
        *prefix,
        *base_inputs(),
        "-vf",
        "setsar=4/3",
        "-pix_fmt",
        "yuv420p",
        *common_output(nonsquare),
    ]

    unsupported = root / "unsupported-pixel-format.mp4"
    commands[unsupported.name] = [
        *prefix,
        *base_inputs(),
        "-pix_fmt",
        "yuv444p",
        *common_output(unsupported),
    ]

    damage_base = root / "damaged-base.partial.mp4"
    commands[damage_base.name] = [
        *prefix,
        *base_inputs(),
        "-pix_fmt",
        "yuv420p",
        *common_output(damage_base),
    ]

    for arguments in commands.values():
        run(ffmpeg, arguments)
    damaged = root / "damaged-truncated.mp4"
    payload = damage_base.read_bytes()
    damaged.write_bytes(payload[: max(len(payload) * 3 // 5, 1)])
    rotation_base.unlink()
    damage_base.unlink()

    artifacts = []
    for path in sorted(root.glob("*.mp4")):
        artifacts.append(
            {
                "name": path.name,
                "sha256": sha256_file(path),
                "byte_size": path.stat().st_size,
                "expected_outcome": {
                    "variable-frame-rate.mp4": "available_vfr",
                    "rotation-90.mp4": "available_rotation_preserved",
                    "unusual-time-base.mp4": "available_supported_time_base",
                    "non-square-pixels.mp4": "available_aspect_preserved",
                    "unsupported-pixel-format.mp4": "refused_pixel_format",
                    "damaged-truncated.mp4": "refused_or_inspection_rejected",
                }[path.name],
            }
        )
    manifest: dict[str, object] = {
        "fixture_version": FIXTURE_VERSION,
        "license": "Apache-2.0",
        "synthetic": True,
        "purpose": "Phase 1 technical edge-policy qualification",
        "generator": "scripts/generate_phase1_edge_fixtures.py",
        "ffmpeg_version": subprocess.run(
            [ffmpeg, "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            shell=False,
        ).stdout.splitlines()[0],
        "commands": {
            name: [
                (
                    Path(argument).name
                    if str(root) in argument
                    else argument
                )
                for argument in args
            ]
            for name, args in commands.items()
        },
        "artifacts": artifacts,
    }
    (root / "generation-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(json.dumps(generate(args.destination), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
