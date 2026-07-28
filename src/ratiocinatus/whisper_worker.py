"""Isolated OpenAI Whisper inference worker with JSON-only output."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "item"):
        return value.item()
    return value


def main(argv: list[str] | None = None) -> int:
    arguments = list(argv) if argv is not None else sys.argv[1:]
    if len(arguments) != 1:
        raise ValueError("worker requires one request path")
    request = json.loads(
        Path(arguments[0]).resolve(strict=True).read_text(encoding="utf-8")
    )
    import whisper

    model = whisper.load_model(
        request["model_path"],
        device=request["device"],
        in_memory=False,
    )
    result = model.transcribe(
        request["audio_path"],
        language=request["language"],
        task="transcribe",
        temperature=request["temperature"],
        word_timestamps=request["word_timestamps"],
        condition_on_previous_text=False,
        clip_timestamps=request["clip_timestamps"],
        fp16=request["device"].startswith("cuda"),
        verbose=False,
    )
    sys.stdout.buffer.write(
        (
            json.dumps(
                _jsonable(result),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
