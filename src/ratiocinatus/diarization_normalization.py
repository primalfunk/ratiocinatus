"""Validation and normalization for Phase 3 temporal speaker evidence."""

from __future__ import annotations

from pathlib import Path

from .addressing_contracts import MediaInterval
from .kernel import canonical_hash, typed_id
from .media import sha256_file
from .phase3_contracts import (
    DiarizationProviderResponse,
    DiarizationRequest,
    DiarizationRun,
    OverlapInterval,
    SpeakerChangeBoundary,
    SpeakerObservation,
    SpeakerTurn,
)


class DiarizationNormalizationError(RuntimeError):
    """Provider or canonical evidence violates the Phase 3 boundary."""


def _end(interval: MediaInterval) -> int:
    return interval.start_microseconds + interval.duration_microseconds


def _overlaps(left: MediaInterval, right: MediaInterval) -> bool:
    return (
        left.start_microseconds < _end(right)
        and right.start_microseconds < _end(left)
    )


def _contains(interval: MediaInterval, microseconds: int) -> bool:
    return interval.start_microseconds < microseconds < _end(interval)


def _seal(model, payload: dict):
    provisional = model(**payload, integrity_sha256="0" * 64)
    integrity = canonical_hash(
        provisional.model_dump(mode="json", exclude={"integrity_sha256"})
    )
    return model(**payload, integrity_sha256=integrity)


def _integrity_payload(item) -> dict:
    payload = item.model_dump(mode="json")
    payload.pop("integrity_sha256", None)
    return payload


def _observation_key(item) -> tuple:
    interval = item.normalized_audio_interval
    return (
        interval.start_microseconds,
        interval.duration_microseconds,
        item.provider_speaker_label,
        item.speech_interval_ids,
    )


def _canonical_aliases(response: DiarizationProviderResponse) -> dict[str, str]:
    canonical = {}
    aliases = {}
    for item in response.observations:
        if item.canonical_owner:
            key = _observation_key(item)
            if key in canonical:
                raise DiarizationNormalizationError(
                    "duplicated canonical observation at chunk transition"
                )
            canonical[key] = item.observation_id
    for item in response.observations:
        if item.canonical_owner:
            aliases[item.observation_id] = item.observation_id
            continue
        owner = canonical.get(_observation_key(item))
        if owner is None:
            raise DiarizationNormalizationError(
                "non-owner chunk observation has no canonical counterpart"
            )
        aliases[item.observation_id] = owner
    return aliases


def validate_diarization_response(
    response: DiarizationProviderResponse,
    request: DiarizationRequest,
    run_root: Path,
) -> None:
    if response.request_id != request.request_id:
        raise DiarizationNormalizationError(
            "diarization response belongs to another request"
        )
    if response.provider != request.provider:
        raise DiarizationNormalizationError(
            "diarization response provider is incompatible"
        )
    expected_hash = canonical_hash(
        {
            "request_id": request.request_id,
            "provider": response.provider.model_dump(mode="json"),
            "observations": [
                item.model_dump(mode="json") for item in response.observations
            ],
            "turns": [item.model_dump(mode="json") for item in response.turns],
            "overlaps": [
                item.model_dump(mode="json") for item in response.overlaps
            ],
            "embeddings": [
                item.model_dump(mode="json") for item in response.embeddings
            ],
        }
    )
    if response.normalized_evidence_sha256 != expected_hash:
        raise DiarizationNormalizationError(
            "normalized diarization evidence hash does not match observations"
        )

    intervals = {item.interval_id: item for item in request.speech_intervals}
    chunks = {item.chunk_id: item for item in request.chunks}
    segments = {item.segment_id: item for item in request.transcript_segments}
    embeddings = {item.embedding_id: item for item in response.embeddings}
    observations = {item.observation_id: item for item in response.observations}
    if len(embeddings) != len(response.embeddings):
        raise DiarizationNormalizationError(
            "speaker embedding identities repeat"
        )

    for observation in response.observations:
        normalized = observation.normalized_audio_interval
        for segment_id in observation.transcript_segment_ids:
            segment = segments.get(segment_id)
            if segment is None or not _overlaps(
                normalized, segment.normalized_audio_interval
            ):
                raise DiarizationNormalizationError(
                    "speaker observation references unaligned transcript evidence"
                )
        referenced = []
        for interval_id in observation.speech_interval_ids:
            interval = intervals.get(interval_id)
            if interval is None:
                raise DiarizationNormalizationError(
                    "speaker observation references unknown speech evidence"
                )
            referenced.append(interval.normalized_audio_interval)
        start = normalized.start_microseconds
        end = _end(normalized)
        if end > request.normalized_audio_duration_microseconds:
            raise DiarizationNormalizationError(
                "speaker observation exceeds normalized audio"
            )
        if not any(
            item.start_microseconds <= start and end <= _end(item)
            for item in referenced
        ):
            raise DiarizationNormalizationError(
                "speaker observation exceeds referenced speech evidence"
            )
        if (
            observation.source_interval.start_microseconds
            != start + request.source_mapping_offset_microseconds
        ):
            raise DiarizationNormalizationError(
                "speaker observation source mapping is invalid"
            )
        chunk = chunks.get(observation.processing_chunk_id)
        if chunk is None:
            raise DiarizationNormalizationError(
                "speaker observation references unknown processing chunk"
            )
        if (
            observation.chunk_local_interval.start_microseconds
            != start - chunk.corpus_interval.start_microseconds
            or start < chunk.corpus_interval.start_microseconds
            or end > _end(chunk.corpus_interval)
        ):
            raise DiarizationNormalizationError(
                "speaker observation chunk-local mapping is invalid"
            )
        ownership = chunk.ownership_interval
        actually_owned = (
            start >= ownership.start_microseconds and end <= _end(ownership)
        )
        if observation.canonical_owner != actually_owned:
            raise DiarizationNormalizationError(
                "speaker observation chunk ownership marker is invalid"
            )
        if observation.embedding_id is not None:
            embedding = embeddings.get(observation.embedding_id)
            if (
                embedding is None
                or embedding.observation_id != observation.observation_id
            ):
                raise DiarizationNormalizationError(
                    "speaker observation embedding lineage is invalid"
                )

    aliases = _canonical_aliases(response)
    canonical_observations = tuple(
        item for item in response.observations if item.canonical_owner
    )
    for turn in response.turns:
        linked = [observations[item] for item in turn.observation_ids]
        start = turn.normalized_audio_interval.start_microseconds
        end = _end(turn.normalized_audio_interval)
        if (
            turn.source_interval.start_microseconds
            != start + request.source_mapping_offset_microseconds
        ):
            raise DiarizationNormalizationError(
                "speaker turn source mapping is invalid"
            )
        if any(
            item.normalized_audio_interval.start_microseconds < start
            or _end(item.normalized_audio_interval) > end
            for item in linked
        ):
            raise DiarizationNormalizationError(
                "speaker turn does not contain its observations"
            )
        if not {aliases[item] for item in turn.observation_ids}:
            raise DiarizationNormalizationError(
                "speaker turn has no canonical observation"
            )

    for overlap in response.overlaps:
        normalized = overlap.normalized_audio_interval
        start = normalized.start_microseconds
        end = _end(normalized)
        if end > request.normalized_audio_duration_microseconds:
            raise DiarizationNormalizationError(
                "overlap interval exceeds normalized audio"
            )
        if (
            overlap.source_interval.start_microseconds
            != start + request.source_mapping_offset_microseconds
        ):
            raise DiarizationNormalizationError(
                "overlap interval source mapping is invalid"
            )
        if not any(
            _overlaps(normalized, item.normalized_audio_interval)
            for item in canonical_observations
        ):
            raise DiarizationNormalizationError(
                "overlap interval has no supporting canonical observation"
            )

    raw = response.raw_evidence
    if raw.relative_path is not None:
        relative = Path(raw.relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise DiarizationNormalizationError(
                "raw diarization evidence path is unsafe"
            )
        root = run_root.resolve()
        path = (root / relative).resolve()
        if root not in path.parents:
            raise DiarizationNormalizationError(
                "raw diarization evidence escapes its run root"
            )
        if (
            not path.is_file()
            or sha256_file(path) != raw.content_sha256
            or path.stat().st_size != raw.byte_size
        ):
            raise DiarizationNormalizationError(
                "raw diarization evidence fails integrity validation"
            )


def canonicalize_diarization(
    request: DiarizationRequest,
    response: DiarizationProviderResponse,
) -> DiarizationRun:
    created_at = response.completed_at
    aliases = _canonical_aliases(response)
    segments = request.transcript_segments
    words = request.transcript_words

    observations = []
    for item in response.observations:
        if not item.canonical_owner:
            continue
        aligned_segments = tuple(
            segment.segment_id
            for segment in segments
            if _overlaps(
                item.normalized_audio_interval,
                segment.normalized_audio_interval,
            )
        )
        payload = {
            "observation_id": item.observation_id,
            "corpus_id": request.corpus_id,
            "source_id": request.source_id,
            "selected_audio_stream_id": request.selected_audio_stream_id,
            "speech_activity_run_id": request.speech_activity_run_id,
            "speech_interval_ids": item.speech_interval_ids,
            "transcript_segment_ids": aligned_segments,
            "source_interval": item.source_interval,
            "normalized_audio_interval": item.normalized_audio_interval,
            "chunk_local_interval": item.chunk_local_interval,
            "processing_chunk_id": item.processing_chunk_id,
            "canonical_owner": True,
            "acoustic_evidence_available": item.acoustic_evidence_available,
            "usability": item.usability,
            "usability_confidence": item.usability_confidence,
            "provider": response.provider,
            "provider_response_id": response.response_id,
            "embedding_id": item.embedding_id,
            "created_at": created_at,
        }
        observations.append(_seal(SpeakerObservation, payload))

    observation_map = {item.observation_id: item for item in observations}
    ordered_turns = sorted(
        response.turns,
        key=lambda item: (
            item.normalized_audio_interval.start_microseconds,
            item.provider_turn_id,
        ),
    )
    turn_rows = []
    for item in ordered_turns:
        observation_ids = tuple(
            dict.fromkeys(aliases[value] for value in item.observation_ids)
        )
        linked = [observation_map[value] for value in observation_ids]
        aligned_segments = tuple(
            segment.segment_id
            for segment in segments
            if _overlaps(
                item.normalized_audio_interval,
                segment.normalized_audio_interval,
            )
        )
        aligned_words = tuple(
            word.word_id
            for word in words
            if _overlaps(
                item.normalized_audio_interval,
                word.normalized_audio_interval,
            )
        )
        turn_rows.append(
            {
                "provider": item,
                "observation_ids": observation_ids,
                "linked": linked,
                "transcript_segment_ids": aligned_segments,
                "transcript_word_ids": aligned_words,
                "turn_id": typed_id(
                    "spkturn", response.response_id, item.provider_turn_id
                ),
                "start_boundary_id": typed_id(
                    "spkboundary",
                    response.response_id,
                    item.provider_turn_id,
                    "start",
                ),
                "end_boundary_id": typed_id(
                    "spkboundary",
                    response.response_id,
                    item.provider_turn_id,
                    "end",
                ),
            }
        )

    overlap_ranges = tuple(
        item.normalized_audio_interval for item in response.overlaps
    )
    boundary_rows = []
    for index, row in enumerate(turn_rows):
        item = row["provider"]
        for edge, microseconds, boundary_id in (
            (
                "start",
                item.normalized_audio_interval.start_microseconds,
                row["start_boundary_id"],
            ),
            ("end", _end(item.normalized_audio_interval), row["end_boundary_id"]),
        ):
            artifacts = tuple(
                [
                    segment.segment_id
                    for segment in segments
                    if _contains(segment.normalized_audio_interval, microseconds)
                ]
                + [
                    word.word_id
                    for word in words
                    if _contains(word.normalized_audio_interval, microseconds)
                ]
            )
            overlap_affected = item.overlap or any(
                interval.start_microseconds <= microseconds <= _end(interval)
                for interval in overlap_ranges
            )
            confidence = item.boundary_confidence.value
            review = (
                confidence is None
                or confidence
                < request.policy.boundary_review_confidence_threshold
                or bool(artifacts)
                or overlap_affected
            )
            preceding = (
                row["observation_ids"][-1]
                if edge == "end"
                else (
                    turn_rows[index - 1]["observation_ids"][-1]
                    if index
                    else None
                )
            )
            following = (
                row["observation_ids"][0]
                if edge == "start"
                else (
                    turn_rows[index + 1]["observation_ids"][0]
                    if index + 1 < len(turn_rows)
                    else None
                )
            )
            boundary_rows.append(
                {
                    "boundary_id": boundary_id,
                    "microseconds": microseconds,
                    "preceding_observation_id": preceding,
                    "following_observation_id": following,
                    "change_confidence": item.boundary_confidence,
                    "inside_transcript_artifact_ids": artifacts,
                    "overlap_affected": overlap_affected,
                    "review_required": review,
                    "provider_basis": f"{item.provider_turn_id}:{edge}",
                }
            )

    for row in boundary_rows:
        competing = tuple(
            candidate["boundary_id"]
            for candidate in boundary_rows
            if candidate["boundary_id"] != row["boundary_id"]
            and abs(candidate["microseconds"] - row["microseconds"])
            <= request.policy.boundary_competition_window_microseconds
            and candidate["microseconds"] != row["microseconds"]
        )
        row["competing_boundary_ids"] = competing
        if competing:
            row["review_required"] = True

    boundaries = tuple(
        SpeakerChangeBoundary(
            boundary_id=row["boundary_id"],
            corpus_id=request.corpus_id,
            normalized_audio_microseconds=row["microseconds"],
            source_microseconds=(
                row["microseconds"]
                + request.source_mapping_offset_microseconds
            ),
            uncertainty_microseconds=(
                request.policy.boundary_uncertainty_microseconds
            ),
            preceding_observation_id=row["preceding_observation_id"],
            following_observation_id=row["following_observation_id"],
            change_confidence=row["change_confidence"],
            competing_boundary_ids=row["competing_boundary_ids"],
            inside_transcript_artifact_ids=(
                row["inside_transcript_artifact_ids"]
            ),
            overlap_affected=row["overlap_affected"],
            review_required=row["review_required"],
            provider_basis=row["provider_basis"],
        )
        for row in boundary_rows
    )

    turns = []
    for row in turn_rows:
        item = row["provider"]
        payload = {
            "turn_id": row["turn_id"],
            "corpus_id": request.corpus_id,
            "source_interval": item.source_interval,
            "normalized_audio_interval": item.normalized_audio_interval,
            "observation_ids": row["observation_ids"],
            "turn_kind": item.turn_kind,
            "start_boundary_id": row["start_boundary_id"],
            "end_boundary_id": row["end_boundary_id"],
            "boundary_confidence": item.boundary_confidence,
            "assignment_confidence": item.assignment_confidence,
            "transcript_segment_ids": row["transcript_segment_ids"],
            "transcript_word_ids": row["transcript_word_ids"],
            "processing_chunk_ids": tuple(
                dict.fromkeys(
                    observation.processing_chunk_id
                    for observation in row["linked"]
                )
            ),
            "provider": response.provider,
            "validation_findings": item.findings,
        }
        turns.append(_seal(SpeakerTurn, payload))

    overlaps = []
    for item in response.overlaps:
        observation_ids = tuple(
            observation.observation_id
            for observation in observations
            if _overlaps(
                item.normalized_audio_interval,
                observation.normalized_audio_interval,
            )
        )
        limitations = tuple(
            dict.fromkeys(
                (
                    *item.findings,
                    "No speaker clusters were available for attribution.",
                )
            )
        )
        payload = {
            "overlap_id": typed_id(
                "spkoverlap",
                response.response_id,
                item.provider_overlap_id,
            ),
            "corpus_id": request.corpus_id,
            "source_interval": item.source_interval,
            "normalized_audio_interval": item.normalized_audio_interval,
            "classification": item.classification,
            "observation_ids": observation_ids,
            "candidate_cluster_ids": (),
            "estimated_active_speaker_count": (
                item.estimated_active_speaker_count
            ),
            "partially_attributed": True,
            "overlap_confidence": item.overlap_confidence,
            "speaker_count_confidence": item.speaker_count_confidence,
            "limitations": limitations,
        }
        overlaps.append(_seal(OverlapInterval, payload))

    run_id = typed_id("diarun", request.request_id, response.response_id)
    payload = {
        "run_id": run_id,
        "request_id": request.request_id,
        "response_id": response.response_id,
        "corpus_id": request.corpus_id,
        "source_id": request.source_id,
        "provider": response.provider,
        "observations": tuple(observations),
        "boundaries": boundaries,
        "turns": tuple(turns),
        "overlaps": tuple(overlaps),
        "created_at": created_at,
        "complete": response.complete,
    }
    return _seal(DiarizationRun, payload)


def validate_diarization_run(run: DiarizationRun) -> None:
    if canonical_hash(_integrity_payload(run)) != run.integrity_sha256:
        raise DiarizationNormalizationError(
            "canonical diarization run integrity is invalid"
        )
    observation_ids = {item.observation_id for item in run.observations}
    boundary_ids = {item.boundary_id for item in run.boundaries}
    if any(not item.canonical_owner for item in run.observations):
        raise DiarizationNormalizationError(
            "canonical run retained a non-owner chunk observation"
        )
    for observation in run.observations:
        if canonical_hash(_integrity_payload(observation)) != (
            observation.integrity_sha256
        ):
            raise DiarizationNormalizationError(
                "canonical speaker observation integrity is invalid"
            )
        if (
            observation.corpus_id != run.corpus_id
            or observation.source_id != run.source_id
        ):
            raise DiarizationNormalizationError(
                "canonical speaker observation lineage is invalid"
            )
    boundary_map = {item.boundary_id: item for item in run.boundaries}
    if len(boundary_map) != len(run.boundaries):
        raise DiarizationNormalizationError("speaker boundary identities repeat")
    for boundary in run.boundaries:
        if not set(boundary.competing_boundary_ids).issubset(boundary_ids):
            raise DiarizationNormalizationError(
                "speaker boundary references unknown competing proposal"
            )
        if any(
            boundary.boundary_id
            not in boundary_map[item].competing_boundary_ids
            for item in boundary.competing_boundary_ids
        ):
            raise DiarizationNormalizationError(
                "competing speaker boundaries must be symmetric"
            )
        if any(
            value is not None and value not in observation_ids
            for value in (
                boundary.preceding_observation_id,
                boundary.following_observation_id,
            )
        ):
            raise DiarizationNormalizationError(
                "speaker boundary references unknown observation"
            )
    for turn in run.turns:
        if canonical_hash(_integrity_payload(turn)) != turn.integrity_sha256:
            raise DiarizationNormalizationError(
                "canonical speaker turn integrity is invalid"
            )
        if not set(turn.observation_ids).issubset(observation_ids):
            raise DiarizationNormalizationError(
                "canonical speaker turn references unknown observations"
            )
        turn_start = turn.normalized_audio_interval.start_microseconds
        turn_end = _end(turn.normalized_audio_interval)
        if any(
            observation.normalized_audio_interval.start_microseconds < turn_start
            or _end(observation.normalized_audio_interval) > turn_end
            for observation in run.observations
            if observation.observation_id in turn.observation_ids
        ):
            raise DiarizationNormalizationError(
                "canonical speaker turn does not contain its observations"
            )
        if (
            turn.start_boundary_id not in boundary_ids
            or turn.end_boundary_id not in boundary_ids
        ):
            raise DiarizationNormalizationError(
                "canonical speaker turn references unknown boundaries"
            )
        if turn.provisional_cluster_id is not None:
            raise DiarizationNormalizationError(
                "initial diarization run must not force speaker clustering"
            )
    for overlap in run.overlaps:
        if canonical_hash(_integrity_payload(overlap)) != (
            overlap.integrity_sha256
        ):
            raise DiarizationNormalizationError(
                "canonical overlap interval integrity is invalid"
            )
        if not set(overlap.observation_ids).issubset(observation_ids):
            raise DiarizationNormalizationError(
                "canonical overlap references unknown observations"
            )
        if not overlap.observation_ids:
            raise DiarizationNormalizationError(
                "canonical overlap has no supporting observations"
            )
        if overlap.corpus_id != run.corpus_id or any(
            not _overlaps(
                overlap.normalized_audio_interval,
                observation.normalized_audio_interval,
            )
            for observation in run.observations
            if observation.observation_id in overlap.observation_ids
        ):
            raise DiarizationNormalizationError(
                "canonical overlap temporal lineage is invalid"
            )
