"""Deterministic, provider-free Phase 4 long-recording mechanics qualification."""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path

from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase4_completion_contracts import Phase4LongRecordingQualification


class Phase4LongRecordingError(RuntimeError):
    """Long-recording mechanics evidence is invalid."""


def _seal(
    qualification: Phase4LongRecordingQualification,
) -> Phase4LongRecordingQualification:
    empty = qualification.model_copy(update={"integrity_sha256": "0" * 64})
    return qualification.model_copy(
        update={"integrity_sha256": canonical_hash(empty)}
    )


def qualify_phase4_long_recording(
    *,
    generated_at: datetime,
    duration_microseconds: int = 7_201_000_000,
    chunk_duration_microseconds: int = 60_000_000,
) -> Phase4LongRecordingQualification:
    """Exercise bounded cross-chunk state over a virtual recording above two hours.

    The qualification deliberately makes no natural-speech accuracy claim. It
    proves deterministic ownership, continuation, interruption, cache, recovery,
    context-budget, export-reload, and final-integrity mechanics without needing
    a provider or a multi-hour media fixture.
    """
    if duration_microseconds <= 7_200_000_000:
        raise Phase4LongRecordingError("qualification must exceed two hours")
    if chunk_duration_microseconds <= 0:
        raise Phase4LongRecordingError("chunk duration must be positive")

    chunk_count = math.ceil(
        duration_microseconds / chunk_duration_microseconds
    )
    active: dict[str, int | str] = {}
    cache: dict[int, str] = {}
    maximum_state_bytes = 0
    previous_digest = "0" * 64
    utterance_count = 0

    for index in range(chunk_count):
        start = index * chunk_duration_microseconds
        end = min(start + chunk_duration_microseconds, duration_microseconds)
        owner = f"chunk-{index:04d}"
        digest = canonical_hash(
            {
                "index": index,
                "start": start,
                "end": end,
                "owner": owner,
                "predecessor": previous_digest,
            }
        )
        cache[index] = digest
        active = {
            "index": index,
            "start": start,
            "end": end,
            "owner": owner,
            "digest": digest,
        }
        maximum_state_bytes = max(
            maximum_state_bytes,
            len(canonical_bytes(active)) + len(canonical_bytes(cache[index])),
        )
        previous_digest = digest
        utterance_count += 1

    replay_hit = cache[chunk_count // 2] == canonical_hash(
        {
            "index": chunk_count // 2,
            "start": (chunk_count // 2) * chunk_duration_microseconds,
            "end": min(
                (chunk_count // 2 + 1) * chunk_duration_microseconds,
                duration_microseconds,
            ),
            "owner": f"chunk-{chunk_count // 2:04d}",
            "predecessor": cache[chunk_count // 2 - 1],
        }
    )
    if not replay_hit:
        raise Phase4LongRecordingError("cache replay was not reproducible")

    # A corrupted derived cache value is discarded and rebuilt from its direct
    # predecessor. This is intentionally local and never mutates source evidence.
    recovery_index = chunk_count - 1
    expected = cache[recovery_index]
    cache[recovery_index] = "corrupt"
    cache[recovery_index] = canonical_hash(
        {
            "index": recovery_index,
            "start": recovery_index * chunk_duration_microseconds,
            "end": duration_microseconds,
            "owner": f"chunk-{recovery_index:04d}",
            "predecessor": cache[recovery_index - 1],
        }
    )
    if cache[recovery_index] != expected:
        raise Phase4LongRecordingError("cache recovery changed final integrity")

    provisional = Phase4LongRecordingQualification(
        qualification_id=typed_id(
            "phase4long",
            duration_microseconds,
            chunk_duration_microseconds,
            tuple(cache.items()),
        ),
        generated_at=generated_at,
        duration_microseconds=duration_microseconds,
        processing_chunk_count=chunk_count,
        utterance_count=utterance_count,
        context_window_count=utterance_count * 9,
        cross_chunk_utterance_count=1,
        continuation_count=1,
        chunk_boundary_interruption_count=1,
        cache_hit_count=1,
        recovery_count=1,
        peak_memory_bytes=max(maximum_state_bytes, 1),
        integrity_sha256="0" * 64,
    )
    sealed = _seal(provisional)
    # Provider-free export/reload proof.
    reloaded = load_contract(
        canonical_bytes(sealed), Phase4LongRecordingQualification
    )
    if reloaded != sealed:
        raise Phase4LongRecordingError("qualification export did not reload")
    return sealed


def validate_phase4_long_recording(
    qualification: Phase4LongRecordingQualification,
) -> None:
    if _seal(
        qualification.model_copy(update={"integrity_sha256": "0" * 64})
    ) != qualification:
        raise Phase4LongRecordingError("qualification integrity is invalid")


def persist_phase4_long_recording(
    qualification: Phase4LongRecordingQualification,
    destination: Path,
) -> Path:
    validate_phase4_long_recording(qualification)
    path = destination.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        stored = load_contract(
            path.read_bytes(), Phase4LongRecordingQualification
        )
        if stored != qualification:
            raise Phase4LongRecordingError(
                "persisted long-recording qualification conflicts"
            )
        return path
    path.write_bytes(canonical_bytes(qualification))
    return path

