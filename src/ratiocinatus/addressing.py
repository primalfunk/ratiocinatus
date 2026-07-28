"""Construction and exact mapping of Phase 1 media timelines."""

from __future__ import annotations

from fractions import Fraction

from .addressing_contracts import (
    IntervalMapping,
    IntervalMappingSegment,
    MappingClassification,
    MediaInterval,
    MediaTimestamp,
    SourceTimeline,
    TimeDomain,
    TimestampMapping,
)
from .phase1_contracts import MediaInspectionResult, VideoStreamDescriptor
from .selection_contracts import StreamSelectionResult


def _rate(value: str | None) -> Fraction | None:
    if not value or value == "0/0":
        return None
    try:
        return Fraction(value)
    except (ValueError, ZeroDivisionError):
        return None


def build_source_timeline(
    inspection: MediaInspectionResult,
    selection: StreamSelectionResult,
) -> SourceTimeline:
    if not selection.valid:
        raise ValueError("cannot build a timeline from invalid stream selection")
    selected_ids = {
        item
        for item in (
            selection.audio.selected_stream_id,
            selection.video.selected_stream_id,
        )
        if item is not None
    }
    selected = {
        stream.stream_id: stream
        for stream in inspection.streams
        if stream.stream_id in selected_ids
    }
    audio = (
        selected.get(selection.audio.selected_stream_id)
        if selection.audio.selected_stream_id
        else None
    )
    video = (
        selected.get(selection.video.selected_stream_id)
        if selection.video.selected_stream_id
        else None
    )
    starts = [
        item
        for item in (
            inspection.container.start_time_microseconds,
            audio.start_time_microseconds if audio else None,
            video.start_time_microseconds if video else None,
        )
        if item is not None
    ]
    source_start = (
        inspection.container.start_time_microseconds
        if inspection.container.start_time_microseconds is not None
        else (min(starts) if starts else 0)
    )
    duration = inspection.container.duration_microseconds
    if duration is None:
        ends = [
            stream.start_time_microseconds + stream.duration_microseconds
            for stream in (audio, video)
            if stream is not None
            and stream.start_time_microseconds is not None
            and stream.duration_microseconds is not None
        ]
        if not ends:
            raise ValueError("source duration is unavailable")
        duration = max(ends) - source_start
    if duration <= 0:
        raise ValueError("source duration must be positive")
    variable_frame_rate = False
    if isinstance(video, VideoStreamDescriptor):
        average = _rate(video.average_frame_rate)
        real = _rate(video.real_frame_rate)
        variable_frame_rate = average is not None and real is not None and average != real
    return SourceTimeline(
        source_id=inspection.source_id,
        source_start_microseconds=source_start,
        source_duration_microseconds=duration,
        corpus_duration_microseconds=duration,
        audio_stream_id=audio.stream_id if audio else None,
        audio_start_microseconds=audio.start_time_microseconds if audio else None,
        audio_duration_microseconds=audio.duration_microseconds if audio else None,
        video_stream_id=video.stream_id if video else None,
        video_start_microseconds=video.start_time_microseconds if video else None,
        video_duration_microseconds=video.duration_microseconds if video else None,
        variable_frame_rate=variable_frame_rate,
        mapping_offset_microseconds=source_start,
    )


def _bounds(timeline: SourceTimeline, domain: TimeDomain) -> tuple[int, int]:
    if domain == TimeDomain.SOURCE_MEDIA:
        start = timeline.source_start_microseconds
        return start, start + timeline.source_duration_microseconds
    if domain == TimeDomain.NORMALIZED_CORPUS:
        return 0, timeline.corpus_duration_microseconds
    raise ValueError(f"timeline does not directly map domain {domain.value}")


def _target_domain(domain: TimeDomain) -> TimeDomain:
    if domain == TimeDomain.SOURCE_MEDIA:
        return TimeDomain.NORMALIZED_CORPUS
    if domain == TimeDomain.NORMALIZED_CORPUS:
        return TimeDomain.SOURCE_MEDIA
    raise ValueError(f"timeline does not directly map domain {domain.value}")


def map_timestamp(
    timeline: SourceTimeline,
    timestamp: MediaTimestamp,
    *,
    clip: bool = False,
) -> TimestampMapping:
    target_domain = _target_domain(timestamp.domain)
    lower, upper = _bounds(timeline, timestamp.domain)
    value = timestamp.microseconds
    classification = MappingClassification.EXACT
    if value < lower or value > upper:
        if not clip:
            return TimestampMapping(
                source_id=timeline.source_id,
                requested=timestamp,
                classification=MappingClassification.UNAVAILABLE,
                explanation="timestamp lies outside the mapped timeline",
            )
        value = min(max(value, lower), upper)
        classification = MappingClassification.CLIPPED
    mapped_value = (
        value - timeline.mapping_offset_microseconds
        if timestamp.domain == TimeDomain.SOURCE_MEDIA
        else value + timeline.mapping_offset_microseconds
    )
    return TimestampMapping(
        source_id=timeline.source_id,
        requested=timestamp,
        mapped=MediaTimestamp(domain=target_domain, microseconds=mapped_value),
        classification=classification,
        explanation=(
            "linear offset mapping"
            if classification == MappingClassification.EXACT
            else "timestamp clipped to timeline bounds before linear mapping"
        ),
    )


def _overlaps(left: MediaInterval, right: MediaInterval) -> bool:
    left_end = left.start_microseconds + left.duration_microseconds
    right_end = right.start_microseconds + right.duration_microseconds
    return left.start_microseconds < right_end and right.start_microseconds < left_end


def map_interval(
    timeline: SourceTimeline,
    interval: MediaInterval,
    *,
    clip: bool = False,
) -> IntervalMapping:
    target_domain = _target_domain(interval.domain)
    lower, upper = _bounds(timeline, interval.domain)
    requested_end = interval.start_microseconds + interval.duration_microseconds
    start = interval.start_microseconds
    end = requested_end
    classification = MappingClassification.EXACT
    if start < lower or end > upper:
        if not clip or end <= lower or start >= upper:
            return IntervalMapping(
                source_id=timeline.source_id,
                source_domain=interval.domain,
                target_domain=target_domain,
                requested=interval,
                classification=MappingClassification.UNAVAILABLE,
                explanation="interval lies outside the mapped timeline",
            )
        start = max(start, lower)
        end = min(end, upper)
        classification = MappingClassification.CLIPPED
    mapped_start = (
        start - timeline.mapping_offset_microseconds
        if interval.domain == TimeDomain.SOURCE_MEDIA
        else start + timeline.mapping_offset_microseconds
    )
    mapped = MediaInterval(
        domain=target_domain,
        start_microseconds=mapped_start,
        duration_microseconds=end - start,
    )
    source_interval = (
        MediaInterval(
            domain=TimeDomain.SOURCE_MEDIA,
            start_microseconds=start,
            duration_microseconds=end - start,
        )
        if interval.domain == TimeDomain.SOURCE_MEDIA
        else mapped
    )
    if any(_overlaps(source_interval, gap) for gap in timeline.discontinuities):
        classification = MappingClassification.DISCONTINUOUS
    requested_effective = MediaInterval(
        domain=interval.domain,
        start_microseconds=start,
        duration_microseconds=end - start,
    )
    return IntervalMapping(
        source_id=timeline.source_id,
        source_domain=interval.domain,
        target_domain=target_domain,
        requested=interval,
        mapped=mapped,
        classification=classification,
        segments=(
            IntervalMappingSegment(
                source=requested_effective,
                target=mapped,
                classification=classification,
            ),
        ),
        explanation=(
            "linear offset interval mapping"
            if classification == MappingClassification.EXACT
            else (
                "interval overlaps a declared source discontinuity"
                if classification == MappingClassification.DISCONTINUOUS
                else "interval clipped to timeline bounds before mapping"
            )
        ),
    )
