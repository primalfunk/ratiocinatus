"""Generate the Riverton controlled audiovisual fixture.

This script runs inside the project-local TTS environment. It deliberately
contains no analysis: it synthesizes known lines, schedules them, creates
geometric source video, and records exact construction metadata.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw, ImageFont

FIXTURE_ID = "ratiocinatus-proof-riverton-evening-access-v1"
CONTRACT = "0.1.0"
SAMPLE_RATE = 48_000
MODEL = Path(".tools/tts/models/kokoro-v1.0.fp16.onnx")
VOICES = Path(".tools/tts/models/voices-v1.0.bin")
SPEAKER_FILES = {
    "MODERATOR": "moderator.flac",
    "PARTICIPANT_A": "participant_a.flac",
    "PARTICIPANT_B": "participant_b.flac",
}
PAN = {"MODERATOR": 0.0, "PARTICIPANT_A": -0.28, "PARTICIPANT_B": 0.28}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str], *, capture: bool = False) -> subprocess.CompletedProcess:
    print("RUN", subprocess.list2cmdline(command), flush=True)
    return subprocess.run(
        command, check=True, text=True,
        capture_output=capture,
    )


def synthesize_missing(root: Path, lines: list[dict], assignments: dict[str, dict]) -> list[dict]:
    project_src = str(Path("src").resolve())
    if project_src not in sys.path:
        sys.path.insert(0, project_src)
    from ratiocinatus.fixture_tts import KokoroOnnxTTS, TTSRequest

    raw_root = root / "generation" / "line_audio"
    raw_root.mkdir(parents=True, exist_ok=True)
    missing = [line for line in lines if not (raw_root / f"{line['line_id']}.wav").is_file()]
    if missing:
        print(f"Loading Kokoro for {len(missing)} unsynthesized lines...", flush=True)
        provider = KokoroOnnxTTS(MODEL, VOICES)
        for index, line in enumerate(missing, 1):
            assignment = assignments[line["speaker_id"]]
            started = time.perf_counter()
            result = provider.synthesize(TTSRequest(
                line_id=line["line_id"], text=line["text"],
                voice_id=assignment["voice_id"], language=assignment["language"],
                speed=assignment["speed"],
            ))
            destination = raw_root / f"{line['line_id']}.wav"
            destination.write_bytes(result.wav_bytes)
            sample_rate = result.sample_rate_hz
            samples = np.empty(result.sample_count, dtype=np.float32)
            print(
                f"[{index:02d}/{len(missing):02d}] {line['line_id']} "
                f"{len(samples)/sample_rate:.2f}s in {time.perf_counter()-started:.2f}s",
                flush=True,
            )
    invocations = []
    for line in lines:
        path = raw_root / f"{line['line_id']}.wav"
        info = sf.info(path)
        invocations.append({
            "contract_version": CONTRACT,
            "duration_microseconds": round(info.duration * 1_000_000),
            "line_id": line["line_id"],
            "output_sha256": sha256(path),
            "sample_count": info.frames,
            "sample_rate_hz": info.samplerate,
            "speaker_id": line["speaker_id"],
            "text_sha256": line["text_sha256"],
            "voice_id": assignments[line["speaker_id"]]["voice_id"],
        })
    write_json(root / "generation" / "synthesis_invocations.json", {
        "engine": "kokoro-onnx", "engine_version": "0.4.9",
        "fixture_id": FIXTURE_ID, "invocations": invocations,
        "model_sha256": sha256(MODEL), "voices_sha256": sha256(VOICES),
    })
    return invocations


def resample(samples: np.ndarray, source_rate: int) -> np.ndarray:
    if source_rate == SAMPLE_RATE:
        return samples.astype(np.float32)
    target_length = round(len(samples) * SAMPLE_RATE / source_rate)
    source_positions = np.linspace(0, len(samples) - 1, len(samples))
    target_positions = np.linspace(0, len(samples) - 1, target_length)
    return np.interp(target_positions, source_positions, samples).astype(np.float32)


def prepare_lines(root: Path, lines: list[dict], variant: str) -> dict[str, np.ndarray]:
    prepared = {}
    rng = np.random.default_rng(20260726)
    for line in lines:
        samples, rate = sf.read(
            root / "generation" / "line_audio" / f"{line['line_id']}.wav",
            dtype="float32", always_2d=False,
        )
        if samples.ndim > 1:
            samples = samples.mean(axis=1)
        samples = resample(samples, rate)
        peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
        if peak:
            samples *= min(1.0, 0.86 / peak)
        if variant in {"naturalized", "adversarial"} and line["line_id"] == "L039":
            pause = 0.35 if variant == "naturalized" else 0.55
            samples = np.concatenate((np.zeros(round(pause * SAMPLE_RATE), np.float32), samples))
        if variant in {"naturalized", "adversarial"} and line["line_id"] == "L063":
            count = round(0.18 * SAMPLE_RATE)
            breath = rng.normal(0, 0.018, count).astype(np.float32)
            breath *= np.linspace(0, 1, count, dtype=np.float32) * np.linspace(1, 0, count, dtype=np.float32)
            samples = np.concatenate((breath, np.zeros(round(0.12 * SAMPLE_RATE), np.float32), samples))
        if variant == "adversarial" and line["line_id"] == "L037":
            samples *= 10 ** (-10 / 20)
        if variant == "adversarial" and line["line_id"] == "L053":
            signal_rms = math.sqrt(float(np.mean(samples ** 2)))
            noise_rms = signal_rms / (10 ** (22 / 20))
            samples = samples + rng.normal(0, noise_rms, len(samples)).astype(np.float32)
        if variant == "adversarial" and line["line_id"] == "L058":
            samples = samples[round(0.12 * SAMPLE_RATE):]
        prepared[line["line_id"]] = np.clip(samples, -0.98, 0.98)
    return prepared


def schedule_lines(lines: list[dict], prepared: dict[str, np.ndarray], variant: str):
    overlap_targets = {}
    if variant == "naturalized":
        overlap_targets = {"L021": ("O-01", "L020", 0.55), "L041": ("O-02", "L040", 0.40)}
    elif variant == "adversarial":
        overlap_targets = {
            "L021": ("O-01", "L020", 1.10),
            "L038": ("I-01", "L037", 0.22),
            "L041": ("O-02", "L040", 0.85),
        }
    speech_seconds = sum(len(prepared[line["line_id"]]) / SAMPLE_RATE for line in lines)
    target = {"clean": 510.0, "naturalized": 505.0, "adversarial": 500.0}[variant]
    overlap_total = sum(item[2] for item in overlap_targets.values())
    base_gap = max(
        0.65 if variant == "clean" else 0.35,
        (target - 4.0 - speech_seconds + overlap_total) / (len(lines) - 1),
    )
    cursor = 2.0
    schedule = []
    overlaps = []
    previous = None
    for index, line in enumerate(lines):
        line_id = line["line_id"]
        duration = len(prepared[line_id]) / SAMPLE_RATE
        if line_id in overlap_targets and previous is not None:
            overlap_id, first_line, amount = overlap_targets[line_id]
            start = previous["end_seconds"] - amount
            overlaps.append({
                "contract_version": CONTRACT,
                "duration_microseconds": round(amount * 1_000_000),
                "first_line_id": first_line,
                "overlap_id": overlap_id,
                "second_line_id": line_id,
                "start_microseconds": round(start * 1_000_000),
            })
        else:
            start = cursor
        end = start + duration
        start_microseconds = round(start * 1_000_000)
        duration_microseconds = round(duration * 1_000_000)
        current = {
            "contract_version": CONTRACT,
            "duration_microseconds": duration_microseconds,
            "end_microseconds": start_microseconds + duration_microseconds,
            "line_id": line_id,
            "speaker_id": line["speaker_id"],
            "start_microseconds": start_microseconds,
            "start_seconds": start,
            "end_seconds": end,
        }
        schedule.append(current)
        varied = base_gap
        if variant != "clean":
            varied *= (0.72, 1.08, 0.88, 1.22)[index % 4]
        cursor = max(cursor, end) + varied
        previous = current
    duration = max(target, max(item["end_seconds"] for item in schedule) + 2.0)
    for item in schedule:
        item.pop("start_seconds"); item.pop("end_seconds")
    return schedule, overlaps, duration


def assemble_audio(
    root: Path, variant: str, lines: list[dict],
    prepared: dict[str, np.ndarray], schedule: list[dict], duration: float,
) -> None:
    media_root = root / "media" / variant
    stems_root = media_root / "stems"
    stems_root.mkdir(parents=True, exist_ok=True)
    total_samples = math.ceil(duration * SAMPLE_RATE)
    schedule_by_id = {item["line_id"]: item for item in schedule}
    stem_hashes = {}
    for speaker, filename in SPEAKER_FILES.items():
        stem = np.zeros(total_samples, dtype=np.float32)
        for line in lines:
            if line["speaker_id"] != speaker:
                continue
            segment = prepared[line["line_id"]]
            start = round(schedule_by_id[line["line_id"]]["start_microseconds"] * SAMPLE_RATE / 1_000_000)
            stem[start:start + len(segment)] += segment
        stem = np.clip(stem, -0.98, 0.98)
        path = stems_root / filename
        sf.write(path, stem, SAMPLE_RATE, format="FLAC", subtype="PCM_16")
        stem_hashes[speaker] = sha256(path)
        del stem
    mix = np.zeros((total_samples, 2), dtype=np.float32)
    for speaker, filename in SPEAKER_FILES.items():
        stem, rate = sf.read(stems_root / filename, dtype="float32")
        pan = PAN[speaker]
        left = math.sqrt((1 - pan) / 2)
        right = math.sqrt((1 + pan) / 2)
        mix[:, 0] += stem * left
        mix[:, 1] += stem * right
        del stem
    peak = float(np.max(np.abs(mix)))
    if peak > 0.92:
        mix *= 0.92 / peak
    sf.write(media_root / "mix.flac", mix, SAMPLE_RATE, format="FLAC", subtype="PCM_16")
    del mix


def visual_events(schedule: list[dict], variant: str, duration: float) -> list[dict]:
    intervals = [
        (
            item["start_microseconds"] / 1_000_000,
            item["end_microseconds"] / 1_000_000,
            item["speaker_id"], item["line_id"],
        )
        for item in schedule
    ]
    boundaries = {0.0, duration}
    for start, end, _, _ in intervals:
        boundaries.add(start); boundaries.add(end)
    l056 = next(item for item in intervals if item[3] == "L056")
    off_duration = 0.0
    if variant == "naturalized": off_duration = 0.75
    if variant == "adversarial": off_duration = 1.25
    if off_duration:
        boundaries.add(min(l056[1], l056[0] + off_duration))
    l050 = next(item for item in intervals if item[3] == "L050")
    if variant == "adversarial":
        boundaries.add(min(l050[1], l050[0] + 0.8))
    points = sorted(boundaries)
    events = []
    for index, (start, end) in enumerate(zip(points, points[1:]), 1):
        if end - start < 0.0001:
            continue
        active = [item for item in intervals if item[0] <= start + 1e-6 < item[1]]
        actual = max(active, key=lambda item: item[0])[2] if active else None
        highlighted = actual
        mismatch = False
        if off_duration and l056[0] <= start < l056[0] + off_duration:
            highlighted = None
        if variant == "adversarial" and l050[0] <= start < l050[0] + 0.8:
            highlighted = "PARTICIPANT_A"
            mismatch = True
        event = {
            "actual_speaker": actual,
            "active_speaker": highlighted,
            "contract_version": CONTRACT,
            "duration_microseconds": round((end - start) * 1_000_000),
            "event_id": f"VS-{index:03d}",
            "intentional_mismatch": mismatch,
            "start_microseconds": round(start * 1_000_000),
        }
        if events and all(
            events[-1][key] == event[key]
            for key in ("actual_speaker", "active_speaker", "intentional_mismatch")
        ):
            events[-1]["duration_microseconds"] += event["duration_microseconds"]
        else:
            events.append(event)
    for index, event in enumerate(events, 1):
        event["event_id"] = f"VS-{index:03d}"
    return events


def draw_state(path: Path, active: str | None) -> None:
    image = Image.new("RGB", (1920, 1080), (18, 24, 38))
    draw = ImageDraw.Draw(image)
    regular_path = Path("C:/Windows/Fonts/arial.ttf")
    bold_path = Path("C:/Windows/Fonts/arialbd.ttf")
    regular = ImageFont.truetype(str(regular_path), 34)
    small = ImageFont.truetype(str(regular_path), 25)
    title = ImageFont.truetype(str(bold_path), 62)
    name_font = ImageFont.truetype(str(bold_path), 38)
    draw.text((960, 72), "Riverton Evening Access Forum", fill=(240, 244, 252), font=title, anchor="ma")
    draw.text((960, 150), "Controlled proof fixture", fill=(159, 178, 207), font=regular, anchor="ma")
    panels = [
        ("MODERATOR", "Elena Ward", "Moderator", (66, 153, 225), "circle"),
        ("PARTICIPANT_A", "Mara Chen", "Participant A", (72, 187, 120), "triangle"),
        ("PARTICIPANT_B", "Daniel Price", "Participant B", (237, 137, 54), "square"),
    ]
    for index, (speaker, name, role, color, shape) in enumerate(panels):
        left = 90 + index * 610
        box = (left, 250, left + 520, 830)
        border = (250, 204, 21) if active == speaker else (72, 88, 113)
        width = 14 if active == speaker else 5
        draw.rounded_rectangle(box, radius=28, fill=(29, 39, 58), outline=border, width=width)
        cx, cy = left + 260, 465
        if shape == "circle":
            draw.ellipse((cx - 90, cy - 90, cx + 90, cy + 90), fill=color)
        elif shape == "triangle":
            draw.polygon(((cx, cy - 105), (cx - 100, cy + 80), (cx + 100, cy + 80)), fill=color)
        else:
            draw.rectangle((cx - 90, cy - 90, cx + 90, cy + 90), fill=color)
        draw.text((cx, 650), name, fill=(245, 247, 250), font=name_font, anchor="ma")
        draw.text((cx, 710), role, fill=(170, 184, 207), font=regular, anchor="ma")
        if active == speaker:
            draw.text((cx, 785), "SPEAKING", fill=(250, 204, 21), font=small, anchor="ma")
    draw.text(
        (960, 1010), "Synthetic source ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¢ No analytical annotations",
        fill=(125, 142, 168), font=small, anchor="ma",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=True)


def render_video(root: Path, variant: str, events: list[dict], duration: float) -> list[str]:
    media_root = root / "media" / variant
    frames_root = root / "generation" / "visual_frames"
    states = {event["active_speaker"] for event in events}
    state_paths = {}
    for state in states:
        name = (state or "none").lower()
        path = frames_root / f"{name}.png"
        if not path.is_file():
            draw_state(path, state)
        state_paths[state] = path.resolve()
    concat = media_root / "visual_concat.txt"
    with concat.open("w", encoding="utf-8", newline="\n") as stream:
        for event in events:
            path = state_paths[event["active_speaker"]]
            stream.write(f"file '{path.as_posix()}'\n")
            stream.write(f"duration {event['duration_microseconds']/1_000_000:.6f}\n")
        stream.write(f"file '{state_paths[events[-1]['active_speaker']].as_posix()}'\n")
    output = media_root / "forum.mp4"
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat),
        "-i", str(media_root / "mix.flac"),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
        "-r", "30", "-vsync", "cfr", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
        "-shortest", "-movflags", "+faststart", str(output),
    ]
    run(command)
    return command


def measure_loudness(path: Path) -> dict[str, float]:
    command = [
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
        "-af", "loudnorm=I=-18:TP=-1.5:LRA=11:print_format=summary",
        "-f", "null", "NUL" if os.name == "nt" else "/dev/null",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    import re
    patterns = {
        "integrated_lufs": r"Input Integrated:\s+(-?[0-9.]+) LUFS",
        "true_peak_dbtp": r"Input True Peak:\s+(-?[0-9.]+) dBTP",
        "loudness_range_lu": r"Input LRA:\s+(-?[0-9.]+) LU",
        "threshold_lufs": r"Input Threshold:\s+(-?[0-9.]+) LUFS",
    }
    result = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, completed.stderr)
        if not match:
            raise RuntimeError(f"could not parse loudness metric {key}")
        result[key] = float(match.group(1))
    return result

def perturbations(schedule: list[dict], variant: str, duration: float) -> list[dict]:
    if variant != "adversarial":
        return []
    by_id = {item["line_id"]: item for item in schedule}
    definitions = [
        ("P-01", "L037", "gain", (("gain_db", "-10"),)),
        ("P-02", "L053", "broadband_noise", (("snr_db", "22"), ("seed", "20260726"))),
        ("P-03", "L058", "initial_clip", (("clip_milliseconds", "120"),)),
        ("P-04", "L001", "voice_similarity", (("participant_a_voice", "af_bella"), ("participant_b_voice", "af_sarah"))),
    ]
    result = []
    for identifier, line_id, kind, parameters in definitions:
        line = by_id[line_id]
        start = 0 if identifier == "P-04" else line["start_microseconds"]
        span = round(duration * 1_000_000) if identifier == "P-04" else line["duration_microseconds"]
        result.append({
            "contract_version": CONTRACT, "duration_microseconds": span,
            "kind": kind, "line_id": line_id, "parameters": list(parameters),
            "perturbation_id": identifier, "start_microseconds": start,
        })
    return result


def generate(root: Path, variant: str, replace: bool, render_only: bool) -> None:
    media_root = root / "media" / variant
    final_video = media_root / "forum.mp4"
    if final_video.exists() and not replace and not render_only:
        raise FileExistsError("refusing to overwrite canonical variant without --replace")
    lines = read_json(root / "script" / "line_definitions.json")["lines"]
    voice_policy = read_json(root / "generation" / "voice_policy.json")
    assignments = {item["speaker_id"]: item for item in voice_policy["assignments"]}
    started = time.perf_counter()
    if not render_only:
        synthesize_missing(root, lines, assignments)
        prepared = prepare_lines(root, lines, variant)
        schedule, overlaps, duration = schedule_lines(lines, prepared, variant)
        media_root.mkdir(parents=True, exist_ok=True)
        assemble_audio(root, variant, lines, prepared, schedule, duration)
        events = visual_events(schedule, variant, duration)
        perturbation_items = perturbations(schedule, variant, duration)
        schedule_root = root / "schedules" / variant
        write_json(schedule_root / "line_schedule.json", {"fixture_id": FIXTURE_ID, "variant": variant, "lines": schedule})
        write_json(schedule_root / "overlap_schedule.json", {"fixture_id": FIXTURE_ID, "variant": variant, "overlaps": overlaps})
        write_json(schedule_root / "visual_state_schedule.json", {"fixture_id": FIXTURE_ID, "variant": variant, "events": events})
        write_json(schedule_root / "perturbation_schedule.json", {"fixture_id": FIXTURE_ID, "variant": variant, "perturbations": perturbation_items})
    else:
        schedule = read_json(root / "schedules" / variant / "line_schedule.json")["lines"]
        events = read_json(root / "schedules" / variant / "visual_state_schedule.json")["events"]
        overlaps = read_json(root / "schedules" / variant / "overlap_schedule.json")["overlaps"]
        perturbation_items = read_json(root / "schedules" / variant / "perturbation_schedule.json")["perturbations"]
        duration = max(item["start_microseconds"] + item["duration_microseconds"] for item in events) / 1_000_000
    command = render_video(root, variant, events, duration)
    loudness = measure_loudness(media_root / "mix.flac")
    ffmpeg_version = run(["ffmpeg", "-version"], capture=True).stdout.splitlines()[:3]
    font_paths = [Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/arialbd.ttf")]
    files = [
        media_root / "forum.mp4", media_root / "mix.flac",
        *(media_root / "stems" / filename for filename in SPEAKER_FILES.values()),
    ]
    manifest = {
        "application_version": "0.2.0",
        "assembly_command": command,
        "contract_version": CONTRACT,
        "duration_microseconds": round(duration * 1_000_000),
        "environment": {
            "ffmpeg": ffmpeg_version,
            "gpu_used": False,
            "machine": platform.machine(),
            "onnx_execution_provider": "CPUExecutionProvider",
            "operating_system": platform.platform(),
            "python": sys.version,
        },
        "files": [
            {"bytes": path.stat().st_size, "path": path.relative_to(root).as_posix(), "sha256": sha256(path)}
            for path in files
        ],
        "fixture_id": FIXTURE_ID,
        "font_inputs": [
            {"path": str(path), "sha256": sha256(path)} for path in font_paths
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generation_seconds": round(time.perf_counter() - started, 3),
        "line_count": len(schedule),
        "loudness_measurement": loudness,
        "overlap_count": len(overlaps),
        "perturbation_count": len(perturbation_items),
        "reproducibility": "configuration_equivalent; canonical media frozen by content hash",
        "variant": variant,
        "visual_state_count": len(events),
        "voice_policy_sha256": sha256(root / "generation" / "voice_policy.json"),
    }
    write_json(root / "manifests" / f"generation_manifest_{variant}.json", manifest)
    print(f"Generated {variant}: {duration:.3f}s in {manifest['generation_seconds']:.1f}s", flush=True)


def regenerate_line(root: Path, line_id: str, replace: bool) -> None:
    lines = read_json(root / "script" / "line_definitions.json")["lines"]
    line = next((item for item in lines if item["line_id"] == line_id), None)
    if line is None:
        raise ValueError(f"unknown line: {line_id}")
    voice_policy = read_json(root / "generation" / "voice_policy.json")
    assignment = next(item for item in voice_policy["assignments"] if item["speaker_id"] == line["speaker_id"])
    project_src = str(Path("src").resolve())
    if project_src not in sys.path:
        sys.path.insert(0, project_src)
    from ratiocinatus.fixture_tts import KokoroOnnxTTS, TTSRequest
    provider = KokoroOnnxTTS(MODEL, VOICES)
    result = provider.synthesize(TTSRequest(
        line_id=line["line_id"], text=line["text"],
        voice_id=assignment["voice_id"], language=assignment["language"],
        speed=assignment["speed"],
    ))
    temporary = root / "generation" / "line_audio" / f".{line_id}.regenerated.wav"
    temporary.write_bytes(result.wav_bytes)
    canonical = root / "generation" / "line_audio" / f"{line_id}.wav"
    identical = canonical.is_file() and sha256(canonical) == sha256(temporary)
    print(json.dumps({
        "canonical_sha256": sha256(canonical) if canonical.is_file() else None,
        "classification": "hash_identical" if identical else "version_changing",
        "line_id": line_id, "regenerated_sha256": sha256(temporary),
    }, indent=2))
    if replace:
        if identical:
            temporary.unlink()
        else:
            shutil.move(temporary, canonical)
            print("Controlled replacement completed; all variant media is now invalidated.")
    else:
        temporary.unlink()
        if not identical:
            print("Canonical line retained; use --replace for controlled version-changing replacement.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--variant", choices=["clean", "naturalized", "adversarial"], required=True)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--render-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--line")
    args = parser.parse_args()
    if not MODEL.is_file() or not VOICES.is_file():
        print("Kokoro model/voice files are unavailable", file=sys.stderr)
        return 4
    if args.dry_run:
        print(json.dumps({
            "action": "regenerate-line" if args.line else "generate",
            "provider": "kokoro-onnx", "root": str(args.root),
            "variant": args.variant, "would_replace": args.replace,
        }, indent=2))
        return 0
    try:
        if args.line:
            regenerate_line(args.root, args.line, args.replace)
        else:
            generate(args.root, args.variant, args.replace, args.render_only)
        return 0
    except Exception as exc:
        print(f"generation failed: {exc}", file=sys.stderr)
        return 10


if __name__ == "__main__":
    raise SystemExit(main())

