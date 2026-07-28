"""Deterministic Phase 1 audio and video stream selection."""

from __future__ import annotations

from .phase1_contracts import (
    AudioStreamDescriptor,
    MediaInspectionResult,
    MediaStreamDescriptor,
    StreamKind,
)
from .selection_contracts import (
    CandidateDisposition,
    StreamCandidateAssessment,
    StreamSelectionDecision,
    StreamSelectionPolicy,
    StreamSelectionResult,
)


class StreamSelectionError(ValueError):
    """An explicit selection request cannot be satisfied safely."""


def _candidate_streams(
    inspection: MediaInspectionResult, media_type: str
) -> tuple[MediaStreamDescriptor, ...]:
    if media_type == "audio":
        return tuple(
            stream
            for stream in inspection.streams
            if stream.stream_type == StreamKind.AUDIO
        )
    return tuple(
        stream
        for stream in inspection.streams
        if stream.stream_type in {StreamKind.VIDEO, StreamKind.ATTACHMENT}
    )


def _explicit_index(policy: StreamSelectionPolicy, media_type: str) -> int | None:
    return (
        policy.explicit_audio_stream_index
        if media_type == "audio"
        else policy.explicit_video_stream_index
    )


def _rank(
    stream: MediaStreamDescriptor,
    explicit: int | None,
    language_match: bool,
    layout_match: bool,
) -> tuple[int, ...]:
    return (
        0 if explicit == stream.stream_index else 1,
        0 if stream.disposition.default else 1,
        0 if language_match else 1,
        0 if layout_match else 1,
        stream.stream_index,
    )


def _assess(
    stream: MediaStreamDescriptor,
    policy: StreamSelectionPolicy,
    media_type: str,
) -> StreamCandidateAssessment:
    explicit = _explicit_index(policy, media_type)
    attached = (
        stream.stream_type == StreamKind.ATTACHMENT
        or stream.disposition.attached_picture
    )
    decode_supported = bool(stream.codec_name)
    language_match = bool(
        policy.preferred_languages
        and stream.language in policy.preferred_languages
    )
    layout = (
        stream.channel_layout if isinstance(stream, AudioStreamDescriptor) else None
    )
    layout_match = bool(
        policy.preferred_audio_layouts
        and layout in policy.preferred_audio_layouts
    )
    explicit_match = explicit == stream.stream_index
    reasons: list[str] = []
    warnings: list[str] = []
    if not decode_supported:
        reasons.append("codec_not_declared")
    else:
        warnings.append("decode_support_requires_qualification")
    if attached:
        reasons.append("attached_picture_excluded")
    if explicit is not None and not explicit_match:
        reasons.append("not_explicit_selection")
    eligible = not reasons
    return StreamCandidateAssessment(
        stream_id=stream.stream_id,
        stream_index=stream.stream_index,
        stream_type=stream.stream_type,
        eligible=eligible,
        decode_supported=decode_supported,
        attached_picture=attached,
        default=stream.disposition.default,
        language_match=language_match,
        layout_match=layout_match,
        explicit_index_match=explicit_match,
        rank=_rank(stream, explicit, language_match, layout_match),
        rejection_reasons=tuple(reasons),
        warnings=tuple(warnings),
        final_disposition=CandidateDisposition.DISQUALIFIED,
    )


def _with_disposition(
    assessment: StreamCandidateAssessment, disposition: CandidateDisposition
) -> StreamCandidateAssessment:
    data = assessment.model_dump()
    data["final_disposition"] = disposition
    if disposition == CandidateDisposition.REJECTED:
        data["rejection_reasons"] = (
            *assessment.rejection_reasons,
            "lower_deterministic_rank",
        )
    return StreamCandidateAssessment(**data)


def _decision(
    inspection: MediaInspectionResult,
    policy: StreamSelectionPolicy,
    media_type: str,
) -> StreamSelectionDecision:
    candidates = _candidate_streams(inspection, media_type)
    explicit = _explicit_index(policy, media_type)
    if explicit is not None and not any(
        stream.stream_index == explicit for stream in candidates
    ):
        raise StreamSelectionError(
            f"explicit {media_type} stream index {explicit} is absent or has "
            f"the wrong stream type"
        )
    assessed = tuple(_assess(stream, policy, media_type) for stream in candidates)
    eligible = sorted(
        (item for item in assessed if item.eligible), key=lambda item: item.rank
    )
    if explicit is not None and not eligible:
        raise StreamSelectionError(
            f"explicit {media_type} stream index {explicit} is not eligible"
        )
    if not eligible:
        optional_video = media_type == "video" and policy.allow_audio_only
        reason = (
            "No eligible video stream; audio-only ingestion is permitted."
            if optional_video
            else f"No eligible {media_type} stream is available."
        )
        return StreamSelectionDecision(
            media_type=media_type,
            policy_version=policy.policy_version,
            candidates=assessed,
            valid=optional_video or (media_type == "audio" and not policy.require_audio),
            explanation=reason,
        )
    selected = eligible[0]
    finalized = tuple(
        _with_disposition(
            item,
            CandidateDisposition.SELECTED
            if item.stream_id == selected.stream_id
            else (
                CandidateDisposition.REJECTED
                if item.eligible
                else CandidateDisposition.DISQUALIFIED
            ),
        )
        for item in assessed
    )
    basis = (
        "explicit configured stream"
        if explicit is not None
        else (
            "default stream"
            if selected.default
            else "first eligible stream by index"
        )
    )
    return StreamSelectionDecision(
        media_type=media_type,
        policy_version=policy.policy_version,
        candidates=finalized,
        selected_stream_id=selected.stream_id,
        selected_stream_index=selected.stream_index,
        valid=True,
        explanation=(
            f"Selected {media_type} stream {selected.stream_index} by {basis}; "
            "ties use ascending stream index."
        ),
    )


def select_streams(
    inspection: MediaInspectionResult,
    policy: StreamSelectionPolicy | None = None,
) -> StreamSelectionResult:
    policy = policy or StreamSelectionPolicy()
    audio = _decision(inspection, policy, "audio")
    video = _decision(inspection, policy, "video")
    return StreamSelectionResult(
        policy=policy,
        audio=audio,
        video=video,
        valid=audio.valid and video.valid,
    )
