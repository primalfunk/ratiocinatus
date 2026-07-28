"""Qualify Phase 2 ownership and assembly on a Phase 1 corpus over two hours."""

from __future__ import annotations

import argparse
import json
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path

from ratiocinatus.addressing_contracts import MediaInterval, TimeDomain
from ratiocinatus.corpus import load_corpus, validate_corpus
from ratiocinatus.kernel import canonical_hash, typed_id
from ratiocinatus.media import sha256_file
from ratiocinatus.phase2_contracts import (
    ConfidenceMeasure,
    ConfidenceOrigin,
    ProviderTranscriptCandidate,
    ProviderTranscriptObservation,
    ProviderWordObservation,
    RawEvidenceDisposition,
    RawProviderEvidence,
    SpeechActivityClassification,
    SpeechActivityInterval,
    SpeechActivityRun,
    SpeechBoundaryEvidence,
    SpeechEvidenceCapability,
    SpeechEvidenceProviderCapabilities,
    SpeechEvidenceProviderIdentity,
    TimestampOrigin,
    TranscriptionProviderResponse,
)
from ratiocinatus.speech_activity import detect_corpus_activity
from ratiocinatus.speech_providers import (
    SpeechActivityProvider,
    TranscriptionProvider,
)
from ratiocinatus.transcript_assembly import assemble_transcript
from ratiocinatus.transcription import transcribe_corpus


def _confidence(value: float, basis: str) -> ConfidenceMeasure:
    return ConfidenceMeasure(
        value=value,
        origin=ConfidenceOrigin.DERIVED,
        basis=basis,
    )


class OwnedChunkQualificationActivityProvider(SpeechActivityProvider):
    """Synthetic control that emits exactly one owned interval per Phase 1 chunk."""

    calls = 0
    _identity = SpeechEvidenceProviderIdentity(
        provider_id="qualification.synthetic_owned_chunk_activity",
        display_name="Synthetic owned-chunk activity qualification control",
        provider_version="1.0.0",
        model_id="phase2-long-boundary-control",
        model_version="1.0.0",
        local=True,
        license_expression="Apache-2.0",
        model_redistributed=False,
    )

    @property
    def capabilities(self) -> SpeechEvidenceProviderCapabilities:
        return SpeechEvidenceProviderCapabilities(
            identity=self._identity,
            capabilities=(SpeechEvidenceCapability.SPEECH_ACTIVITY,),
            available=True,
            speech_confidence=True,
            cancellation_boundaries=("between_phase1_chunks",),
            limitations=(
                "Qualification-only synthetic control; classifications do not "
                "claim that the long fixture contains speech.",
            ),
        )

    def detect(self, request, normalized_audio: Path) -> SpeechActivityRun:
        self.calls += 1
        if request.provider != self._identity:
            raise ValueError("request belongs to another activity provider")
        if sha256_file(normalized_audio) != request.normalized_audio_sha256:
            raise ValueError("normalized audio hash does not match request")
        started = datetime.now(timezone.utc)
        boundaries: dict[int, SpeechBoundaryEvidence] = {}
        intervals = []
        basis = "qualification fixture assigns synthetic activity to owned chunks"
        for chunk in request.chunks:
            owned = chunk.ownership_interval
            start = owned.start_microseconds
            end = start + owned.duration_microseconds
            for position in (start, end):
                boundaries.setdefault(
                    position,
                    SpeechBoundaryEvidence(
                        boundary_id=typed_id(
                            "boundary", request.request_id, position
                        ),
                        normalized_audio_microseconds=position,
                        source_microseconds=(
                            position + request.source_mapping_offset_microseconds
                        ),
                        uncertainty_microseconds=0,
                        confidence=_confidence(1.0, basis),
                    ),
                )
            intervals.append(
                SpeechActivityInterval(
                    interval_id=typed_id(
                        "speech", request.request_id, chunk.chunk_id, start, end
                    ),
                    corpus_id=request.corpus_id,
                    source_interval=MediaInterval(
                        domain=TimeDomain.SOURCE_MEDIA,
                        start_microseconds=(
                            start + request.source_mapping_offset_microseconds
                        ),
                        duration_microseconds=owned.duration_microseconds,
                    ),
                    normalized_audio_interval=owned,
                    processing_chunk_id=chunk.chunk_id,
                    classification=SpeechActivityClassification.PROBABLE_SPEECH,
                    speech_presence_confidence=_confidence(1.0, basis),
                    start_boundary_id=boundaries[start].boundary_id,
                    end_boundary_id=boundaries[end].boundary_id,
                    canonical_owner=True,
                    findings=(
                        "synthetic boundary control; not observed speech evidence",
                    ),
                )
            )
        evidence_hash = canonical_hash(
            {
                "request_id": request.request_id,
                "provider": self._identity.model_dump(mode="json"),
                "intervals": [
                    item.model_dump(mode="json") for item in intervals
                ],
            }
        )
        return SpeechActivityRun(
            run_id=typed_id("sarun", request.request_id, evidence_hash),
            request=request,
            provider=self._identity,
            started_at=started,
            completed_at=datetime.now(timezone.utc),
            intervals=tuple(intervals),
            boundaries=tuple(boundaries[key] for key in sorted(boundaries)),
            raw_evidence=RawProviderEvidence(
                disposition=RawEvidenceDisposition.HASH_ONLY,
                content_sha256=evidence_hash,
                explanation=(
                    "Canonical hash of generated ownership-control intervals."
                ),
            ),
            complete=True,
        )


class BoundaryMarkerTranscriptionProvider(TranscriptionProvider):
    """Synthetic provider emitting one mapped marker in each owned chunk."""

    calls = 0
    _identity = SpeechEvidenceProviderIdentity(
        provider_id="qualification.synthetic_boundary_transcription",
        display_name="Synthetic chunk-boundary transcription control",
        provider_version="1.0.0",
        model_id="phase2-long-boundary-control",
        model_version="1.0.0",
        local=True,
        license_expression="Apache-2.0",
        model_redistributed=False,
    )

    @property
    def capabilities(self) -> SpeechEvidenceProviderCapabilities:
        return SpeechEvidenceProviderCapabilities(
            identity=self._identity,
            capabilities=(SpeechEvidenceCapability.TRANSCRIPTION,),
            available=True,
            supported_languages=("en",),
            segment_timestamps=True,
            word_timestamps=True,
            text_confidence=True,
            cancellation_boundaries=("between_speech_intervals",),
            limitations=(
                "Qualification-only synthetic boundary markers; no "
                "transcription-accuracy claim is made.",
            ),
        )

    def transcribe(
        self,
        request,
        normalized_audio: Path,
        *,
        evidence_root: Path | None = None,
    ) -> TranscriptionProviderResponse:
        self.calls += 1
        if request.provider != self._identity:
            raise ValueError("request belongs to another transcription provider")
        if sha256_file(normalized_audio) != request.normalized_audio_sha256:
            raise ValueError("normalized audio hash does not match request")
        started = datetime.now(timezone.utc)
        observations = []
        basis = "qualification-only deterministic synthetic marker"
        for ordinal, speech in enumerate(request.speech_intervals):
            owned = speech.normalized_audio_interval
            duration = min(1_000_000, owned.duration_microseconds)
            normalized = MediaInterval(
                domain=TimeDomain.NORMALIZED_CORPUS,
                start_microseconds=owned.start_microseconds,
                duration_microseconds=duration,
            )
            source = MediaInterval(
                domain=TimeDomain.SOURCE_MEDIA,
                start_microseconds=(
                    normalized.start_microseconds
                    + request.source_mapping_offset_microseconds
                ),
                duration_microseconds=duration,
            )
            text = f"boundary-marker-{ordinal:03d}"
            word = ProviderWordObservation(
                provider_word_id=f"marker-{ordinal:03d}",
                surface_text=text,
                sequence_position=0,
                source_interval=source,
                normalized_audio_interval=normalized,
                timestamp_origin=TimestampOrigin.ESTIMATED,
                recognition_confidence=_confidence(1.0, basis),
                timing_confidence=_confidence(1.0, basis),
                boundary_uncertainty_microseconds=0,
            )
            candidate = ProviderTranscriptCandidate(
                provider_candidate_id=f"candidate-{ordinal:03d}",
                proposed_text=text,
                language="en",
                rank=1,
                text_confidence=_confidence(1.0, basis),
                selected=True,
                selection_reason="single qualification marker",
                words=(word,),
            )
            observations.append(
                ProviderTranscriptObservation(
                    observation_id=typed_id(
                        "txobs", request.request_id, ordinal
                    ),
                    speech_interval_ids=(speech.interval_id,),
                    source_interval=source,
                    normalized_audio_interval=normalized,
                    processing_chunk_ids=(speech.processing_chunk_id,),
                    provider_segment_reference=f"marker-{ordinal:03d}",
                    candidates=(candidate,),
                    selected_candidate_id=candidate.provider_candidate_id,
                    timing_confidence=_confidence(1.0, basis),
                    boundary_confidence=_confidence(1.0, basis),
                    findings=(
                        "synthetic boundary marker; not lexical source evidence",
                    ),
                )
            )
        evidence_hash = canonical_hash(
            {
                "request_id": request.request_id,
                "provider": self._identity.model_dump(mode="json"),
                "observations": [
                    item.model_dump(mode="json") for item in observations
                ],
            }
        )
        return TranscriptionProviderResponse(
            response_id=typed_id(
                "txresponse", request.request_id, evidence_hash
            ),
            request_id=request.request_id,
            provider=self._identity,
            started_at=started,
            completed_at=datetime.now(timezone.utc),
            observations=tuple(observations),
            normalized_evidence_sha256=evidence_hash,
            raw_evidence=RawProviderEvidence(
                disposition=RawEvidenceDisposition.HASH_ONLY,
                content_sha256=evidence_hash,
                explanation=(
                    "Canonical hash of generated boundary-marker observations."
                ),
            ),
            complete=True,
        )


def _tree_hash(root: Path) -> str:
    records = [
        (path.relative_to(root).as_posix(), sha256_file(path))
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]
    return canonical_hash(records)


def qualify(corpus_root: Path, destination: Path) -> dict[str, object]:
    corpus_root = corpus_root.resolve(strict=True)
    destination = destination.resolve()
    integrity = validate_corpus(corpus_root)
    if not integrity.valid:
        raise RuntimeError("long-recording corpus is invalid")
    corpus_before = _tree_hash(corpus_root)
    loaded = load_corpus(corpus_root)
    activity_provider = OwnedChunkQualificationActivityProvider()
    transcription_provider = BoundaryMarkerTranscriptionProvider()
    activity_provider.calls = 0
    transcription_provider.calls = 0

    tracemalloc.start()
    started = time.perf_counter()
    activity, activity_report, activity_root, activity_reused_first = (
        detect_corpus_activity(
            corpus_root, destination, provider=activity_provider
        )
    )
    _, _, _, activity_reused_second = detect_corpus_activity(
        corpus_root, destination, provider=activity_provider
    )
    request, response, tx_report, tx_root, tx_reused_first = transcribe_corpus(
        corpus_root,
        activity_root,
        destination,
        provider=transcription_provider,
    )
    _, _, _, _, tx_reused_second = transcribe_corpus(
        corpus_root,
        activity_root,
        destination,
        provider=transcription_provider,
    )
    assembly, assembly_report, assembly_root, assembly_reused_first = (
        assemble_transcript(corpus_root, tx_root, destination)
    )
    _, _, _, assembly_reused_second = assemble_transcript(
        corpus_root, tx_root, destination
    )
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    chunks = loaded["chunks"].chunks
    transitions = [
        (
            chunks[index - 1].ownership_interval.start_microseconds
            + chunks[index - 1].ownership_interval.duration_microseconds,
            chunks[index].ownership_interval.start_microseconds,
        )
        for index in range(1, len(chunks))
    ]
    observed_chunk_ids = {
        item.processing_chunk_ids[0] for item in response.observations
    }
    corpus_after = _tree_hash(corpus_root)
    assertions = {
        "duration_exceeds_two_hours": (
            loaded["timeline"].corpus_duration_microseconds > 7_200_000_000
        ),
        "phase1_corpus_valid": integrity.valid,
        "phase1_corpus_unchanged": corpus_before == corpus_after,
        "multiple_phase1_chunks": len(chunks) > 1,
        "chunk_transitions_contiguous": all(a == b for a, b in transitions),
        "activity_coverage_complete": activity_report.coverage_complete,
        "activity_inherits_every_owned_chunk": (
            len(activity.intervals) == len(chunks)
        ),
        "overlap_output_not_duplicated": (
            activity_report.duplicate_owned_interval_count == 0
        ),
        "transcript_observation_per_owned_chunk": (
            len(response.observations) == len(chunks)
            and observed_chunk_ids == {item.chunk_id for item in chunks}
        ),
        "canonical_segment_per_owned_chunk": (
            len(assembly.segments) == len(chunks)
        ),
        "canonical_word_per_owned_chunk": len(assembly.words) == len(chunks),
        "final_assembly_valid": (
            assembly_report.status.value != "blocked"
            and not assembly_report.validation_findings
        ),
        "activity_resume_reused": (
            not activity_reused_first and activity_reused_second
        ),
        "transcription_resume_reused": (
            not tx_reused_first and tx_reused_second
        ),
        "assembly_resume_reused": (
            not assembly_reused_first and assembly_reused_second
        ),
        "providers_invoked_once": (
            activity_provider.calls == 1
            and transcription_provider.calls == 1
        ),
        "python_peak_below_256_mib": peak < 256 * 1024 * 1024,
    }
    return {
        "qualification": "phase-2-long-recording",
        "status": "passed" if all(assertions.values()) else "failed",
        "fixture_status": (
            "Synthetic ownership and boundary control; no speech or "
            "transcription-accuracy claim."
        ),
        "corpus": {
            "corpus_id": loaded["corpus"].corpus_id,
            "source_id": loaded["corpus"].source_id,
            "duration_microseconds": (
                loaded["timeline"].corpus_duration_microseconds
            ),
            "normalized_audio_sha256": loaded["audio"].integrity.derivative_sha256,
            "tree_hash_before": corpus_before,
            "tree_hash_after": corpus_after,
        },
        "chunks": {
            "count": len(chunks),
            "transition_count": len(transitions),
            "overlap_microseconds": loaded["chunks"].policy.overlap_microseconds,
            "maximum_coverage_multiplicity": (
                loaded["chunks"].maximum_coverage_multiplicity
            ),
        },
        "phase2": {
            "activity_run_id": activity.run_id,
            "transcription_request_id": request.request_id,
            "transcription_response_id": response.response_id,
            "assembly_id": assembly.assembly_id,
            "activity_interval_count": len(activity.intervals),
            "transcript_observation_count": tx_report.observation_count,
            "segment_count": assembly_report.segment_count,
            "word_count": assembly_report.word_count,
            "low_confidence_region_count": (
                assembly_report.review_region_count
            ),
            "activity_provider_calls": activity_provider.calls,
            "transcription_provider_calls": transcription_provider.calls,
            "activity_root": str(activity_root),
            "transcription_root": str(tx_root),
            "assembly_root": str(assembly_root),
        },
        "performance": {
            "processing_seconds": round(elapsed, 6),
            "python_allocator_peak_bytes": peak,
            "measurement_scope": (
                "tracemalloc Python allocator peak for Phase 2 qualification; "
                "hashing streams files in bounded blocks"
            ),
        },
        "resume_boundary": {
            "interruption_simulated_after": "speech_activity_committed",
            "activity_cache_reused": activity_reused_second,
            "transcription_cache_reused": tx_reused_second,
            "assembly_cache_reused": assembly_reused_second,
        },
        "assertions": assertions,
    }


def markdown(report: dict[str, object]) -> str:
    corpus = report["corpus"]
    chunks = report["chunks"]
    phase2 = report["phase2"]
    performance = report["performance"]
    lines = [
        "# Phase 2 long-recording qualification",
        "",
        f"Status: **{str(report['status']).upper()}**",
        "",
        str(report["fixture_status"]),
        "",
        "## Measurements",
        "",
        f"- Duration: {corpus['duration_microseconds']} microseconds",
        f"- Phase 1 chunks: {chunks['count']}",
        f"- Owned chunk transitions: {chunks['transition_count']}",
        f"- Phase 2 activity intervals: {phase2['activity_interval_count']}",
        f"- Transcript segments: {phase2['segment_count']}",
        f"- Timestamped words: {phase2['word_count']}",
        f"- Processing: {performance['processing_seconds']} seconds",
        (
            "- Python allocator peak: "
            f"{performance['python_allocator_peak_bytes']} bytes"
        ),
        "",
        "## Gate results",
        "",
    ]
    lines.extend(
        f"- {'PASS' if passed else 'FAIL'} — {name.replace('_', ' ')}"
        for name, passed in report["assertions"].items()
    )
    lines.extend(
        [
            "",
            "The qualification deliberately uses synthetic marker providers. "
            "It proves Phase 2 addressing, inherited overlap ownership, cache "
            "resume, integrity, and canonical assembly across the existing "
            "long Phase 1 corpus; it does not measure recognition quality.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus_root", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("report_json", type=Path)
    parser.add_argument("report_markdown", type=Path)
    args = parser.parse_args()
    report = qualify(args.corpus_root, args.destination)
    args.report_json.parent.mkdir(parents=True, exist_ok=True)
    args.report_json.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.report_markdown.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
