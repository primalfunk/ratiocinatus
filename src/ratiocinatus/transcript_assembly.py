"""Deterministic promotion of transcript observations into canonical evidence."""

from __future__ import annotations

import os
import unicodedata
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from .corpus import load_corpus, validate_corpus
from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase2_contracts import (
    ConfidenceMeasure,
    ConfidenceOrigin,
    ProviderTranscriptCandidate,
    ProviderTranscriptObservation,
    ProviderWordObservation,
    TimestampOrigin,
    TranscriptionProviderResponse,
    TranscriptionReport,
    TranscriptionRequest,
)
from .transcript_contracts import (
    LowConfidenceClassification,
    LowConfidenceRegion,
    LowConfidenceSummary,
    ReviewSeverity,
    TranscriptArtifactDigest,
    TranscriptAssembly,
    TranscriptAssemblyPolicy,
    TranscriptAssemblyReport,
    TranscriptAssemblyStatus,
    TranscriptSegment,
    TranscriptVersion,
    TranscriptWord,
)
from .transcription import (
    TranscriptionIntegrityError,
    validate_transcription_response,
)


class TranscriptAssemblyIntegrityError(RuntimeError):
    pass


def _atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.partial-{uuid.uuid4().hex}")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _seal(model: Any) -> Any:
    payload = model.model_dump(mode="json")
    payload.pop("integrity_sha256")
    return model.model_copy(update={"integrity_sha256": canonical_hash(payload)})


def _verify_seal(model: Any, label: str) -> None:
    payload = model.model_dump(mode="json")
    actual = payload.pop("integrity_sha256")
    if canonical_hash(payload) != actual:
        raise TranscriptAssemblyIntegrityError(
            f"{label} integrity hash does not match its content"
        )


def _classification_for_measure(
    measure: ConfidenceMeasure,
    *,
    threshold: float,
    low: LowConfidenceClassification,
    unavailable: LowConfidenceClassification,
) -> LowConfidenceClassification | None:
    if measure.origin == ConfidenceOrigin.UNAVAILABLE:
        return unavailable
    if measure.value is not None and measure.value < threshold:
        return low
    return None


def _region(
    *,
    corpus_id: str,
    observation: ProviderTranscriptObservation,
    classification: LowConfidenceClassification,
    evidence_references: tuple[str, ...],
    policy_basis: str,
    explanation: str,
    created_at,
    segment_id: str | None = None,
    word_id: str | None = None,
    word: ProviderWordObservation | None = None,
    blocks: bool = False,
    review: bool = True,
) -> LowConfidenceRegion:
    source_interval = (
        word.source_interval
        if word is not None and word.source_interval is not None
        else observation.source_interval
    )
    normalized_interval = (
        word.normalized_audio_interval
        if word is not None and word.normalized_audio_interval is not None
        else observation.normalized_audio_interval
    )
    region_id = typed_id(
        "lowconf",
        corpus_id,
        observation.observation_id,
        word_id,
        classification.value,
        policy_basis,
    )
    severity = (
        ReviewSeverity.BLOCKING
        if blocks
        else (ReviewSeverity.WARNING if review else ReviewSeverity.INFORMATION)
    )
    value = LowConfidenceRegion(
        region_id=region_id,
        corpus_id=corpus_id,
        segment_id=segment_id,
        word_id=word_id,
        source_interval=source_interval,
        normalized_audio_interval=normalized_interval,
        classification=classification,
        severity=severity,
        evidence_references=evidence_references,
        policy_basis=policy_basis,
        review_recommended=review,
        blocks_downstream_use=blocks,
        explanation=explanation,
        created_at=created_at,
        integrity_sha256="0" * 64,
    )
    return _seal(value)


def _word(
    request: TranscriptionRequest,
    observation: ProviderTranscriptObservation,
    candidate: ProviderTranscriptCandidate,
    provider_word: ProviderWordObservation,
    segment_id: str,
    created_at,
) -> TranscriptWord | None:
    if (
        provider_word.timestamp_origin == TimestampOrigin.UNAVAILABLE
        or provider_word.source_interval is None
        or provider_word.normalized_audio_interval is None
    ):
        return None
    normalized = _normalize(provider_word.surface_text)
    if not normalized:
        return None
    word_id = typed_id(
        "txword",
        segment_id,
        provider_word.provider_word_id,
        provider_word.normalized_audio_interval.model_dump(mode="json"),
        normalized,
    )
    value = TranscriptWord(
        word_id=word_id,
        segment_id=segment_id,
        corpus_id=request.corpus_id,
        source_interval=provider_word.source_interval,
        normalized_audio_interval=provider_word.normalized_audio_interval,
        surface_text=provider_word.surface_text,
        normalized_form=normalized,
        sequence_position=provider_word.sequence_position,
        recognition_confidence=provider_word.recognition_confidence,
        timing_confidence=provider_word.timing_confidence,
        timestamp_origin=provider_word.timestamp_origin,
        boundary_uncertainty_microseconds=(
            provider_word.boundary_uncertainty_microseconds
        ),
        provider_token_reference=provider_word.provider_token_reference,
        provider_word_id=provider_word.provider_word_id,
        provider_observation_id=observation.observation_id,
        provider_candidate_id=candidate.provider_candidate_id,
        created_at=created_at,
        integrity_sha256="0" * 64,
    )
    return _seal(value)


def _segment_classifications(
    observation: ProviderTranscriptObservation,
    candidate: ProviderTranscriptCandidate,
    policy: TranscriptAssemblyPolicy,
) -> tuple[LowConfidenceClassification, ...]:
    values: list[LowConfidenceClassification] = []
    text = _classification_for_measure(
        candidate.text_confidence,
        threshold=policy.minimum_text_confidence,
        low=LowConfidenceClassification.LOW_TRANSCRIPTION_CONFIDENCE,
        unavailable=(
            LowConfidenceClassification.UNAVAILABLE_TRANSCRIPTION_CONFIDENCE
        ),
    )
    if text is not None:
        values.append(text)
    timing = _classification_for_measure(
        observation.timing_confidence,
        threshold=policy.minimum_timing_confidence,
        low=LowConfidenceClassification.LOW_TEMPORAL_ALIGNMENT_CONFIDENCE,
        unavailable=(
            LowConfidenceClassification.UNAVAILABLE_TEMPORAL_ALIGNMENT_CONFIDENCE
        ),
    )
    if timing is not None:
        values.append(timing)
    boundary = _classification_for_measure(
        observation.boundary_confidence,
        threshold=policy.minimum_boundary_confidence,
        low=LowConfidenceClassification.UNCERTAIN_SEGMENT_BOUNDARY,
        unavailable=LowConfidenceClassification.UNCERTAIN_SEGMENT_BOUNDARY,
    )
    if boundary is not None:
        values.append(boundary)
    if len(observation.candidates) > 1:
        values.append(LowConfidenceClassification.CANDIDATE_DISAGREEMENT)
    return tuple(dict.fromkeys(values))


def _build_assembly(
    request: TranscriptionRequest,
    response: TranscriptionProviderResponse,
    *,
    audio_stream_id: str,
    audio_stream_index: int,
    policy: TranscriptAssemblyPolicy,
) -> TranscriptAssembly:
    created_at = response.completed_at
    policy_hash = canonical_hash(policy)
    segments: list[TranscriptSegment] = []
    words: list[TranscriptWord] = []
    regions: list[LowConfidenceRegion] = []
    findings: list[str] = []
    speech_evidence = {
        item.interval_id: item for item in request.speech_intervals
    }

    for observation in response.observations:
        selected = next(
            (
                item
                for item in observation.candidates
                if item.provider_candidate_id
                == observation.selected_candidate_id
                and item.selected
            ),
            None,
        )
        normalized_text = (
            _normalize(selected.proposed_text) if selected is not None else ""
        )
        if selected is None or not normalized_text:
            blocks = policy.block_unresolved_observations
            regions.append(
                _region(
                    corpus_id=request.corpus_id,
                    observation=observation,
                    classification=LowConfidenceClassification.MISSING_OUTPUT,
                    evidence_references=(observation.observation_id,),
                    policy_basis=(
                        "block_unresolved_observations="
                        f"{str(blocks).lower()}"
                    ),
                    explanation=(
                        "Provider observation has no selected non-empty lexical "
                        "candidate; no canonical segment was invented."
                    ),
                    created_at=created_at,
                    blocks=blocks,
                    review=True,
                )
            )
            findings.append(
                f"{observation.observation_id} has no promotable candidate"
            )
            continue

        classification_values = list(
            _segment_classifications(observation, selected, policy)
        )
        for evidence_id in observation.speech_interval_ids:
            speech = speech_evidence[evidence_id].speech_presence_confidence
            if (
                speech.origin != ConfidenceOrigin.UNAVAILABLE
                and speech.value is not None
                and speech.value
                < policy.minimum_speech_presence_confidence
            ):
                classification_values.append(
                    LowConfidenceClassification.LOW_SPEECH_PROBABILITY
                )
        classifications = tuple(dict.fromkeys(classification_values))
        segment_id = typed_id(
            "txsegment",
            request.corpus_id,
            request.source_id,
            response.response_id,
            observation.observation_id,
            selected.provider_candidate_id,
            policy_hash,
        )
        segment = TranscriptSegment(
            segment_id=segment_id,
            corpus_id=request.corpus_id,
            source_id=request.source_id,
            selected_audio_stream_id=audio_stream_id,
            selected_audio_stream_index=audio_stream_index,
            source_interval=observation.source_interval,
            normalized_audio_interval=observation.normalized_audio_interval,
            processing_chunk_ids=observation.processing_chunk_ids,
            proposed_text=selected.proposed_text,
            normalized_text=normalized_text,
            language_claim=selected.language,
            speech_activity_evidence_ids=observation.speech_interval_ids,
            provider=response.provider,
            transcription_response_id=response.response_id,
            provider_observation_id=observation.observation_id,
            selected_candidate_id=selected.provider_candidate_id,
            promotion_basis=(
                "validated selected provider candidate promoted by "
                f"transcript assembly policy {policy.policy_version}; "
                "selection does not establish correctness"
            ),
            text_confidence=selected.text_confidence,
            timing_confidence=observation.timing_confidence,
            boundary_confidence=observation.boundary_confidence,
            alternative_candidate_ids=tuple(
                item.provider_candidate_id
                for item in observation.candidates
                if item.provider_candidate_id != selected.provider_candidate_id
            ),
            low_confidence_classifications=classifications,
            created_at=created_at,
            integrity_sha256="0" * 64,
        )
        segment = _seal(segment)
        segments.append(segment)

        for classification in classifications:
            if classification == LowConfidenceClassification.LOW_SPEECH_PROBABILITY:
                basis = (
                    "speech presence confidence < "
                    f"{policy.minimum_speech_presence_confidence}"
                )
                blocks = False
                review = True
                explanation = "Speech-presence confidence is below policy."
            elif classification == (
                LowConfidenceClassification.LOW_TRANSCRIPTION_CONFIDENCE
            ):
                basis = (
                    "text_confidence < "
                    f"{policy.minimum_text_confidence}"
                )
                blocks = policy.block_low_text_confidence
                review = True
                explanation = "Selected candidate text confidence is below policy."
            elif classification == (
                LowConfidenceClassification.UNAVAILABLE_TRANSCRIPTION_CONFIDENCE
            ):
                basis = "text confidence unavailable"
                blocks = policy.block_unavailable_text_confidence
                review = policy.review_unavailable_text_confidence
                explanation = "Provider supplied no meaningful text confidence."
            elif classification == (
                LowConfidenceClassification.LOW_TEMPORAL_ALIGNMENT_CONFIDENCE
            ):
                basis = (
                    "timing_confidence < "
                    f"{policy.minimum_timing_confidence}"
                )
                blocks = False
                review = True
                explanation = "Segment timing confidence is below policy."
            elif classification == (
                LowConfidenceClassification.UNAVAILABLE_TEMPORAL_ALIGNMENT_CONFIDENCE
            ):
                basis = "timing confidence unavailable"
                blocks = False
                review = policy.review_unavailable_timing_confidence
                explanation = "Provider supplied no segment timing confidence."
            elif classification == (
                LowConfidenceClassification.UNCERTAIN_SEGMENT_BOUNDARY
            ):
                basis = (
                    "boundary confidence unavailable or below "
                    f"{policy.minimum_boundary_confidence}"
                )
                blocks = False
                review = policy.review_uncertain_boundaries
                explanation = "Segment boundary confidence is weak or unavailable."
            else:
                review = True
                basis = "multiple provider candidates"
                blocks = False
                explanation = "Provider observation contains alternative candidates."
            regions.append(
                _region(
                    corpus_id=request.corpus_id,
                    observation=observation,
                    classification=classification,
                    evidence_references=(
                        observation.observation_id,
                        selected.provider_candidate_id,
                        *observation.speech_interval_ids,
                    ),
                    policy_basis=basis,
                    explanation=explanation,
                    created_at=created_at,
                    segment_id=segment_id,
                    blocks=blocks,
                    review=review,
                )
            )

        for provider_word in selected.words:
            word = _word(
                request,
                observation,
                selected,
                provider_word,
                segment_id,
                created_at,
            )
            if word is None:
                regions.append(
                    _region(
                        corpus_id=request.corpus_id,
                        observation=observation,
                        classification=(
                            LowConfidenceClassification.INCOMPLETE_BOUNDARY_WORD
                        ),
                        evidence_references=(
                            observation.observation_id,
                            provider_word.provider_word_id,
                        ),
                        policy_basis="canonical words require mapped timestamps",
                        explanation=(
                            "Provider word lacks usable mapped timestamps and "
                            "was not promoted."
                        ),
                        created_at=created_at,
                        segment_id=segment_id,
                    )
                )
                continue
            words.append(word)
            recognition = _classification_for_measure(
                word.recognition_confidence,
                threshold=policy.minimum_word_confidence,
                low=LowConfidenceClassification.LOW_TRANSCRIPTION_CONFIDENCE,
                unavailable=(
                    LowConfidenceClassification.UNAVAILABLE_TRANSCRIPTION_CONFIDENCE
                ),
            )
            timing = _classification_for_measure(
                word.timing_confidence,
                threshold=policy.minimum_timing_confidence,
                low=(
                    LowConfidenceClassification.LOW_TEMPORAL_ALIGNMENT_CONFIDENCE
                ),
                unavailable=(
                    LowConfidenceClassification.UNAVAILABLE_TEMPORAL_ALIGNMENT_CONFIDENCE
                ),
            )
            for classification, basis, explanation in (
                (
                    recognition,
                    "word recognition confidence unavailable or below "
                    f"{policy.minimum_word_confidence}",
                    "Word recognition confidence is weak or unavailable.",
                ),
                (
                    timing,
                    "word timing confidence unavailable or below "
                    f"{policy.minimum_timing_confidence}",
                    "Word timing confidence is weak or unavailable.",
                ),
            ):
                if classification is not None:
                    review = True
                    if classification == (
                        LowConfidenceClassification.UNAVAILABLE_TRANSCRIPTION_CONFIDENCE
                    ):
                        review = policy.review_unavailable_text_confidence
                    elif classification == (
                        LowConfidenceClassification.UNAVAILABLE_TEMPORAL_ALIGNMENT_CONFIDENCE
                    ):
                        review = policy.review_unavailable_timing_confidence
                    regions.append(
                        _region(
                            corpus_id=request.corpus_id,
                            observation=observation,
                            classification=classification,
                            evidence_references=(
                                observation.observation_id,
                                provider_word.provider_word_id,
                            ),
                            policy_basis=basis,
                            explanation=explanation,
                            created_at=created_at,
                            segment_id=segment_id,
                            word_id=word.word_id,
                            word=provider_word,
                            review=review,
                        )
                    )

    if not response.complete:
        findings.append(
            "provider response failed; canonical transcript is incomplete"
        )
        covered = {
            evidence_id
            for observation in response.observations
            for evidence_id in observation.speech_interval_ids
        }
        for interval in request.speech_intervals:
            if interval.interval_id in covered:
                continue
            synthetic = ProviderTranscriptObservation(
                observation_id=typed_id(
                    "txobs", response.response_id, interval.interval_id
                ),
                speech_interval_ids=(interval.interval_id,),
                source_interval=interval.source_interval,
                normalized_audio_interval=interval.normalized_audio_interval,
                processing_chunk_ids=(interval.processing_chunk_id,),
                candidates=(),
                selected_candidate_id=None,
                timing_confidence=ConfidenceMeasure(
                    origin=ConfidenceOrigin.UNAVAILABLE,
                    basis="provider response failed",
                ),
                boundary_confidence=ConfidenceMeasure(
                    origin=ConfidenceOrigin.UNAVAILABLE,
                    basis="provider response failed",
                ),
                findings=("provider response failed",),
            )
            regions.append(
                _region(
                    corpus_id=request.corpus_id,
                    observation=synthetic,
                    classification=LowConfidenceClassification.PROVIDER_ERROR,
                    evidence_references=(
                        response.response_id,
                        interval.interval_id,
                    ),
                    policy_basis="failed provider response blocks assembly",
                    explanation=response.failure_message
                    or "Transcription provider failed.",
                    created_at=created_at,
                    blocks=True,
                )
            )

    segment_digests = tuple(
        TranscriptArtifactDigest(
            artifact_id=item.segment_id,
            content_sha256=canonical_hash(item),
        )
        for item in segments
    )
    word_digests = tuple(
        TranscriptArtifactDigest(
            artifact_id=item.word_id,
            content_sha256=canonical_hash(item),
        )
        for item in words
    )
    region_digests = tuple(
        TranscriptArtifactDigest(
            artifact_id=item.region_id,
            content_sha256=canonical_hash(item),
        )
        for item in regions
    )
    version_id = typed_id(
        "txversion",
        request.corpus_id,
        response.response_id,
        policy_hash,
        tuple(item.model_dump(mode="json") for item in segment_digests),
        tuple(item.model_dump(mode="json") for item in word_digests),
        tuple(item.model_dump(mode="json") for item in region_digests),
    )
    version = _seal(
        TranscriptVersion(
            version_id=version_id,
            corpus_id=request.corpus_id,
            transcription_response_id=response.response_id,
            assembly_policy=policy,
            segments=segment_digests,
            words=word_digests,
            low_confidence_regions=region_digests,
            created_at=created_at,
            integrity_sha256="0" * 64,
        )
    )
    blocking = any(item.blocks_downstream_use for item in regions)
    status = (
        TranscriptAssemblyStatus.BLOCKED
        if blocking
        else (
            TranscriptAssemblyStatus.REVIEW_REQUIRED
            if any(item.review_recommended for item in regions) or findings
            else TranscriptAssemblyStatus.COMPLETE
        )
    )
    assembly_id = typed_id(
        "txassembly", request.corpus_id, response.response_id, policy_hash
    )
    return _seal(
        TranscriptAssembly(
            assembly_id=assembly_id,
            source_id=request.source_id,
            normalized_audio_sha256=request.normalized_audio_sha256,
            normalized_audio_duration_microseconds=(
                request.normalized_audio_duration_microseconds
            ),
            source_mapping_offset_microseconds=(
                request.source_mapping_offset_microseconds
            ),
            version=version,
            segments=tuple(segments),
            words=tuple(words),
            low_confidence_regions=tuple(regions),
            validation_findings=tuple(findings),
            status=status,
            assembled_at=created_at,
            integrity_sha256="0" * 64,
        )
    )


def validate_transcript_assembly(
    assembly: TranscriptAssembly,
    *,
    request: TranscriptionRequest | None = None,
    response: TranscriptionProviderResponse | None = None,
) -> None:
    _verify_seal(assembly, "transcript assembly")
    _verify_seal(assembly.version, "transcript version")
    for item in assembly.segments:
        _verify_seal(item, item.segment_id)
    for item in assembly.words:
        _verify_seal(item, item.word_id)
    for item in assembly.low_confidence_regions:
        _verify_seal(item, item.region_id)
    if request is not None and assembly.source_id != request.source_id:
        raise TranscriptAssemblyIntegrityError(
            "transcript assembly belongs to another source"
        )
    if request is not None and (
        assembly.normalized_audio_sha256
        != request.normalized_audio_sha256
    ):
        raise TranscriptAssemblyIntegrityError(
            "transcript assembly normalized audio hash differs"
        )
    if request is not None and assembly.version.corpus_id != request.corpus_id:
        raise TranscriptAssemblyIntegrityError(
            "transcript assembly belongs to another corpus"
        )
    if request is not None and (
        assembly.normalized_audio_duration_microseconds
        != request.normalized_audio_duration_microseconds
        or assembly.source_mapping_offset_microseconds
        != request.source_mapping_offset_microseconds
    ):
        raise TranscriptAssemblyIntegrityError(
            "transcript assembly addressing differs from its request"
        )
    if response is not None and (
        assembly.version.transcription_response_id != response.response_id
    ):
        raise TranscriptAssemblyIntegrityError(
            "transcript assembly belongs to another provider response"
        )

    segments = {item.segment_id: item for item in assembly.segments}
    if len(segments) != len(assembly.segments):
        raise TranscriptAssemblyIntegrityError("duplicate transcript segment")
    words = {item.word_id: item for item in assembly.words}
    if len(words) != len(assembly.words):
        raise TranscriptAssemblyIntegrityError("duplicate transcript word")
    regions = {item.region_id: item for item in assembly.low_confidence_regions}
    if len(regions) != len(assembly.low_confidence_regions):
        raise TranscriptAssemblyIntegrityError("duplicate low-confidence region")

    previous_end = 0
    for segment in assembly.segments:
        start = segment.normalized_audio_interval.start_microseconds
        end = start + segment.normalized_audio_interval.duration_microseconds
        if (
            segment.source_interval.start_microseconds
            != start + assembly.source_mapping_offset_microseconds
            or end > assembly.normalized_audio_duration_microseconds
        ):
            raise TranscriptAssemblyIntegrityError(
                "canonical transcript segment mapping exceeds assembly bounds"
            )
        if start < previous_end:
            raise TranscriptAssemblyIntegrityError(
                "canonical transcript segments overlap or regress"
            )
        previous_end = end
    by_segment: dict[str, list[TranscriptWord]] = {}
    for word in assembly.words:
        if word.segment_id not in segments:
            raise TranscriptAssemblyIntegrityError(
                "transcript word references unknown segment"
            )
        by_segment.setdefault(word.segment_id, []).append(word)
    for segment_id, segment_words in by_segment.items():
        segment = segments[segment_id].normalized_audio_interval
        start = segment.start_microseconds
        limit = start + segment.duration_microseconds
        previous_end = start
        previous_position = -1
        for word in segment_words:
            interval = word.normalized_audio_interval
            end = interval.start_microseconds + interval.duration_microseconds
            if (
                word.sequence_position <= previous_position
                or interval.start_microseconds < previous_end
                or end > limit
            ):
                raise TranscriptAssemblyIntegrityError(
                    "canonical word order or containment is invalid"
                )
            previous_end = end
            previous_position = word.sequence_position
    for region in assembly.low_confidence_regions:
        if region.segment_id is not None and region.segment_id not in segments:
            raise TranscriptAssemblyIntegrityError(
                "low-confidence region references unknown segment"
            )
        if region.word_id is not None and region.word_id not in words:
            raise TranscriptAssemblyIntegrityError(
                "low-confidence region references unknown word"
            )

    expected = (
        (
            TranscriptArtifactDigest(
                artifact_id=item.segment_id,
                content_sha256=canonical_hash(item),
            )
            for item in assembly.segments
        ),
        (
            TranscriptArtifactDigest(
                artifact_id=item.word_id,
                content_sha256=canonical_hash(item),
            )
            for item in assembly.words
        ),
        (
            TranscriptArtifactDigest(
                artifact_id=item.region_id,
                content_sha256=canonical_hash(item),
            )
            for item in assembly.low_confidence_regions
        ),
    )
    actual = (
        assembly.version.segments,
        assembly.version.words,
        assembly.version.low_confidence_regions,
    )
    if tuple(tuple(values) for values in expected) != actual:
        raise TranscriptAssemblyIntegrityError(
            "transcript version artifact digests do not match assembly"
        )
    blocking = any(
        item.blocks_downstream_use
        for item in assembly.low_confidence_regions
    )
    expected_status = (
        TranscriptAssemblyStatus.BLOCKED
        if blocking
        else (
            TranscriptAssemblyStatus.REVIEW_REQUIRED
            if any(
                item.review_recommended
                for item in assembly.low_confidence_regions
            ) or assembly.validation_findings
            else TranscriptAssemblyStatus.COMPLETE
        )
    )
    if assembly.status != expected_status:
        raise TranscriptAssemblyIntegrityError(
            "transcript assembly status does not match findings"
        )


def _report(assembly: TranscriptAssembly) -> TranscriptAssemblyReport:
    counts = Counter(
        item.classification for item in assembly.low_confidence_regions
    )
    summaries = tuple(
        LowConfidenceSummary(
            classification=classification,
            region_count=counts[classification],
            duration_microseconds=sum(
                item.normalized_audio_interval.duration_microseconds
                for item in assembly.low_confidence_regions
                if item.classification == classification
            ),
            blocking_region_count=sum(
                item.blocks_downstream_use
                for item in assembly.low_confidence_regions
                if item.classification == classification
            ),
        )
        for classification in sorted(counts, key=lambda item: item.value)
    )
    return TranscriptAssemblyReport(
        report_id=typed_id("txassemblyreport", assembly.assembly_id),
        assembly_id=assembly.assembly_id,
        version_id=assembly.version.version_id,
        corpus_id=assembly.version.corpus_id,
        generated_at=assembly.assembled_at,
        segment_count=len(assembly.segments),
        word_count=len(assembly.words),
        low_confidence=summaries,
        review_region_count=sum(
            item.review_recommended
            for item in assembly.low_confidence_regions
        ),
        blocking_region_count=sum(
            item.blocks_downstream_use
            for item in assembly.low_confidence_regions
        ),
        validation_findings=assembly.validation_findings,
        status=assembly.status,
    )


def report_markdown(report: TranscriptAssemblyReport) -> str:
    lines = [
        "# Phase 2 canonical transcript assembly report",
        "",
        f"Status: **{report.status.value.upper()}**",
        "",
        f"Assembly: `{report.assembly_id}`",
        "",
        f"- Canonical segments: {report.segment_count}",
        f"- Canonical timestamped words: {report.word_count}",
        f"- Review regions: {report.review_region_count}",
        f"- Blocking regions: {report.blocking_region_count}",
        "",
        "Low-confidence classifications are persisted as machine-readable "
        "artifacts; they are not inferred from this rendering.",
        "",
    ]
    for item in report.low_confidence:
        lines.append(
            f"- `{item.classification.value}`: {item.region_count} regions, "
            f"{item.duration_microseconds} microseconds, "
            f"{item.blocking_region_count} blocking"
        )
    lines.append("")
    return "\n".join(lines)


def _verify_persisted(root: Path, assembly: TranscriptAssembly) -> None:
    version = load_contract(
        (root / "version.json").read_bytes(), TranscriptVersion
    )
    if version != assembly.version:
        raise TranscriptAssemblyIntegrityError(
            "persisted transcript version differs from assembly"
        )
    for directory, identifier, items, model in (
        ("segments", "segment_id", assembly.segments, TranscriptSegment),
        ("words", "word_id", assembly.words, TranscriptWord),
        (
            "low-confidence",
            "region_id",
            assembly.low_confidence_regions,
            LowConfidenceRegion,
        ),
    ):
        for item in items:
            artifact_id = getattr(item, identifier)
            try:
                loaded = load_contract(
                    (root / directory / f"{artifact_id}.json").read_bytes(),
                    model,
                )
            except Exception as exc:
                raise TranscriptAssemblyIntegrityError(
                    f"persisted artifact {artifact_id} is missing or malformed"
                ) from exc
            if loaded != item:
                raise TranscriptAssemblyIntegrityError(
                    f"persisted artifact {artifact_id} differs from assembly"
                )


def assemble_transcript(
    corpus_root: Path,
    transcription_run_root: Path,
    destination: Path,
    *,
    policy: TranscriptAssemblyPolicy | None = None,
) -> tuple[TranscriptAssembly, TranscriptAssemblyReport, Path, bool]:
    corpus_root = corpus_root.expanduser().resolve(strict=True)
    transcription_run_root = transcription_run_root.expanduser().resolve(
        strict=True
    )
    destination = destination.expanduser().resolve()
    if destination == corpus_root or corpus_root in destination.parents:
        raise ValueError("Phase 2 output must not modify the Phase 1 corpus")
    integrity = validate_corpus(corpus_root)
    if not integrity.valid:
        raise TranscriptAssemblyIntegrityError(
            "Phase 1 corpus is invalid: " + "; ".join(integrity.findings)
        )
    corpus = load_corpus(corpus_root)
    request = load_contract(
        (transcription_run_root / "request.json").read_bytes(),
        TranscriptionRequest,
    )
    response = load_contract(
        (transcription_run_root / "response.json").read_bytes(),
        TranscriptionProviderResponse,
    )
    transcription_report = load_contract(
        (transcription_run_root / "report.json").read_bytes(),
        TranscriptionReport,
    )
    try:
        validate_transcription_response(
            response, request, transcription_run_root
        )
    except TranscriptionIntegrityError as exc:
        raise TranscriptAssemblyIntegrityError(str(exc)) from exc
    if (
        request.corpus_id != corpus["corpus"].corpus_id
        or request.source_id != corpus["corpus"].source_id
    ):
        raise TranscriptAssemblyIntegrityError(
            "transcription request belongs to another Phase 1 corpus"
        )
    if (
        transcription_report.response_id != response.response_id
        or transcription_report.request_id != request.request_id
        or transcription_report.corpus_id != request.corpus_id
    ):
        raise TranscriptAssemblyIntegrityError(
            "transcription report lineage is incompatible"
        )
    selection = corpus["selection"].audio
    timeline = corpus["timeline"]
    if (
        selection.selected_stream_id is None
        or selection.selected_stream_index is None
        or selection.selected_stream_id != timeline.audio_stream_id
    ):
        raise TranscriptAssemblyIntegrityError(
            "Phase 1 selected audio-stream lineage is unavailable or inconsistent"
        )
    policy = policy or TranscriptAssemblyPolicy()
    assembly = _build_assembly(
        request,
        response,
        audio_stream_id=selection.selected_stream_id,
        audio_stream_index=selection.selected_stream_index,
        policy=policy,
    )
    validate_transcript_assembly(
        assembly, request=request, response=response
    )
    report = _report(assembly)
    root = destination / "transcript-assemblies" / assembly.assembly_id
    assembly_path = root / "assembly.json"
    report_path = root / "report.json"
    if assembly_path.exists() or report_path.exists():
        if not assembly_path.exists() or not report_path.exists():
            raise TranscriptAssemblyIntegrityError(
                "cached transcript assembly is incomplete"
            )
        stored = load_contract(
            assembly_path.read_bytes(), TranscriptAssembly
        )
        stored_report = load_contract(
            report_path.read_bytes(), TranscriptAssemblyReport
        )
        if stored != assembly or stored_report != report:
            raise TranscriptAssemblyIntegrityError(
                "cached transcript assembly is incompatible"
            )
        validate_transcript_assembly(
            stored, request=request, response=response
        )
        _verify_persisted(root, stored)
        return stored, stored_report, root, True

    _atomic(assembly_path, canonical_bytes(assembly))
    _atomic(root / "version.json", canonical_bytes(assembly.version))
    for item in assembly.segments:
        _atomic(
            root / "segments" / f"{item.segment_id}.json",
            canonical_bytes(item),
        )
    for item in assembly.words:
        _atomic(
            root / "words" / f"{item.word_id}.json",
            canonical_bytes(item),
        )
    for item in assembly.low_confidence_regions:
        _atomic(
            root / "low-confidence" / f"{item.region_id}.json",
            canonical_bytes(item),
        )
    _atomic(report_path, canonical_bytes(report))
    _atomic(
        root / "report.md",
        report_markdown(report).encode("utf-8"),
    )
    return assembly, report, root, False
