"""Deterministic operational chunk planning over normalized corpus time."""

from __future__ import annotations

from .addressing import map_interval
from .addressing_contracts import MediaInterval, SourceTimeline, TimeDomain
from .chunk_contracts import ChunkPolicy, ProcessingChunk, ProcessingChunkPlan
from .kernel import typed_id


def _maximum_multiplicity(intervals: list[tuple[int, int]]) -> int:
    events = [event for start, end in intervals for event in ((start, 1), (end, -1))]
    current = maximum = 0
    for _, delta in sorted(events, key=lambda item: (item[0], item[1])):
        current += delta
        maximum = max(maximum, current)
    return maximum


def build_chunk_plan(
    timeline: SourceTimeline,
    policy: ChunkPolicy | None = None,
) -> ProcessingChunkPlan:
    policy = policy or ChunkPolicy()
    duration = timeline.corpus_duration_microseconds
    step = policy.target_duration_microseconds - policy.overlap_microseconds
    intervals: list[tuple[int, int]] = []
    start = 0
    while True:
        end = min(start + policy.target_duration_microseconds, duration)
        intervals.append((start, end))
        if end == duration:
            break
        start += step
    plan_id = typed_id(
        "chunkplan",
        timeline.source_id,
        duration,
        policy.model_dump(mode="json"),
    )
    chunks: list[ProcessingChunk] = []
    for ordinal, (start, end) in enumerate(intervals):
        previous_end = intervals[ordinal - 1][1] if ordinal else start
        next_start = (
            intervals[ordinal + 1][0]
            if ordinal + 1 < len(intervals)
            else end
        )
        overlap_before = max(previous_end - start, 0)
        overlap_after = max(end - next_start, 0)
        corpus_interval = MediaInterval(
            domain=TimeDomain.NORMALIZED_CORPUS,
            start_microseconds=start,
            duration_microseconds=end - start,
        )
        source_mapping = map_interval(timeline, corpus_interval)
        if source_mapping.mapped is None:
            raise ValueError("chunk interval could not be mapped to source time")
        ownership_start = start + overlap_before
        ownership_interval = MediaInterval(
            domain=TimeDomain.NORMALIZED_CORPUS,
            start_microseconds=ownership_start,
            duration_microseconds=end - ownership_start,
        )
        chunk_id = typed_id(
            "chunk",
            plan_id,
            ordinal,
            start,
            end,
        )
        chunks.append(
            ProcessingChunk(
                chunk_id=chunk_id,
                ordinal=ordinal,
                corpus_interval=corpus_interval,
                source_interval=source_mapping.mapped,
                ownership_interval=ownership_interval,
                overlap_before_microseconds=overlap_before,
                overlap_after_microseconds=overlap_after,
                terminal_short_chunk=(
                    ordinal == len(intervals) - 1
                    and end - start < policy.minimum_duration_microseconds
                ),
            )
        )
    multiplicity = _maximum_multiplicity(intervals)
    return ProcessingChunkPlan(
        plan_id=plan_id,
        source_id=timeline.source_id,
        policy=policy,
        corpus_duration_microseconds=duration,
        chunks=tuple(chunks),
        coverage_complete=True,
        maximum_coverage_multiplicity=multiplicity,
    )


def chunk_local_to_source(
    chunk: ProcessingChunk,
    interval: MediaInterval,
) -> MediaInterval:
    if interval.domain != TimeDomain.CHUNK_LOCAL:
        raise ValueError("interval must use chunk-local time")
    if (
        interval.start_microseconds + interval.duration_microseconds
        > chunk.corpus_interval.duration_microseconds
    ):
        raise ValueError("chunk-local interval exceeds chunk bounds")
    return MediaInterval(
        domain=TimeDomain.SOURCE_MEDIA,
        start_microseconds=(
            chunk.source_interval.start_microseconds + interval.start_microseconds
        ),
        duration_microseconds=interval.duration_microseconds,
    )
