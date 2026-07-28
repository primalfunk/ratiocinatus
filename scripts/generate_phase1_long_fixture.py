"""Generate the reproducible synthetic long-recording Phase 1 fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

FIXTURE_VERSION = "1.0.0"
DEFAULT_DURATION_SECONDS = 7_201


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tool_version(executable: str) -> str:
    completed = subprocess.run(
        [executable, "-version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
        shell=False,
    )
    return completed.stdout.splitlines()[0]


def generate(destination: Path, duration_seconds: int) -> dict[str, object]:
    if duration_seconds < 7_200:
        raise ValueError("long qualification fixture must be at least two hours")
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("FFmpeg and FFprobe are required")
    root = destination.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    media = root / "phase1-long-synthetic.avi"
    manifest_path = root / "generation-manifest.json"
    if media.exists() or manifest_path.exists():
        raise FileExistsError(
            "fixture destination is not empty; generation never overwrites evidence"
        )
    partial = root / "phase1-long-synthetic.partial.avi"
    video = root / "phase1-long-synthetic.partial.h264"
    audio = root / "phase1-long-synthetic.partial.wav"
    video_arguments = [
        "-hide_banner", "-nostdin", "-v", "error",
        "-f", "lavfi", "-i",
        f"color=c=black:s=320x180:r=1:d={duration_seconds}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "35",
        "-pix_fmt", "yuv420p", "-g", "60", "-threads", "1",
        "-an", "-f", "h264", "-n", str(video),
    ]
    audio_arguments = [
        "-hide_banner", "-nostdin", "-v", "error",
        "-f", "lavfi", "-i",
        f"anullsrc=r=16000:cl=mono:d={duration_seconds}",
        "-c:a", "pcm_s16le", "-ar", "16000", "-ac", "1",
        "-map_metadata", "-1", "-fflags", "+bitexact",
        "-f", "wav", "-n", str(audio),
    ]
    mux_arguments = [
        "-hide_banner", "-nostdin", "-v", "error",
        "-fflags", "+genpts", "-r", "1",
        "-i", str(video), "-i", str(audio),
        "-map", "0:v:0", "-map", "1:a:0", "-c", "copy",
        "-map_metadata", "-1", "-max_interleave_delta", "0",
        "-f", "avi", "-n", str(partial),
    ]
    for stage, arguments in (
        ("video", video_arguments),
        ("audio", audio_arguments),
        ("mux", mux_arguments),
    ):
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
                f"fixture {stage} generation failed "
                f"({completed.returncode}): {completed.stderr.strip()}"
            )
    partial.replace(media)
    video.unlink()
    audio.unlink()
    probe = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=index,codec_type,codec_name,"
            "sample_rate,channels,width,height",
            "-of",
            "json",
            str(media),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
        shell=False,
    )
    inspection = json.loads(probe.stdout)
    manifest: dict[str, object] = {
        "fixture_version": FIXTURE_VERSION,
        "license": "Apache-2.0",
        "synthetic": True,
        "purpose": "Phase 1 long-recording ingestion qualification",
        "generator": "scripts/generate_phase1_long_fixture.py",
        "requested_duration_seconds": duration_seconds,
        "media_relative_path": media.name,
        "media_sha256": sha256_file(media),
        "media_byte_size": media.stat().st_size,
        "ffmpeg_version": tool_version(ffmpeg),
        "ffprobe_version": tool_version(ffprobe),
        "ffmpeg_stages": {
            "video_arguments": video_arguments[:-1] + [video.name],
            "audio_arguments": audio_arguments[:-1] + [audio.name],
            "mux_arguments": mux_arguments[:-1] + [media.name],
        },
        "ffprobe_result": inspection,
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    parser.add_argument(
        "--duration-seconds", type=int, default=DEFAULT_DURATION_SECONDS
    )
    args = parser.parse_args()
    print(
        json.dumps(
            generate(args.destination, args.duration_seconds),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
