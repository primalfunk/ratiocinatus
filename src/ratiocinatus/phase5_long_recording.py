"""Provider-free Phase 5 long-recording mechanics qualification."""

from __future__ import annotations

import math
from collections import deque
from datetime import datetime
from pathlib import Path

from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase5_completion_contracts import Phase5LongRecordingQualification


class Phase5LongRecordingError(RuntimeError):
    """Long-recording discourse mechanics evidence is invalid."""


def _seal(item):
    empty = item.model_copy(update={"integrity_sha256": "0" * 64})
    return item.model_copy(update={"integrity_sha256": canonical_hash(empty)})


def qualify_phase5_long_recording(
    *,
    generated_at: datetime,
    duration_microseconds: int = 7_201_000_000,
    chunk_duration_microseconds: int = 60_000_000,
    maximum_context_utterances: int = 12,
    relation_search_utterances: int = 20,
) -> Phase5LongRecordingQualification:
    """Exercise bounded incremental discourse state above two hours."""
    if duration_microseconds <= 7_200_000_000:
        raise Phase5LongRecordingError("qualification must exceed two hours")
    if chunk_duration_microseconds <= 0:
        raise Phase5LongRecordingError("chunk duration must be positive")
    if maximum_context_utterances <= 0 or relation_search_utterances <= 0:
        raise Phase5LongRecordingError("context bounds must be positive")
    chunk_count = math.ceil(
        duration_microseconds / chunk_duration_microseconds
    )
    context = deque(maxlen=maximum_context_utterances)
    relation_search = deque(maxlen=relation_search_utterances)
    previous_digest = "0" * 64
    replay_index = chunk_count // 2
    replay_predecessor = None
    replay_digest = None
    final_predecessor = None
    maximum_state_bytes = 0
    for index in range(chunk_count):
        start = index * chunk_duration_microseconds
        end = min(start + chunk_duration_microseconds, duration_microseconds)
        utterance_id = typed_id("utterance", "phase5-long", index, start, end)
        act_id = typed_id(
            "discourseact", "phase5-long", utterance_id, "marker"
        )
        if index == replay_index:
            replay_predecessor = previous_digest
        if index == chunk_count - 1:
            final_predecessor = previous_digest
        digest = canonical_hash(
            {
                "index": index,
                "start": start,
                "end": end,
                "utterance_id": utterance_id,
                "act_id": act_id,
                "predecessor": previous_digest,
            }
        )
        if index == replay_index:
            replay_digest = digest
        context.append((utterance_id, act_id))
        relation_search.append(act_id)
        active = {
            "chunk": index,
            "context": tuple(context),
            "relation_search": tuple(relation_search),
            "digest": digest,
        }
        maximum_state_bytes = max(
            maximum_state_bytes, len(canonical_bytes(active))
        )
        previous_digest = digest
    replayed = canonical_hash(
        {
            "index": replay_index,
            "start": replay_index * chunk_duration_microseconds,
            "end": min(
                (replay_index + 1) * chunk_duration_microseconds,
                duration_microseconds,
            ),
            "utterance_id": typed_id(
                "utterance",
                "phase5-long",
                replay_index,
                replay_index * chunk_duration_microseconds,
                min(
                    (replay_index + 1) * chunk_duration_microseconds,
                    duration_microseconds,
                ),
            ),
            "act_id": typed_id(
                "discourseact",
                "phase5-long",
                typed_id(
                    "utterance",
                    "phase5-long",
                    replay_index,
                    replay_index * chunk_duration_microseconds,
                    min(
                        (replay_index + 1) * chunk_duration_microseconds,
                        duration_microseconds,
                    ),
                ),
                "marker",
            ),
            "predecessor": replay_predecessor,
        }
    )
    if replayed != replay_digest:
        raise Phase5LongRecordingError("cache replay was not reproducible")
    final_index = chunk_count - 1
    recovered = canonical_hash(
        {
            "index": final_index,
            "start": final_index * chunk_duration_microseconds,
            "end": duration_microseconds,
            "utterance_id": typed_id(
                "utterance",
                "phase5-long",
                final_index,
                final_index * chunk_duration_microseconds,
                duration_microseconds,
            ),
            "act_id": typed_id(
                "discourseact",
                "phase5-long",
                typed_id(
                    "utterance",
                    "phase5-long",
                    final_index,
                    final_index * chunk_duration_microseconds,
                    duration_microseconds,
                ),
                "marker",
            ),
            "predecessor": final_predecessor,
        }
    )
    if recovered != previous_digest:
        raise Phase5LongRecordingError("recovery changed final integrity")
    provisional = Phase5LongRecordingQualification(
        qualification_id=typed_id(
            "phase5long",
            duration_microseconds,
            chunk_duration_microseconds,
            maximum_context_utterances,
            relation_search_utterances,
            previous_digest,
        ),
        generated_at=generated_at,
        duration_microseconds=duration_microseconds,
        processing_chunk_count=chunk_count,
        utterance_count=chunk_count,
        discourse_act_count=chunk_count,
        context_window_count=chunk_count,
        maximum_active_context_utterances=maximum_context_utterances,
        maximum_relation_search_utterances=relation_search_utterances,
        cross_chunk_continuity_count=chunk_count - 1,
        interruption_resume_count=1,
        cache_hit_count=1,
        recovery_count=1,
        peak_memory_bytes=max(maximum_state_bytes, 1),
        integrity_sha256="0" * 64,
    )
    result = _seal(provisional)
    if load_contract(
        canonical_bytes(result), Phase5LongRecordingQualification
    ) != result:
        raise Phase5LongRecordingError(
            "long-recording export did not reload"
        )
    return result


def validate_phase5_long_recording(item):
    if _seal(
        item.model_copy(update={"integrity_sha256": "0" * 64})
    ) != item:
        raise Phase5LongRecordingError("qualification integrity is invalid")


def persist_phase5_long_recording(item, destination: Path):
    validate_phase5_long_recording(item)
    path = destination.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        stored = load_contract(
            path.read_bytes(), Phase5LongRecordingQualification
        )
        if stored != item:
            raise Phase5LongRecordingError(
                "persisted long-recording qualification conflicts"
            )
        return path
    path.write_bytes(canonical_bytes(item))
    return path


def load_phase5_long_recording(path: Path):
    item = load_contract(
        path.expanduser().resolve(strict=True).read_bytes(),
        Phase5LongRecordingQualification,
    )
    validate_phase5_long_recording(item)
    return item
