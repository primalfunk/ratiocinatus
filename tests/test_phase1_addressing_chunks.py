from __future__ import annotations

import pytest

from ratiocinatus.addressing import map_interval, map_timestamp
from ratiocinatus.addressing_contracts import (
    ADDRESSING_CONTRACT_MODELS,
    MappingClassification,
    MediaInterval,
    MediaTimestamp,
    SourceTimeline,
    TimeDomain,
)
from ratiocinatus.chunk_contracts import CHUNK_CONTRACT_MODELS, ChunkPolicy
from ratiocinatus.chunking import (
    build_chunk_plan,
    chunk_local_to_source,
)


def timeline(duration: int = 1_200_000_000) -> SourceTimeline:
    return SourceTimeline(
        source_id="src_" + "a" * 32,
        source_start_microseconds=-500_000,
        source_duration_microseconds=duration,
        corpus_duration_microseconds=duration,
        mapping_offset_microseconds=-500_000,
    )


def test_addressing_and_chunk_contract_schemas_are_closed() -> None:
    for model in (*ADDRESSING_CONTRACT_MODELS, *CHUNK_CONTRACT_MODELS):
        assert model.model_json_schema().get("additionalProperties") is False


def test_point_mapping_round_trips_negative_source_start() -> None:
    source = MediaTimestamp(
        domain=TimeDomain.SOURCE_MEDIA,
        microseconds=-250_000,
    )
    forward = map_timestamp(timeline(), source)
    assert forward.classification == MappingClassification.EXACT
    assert forward.mapped == MediaTimestamp(
        domain=TimeDomain.NORMALIZED_CORPUS,
        microseconds=250_000,
    )
    reverse = map_timestamp(timeline(), forward.mapped)
    assert reverse.mapped == source


def test_out_of_bounds_point_is_unavailable_or_clipped() -> None:
    point = MediaTimestamp(
        domain=TimeDomain.SOURCE_MEDIA,
        microseconds=-1_000_000,
    )
    assert map_timestamp(
        timeline(), point
    ).classification == MappingClassification.UNAVAILABLE
    clipped = map_timestamp(timeline(), point, clip=True)
    assert clipped.classification == MappingClassification.CLIPPED
    assert clipped.mapped.microseconds == 0


def test_interval_mapping_round_trip_and_discontinuity() -> None:
    corpus = MediaInterval(
        domain=TimeDomain.NORMALIZED_CORPUS,
        start_microseconds=10_000_000,
        duration_microseconds=2_000_000,
    )
    to_source = map_interval(timeline(), corpus)
    assert to_source.mapped.start_microseconds == 9_500_000
    assert map_interval(timeline(), to_source.mapped).mapped == corpus
    with_gap = timeline().model_copy(update={
        "discontinuities": (
            MediaInterval(
                domain=TimeDomain.SOURCE_MEDIA,
                start_microseconds=10_000_000,
                duration_microseconds=100_000,
            ),
        )
    })
    assert map_interval(
        with_gap, corpus
    ).classification == MappingClassification.DISCONTINUOUS


def test_interval_clipping_and_normalized_negative_rejection() -> None:
    interval = MediaInterval(
        domain=TimeDomain.SOURCE_MEDIA,
        start_microseconds=-1_000_000,
        duration_microseconds=1_000_000,
    )
    clipped = map_interval(timeline(), interval, clip=True)
    assert clipped.classification == MappingClassification.CLIPPED
    assert clipped.mapped.start_microseconds == 0
    with pytest.raises(ValueError):
        MediaInterval(
            domain=TimeDomain.NORMALIZED_CORPUS,
            start_microseconds=-1,
            duration_microseconds=1,
        )


def test_default_chunk_plan_has_complete_stable_overlapping_coverage() -> None:
    first = build_chunk_plan(timeline())
    second = build_chunk_plan(timeline())
    assert first == second
    assert first.coverage_complete
    assert [chunk.ordinal for chunk in first.chunks] == [0, 1, 2]
    assert [chunk.corpus_interval.start_microseconds for chunk in first.chunks] == [
        0,
        595_000_000,
        1_190_000_000,
    ]
    assert first.chunks[-1].corpus_interval.start_microseconds + (
        first.chunks[-1].corpus_interval.duration_microseconds
    ) == 1_200_000_000
    assert first.chunks[1].overlap_before_microseconds == 5_000_000
    assert first.chunks[0].overlap_after_microseconds == 5_000_000
    assert first.chunks[-1].terminal_short_chunk
    assert first.maximum_coverage_multiplicity == 2


def test_chunk_policy_changes_identity_and_rejects_invalid_overlap() -> None:
    default = build_chunk_plan(timeline())
    changed = build_chunk_plan(
        timeline(),
        ChunkPolicy(
            target_duration_microseconds=300_000_000,
            overlap_microseconds=5_000_000,
            minimum_duration_microseconds=30_000_000,
            maximum_duration_microseconds=900_000_000,
        ),
    )
    assert default.plan_id != changed.plan_id
    with pytest.raises(ValueError):
        ChunkPolicy(
            target_duration_microseconds=5_000_000,
            overlap_microseconds=5_000_000,
            minimum_duration_microseconds=1_000_000,
        )


def test_chunk_local_interval_maps_to_source() -> None:
    chunk = build_chunk_plan(timeline()).chunks[1]
    local = MediaInterval(
        domain=TimeDomain.CHUNK_LOCAL,
        start_microseconds=2_000_000,
        duration_microseconds=1_000_000,
    )
    mapped = chunk_local_to_source(chunk, local)
    assert mapped.start_microseconds == (
        chunk.source_interval.start_microseconds + 2_000_000
    )
    with pytest.raises(ValueError):
        chunk_local_to_source(
            chunk,
            MediaInterval(
                domain=TimeDomain.CHUNK_LOCAL,
                start_microseconds=chunk.corpus_interval.duration_microseconds,
                duration_microseconds=1,
            ),
        )
