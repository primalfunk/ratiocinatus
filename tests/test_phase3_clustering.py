from __future__ import annotations

import math
import shutil
import wave
from array import array
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ratiocinatus.activity import FFmpegEnergySpeechActivityProvider
from ratiocinatus.addressing_contracts import MediaInterval, TimeDomain
from ratiocinatus.clustering import (
    ClusteringIntegrityError,
    ClusteringUnavailable,
    cluster_diarization,
)
from ratiocinatus.cli import EXIT_SUCCESS, main
from ratiocinatus.clustering_contracts import (
    CLUSTERING_CONTRACT_MODELS,
    ClusterConsistencyDisposition,
    ClusterProposalDisposition,
)
from ratiocinatus.diarization import diarize_corpus
from ratiocinatus.diarization_providers import DiarizationProvider
from ratiocinatus.ingestion import prepare_ingestion_request, run_ingestion
from ratiocinatus.kernel import canonical_hash, typed_id
from ratiocinatus.phase2_contracts import (
    ConfidenceMeasure,
    ConfidenceOrigin,
    RawEvidenceDisposition,
    RawProviderEvidence,
)
from ratiocinatus.phase3_contracts import (
    DiarizationCapability,
    DiarizationProviderCapabilities,
    DiarizationProviderIdentity,
    DiarizationProviderResponse,
    EmbeddingStorageDisposition,
    ObservationUsability,
    OverlapClassification,
    ProviderOverlapInterval,
    ProviderSpeakerObservation,
    ProviderSpeakerTurn,
    SpeakerEmbedding,
    SpeakerTurnKind,
)
from ratiocinatus.speech_activity import detect_corpus_activity

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
NOW = datetime(2000, 1, 1, tzinfo=timezone.utc)


def _confidence(value: float = 0.8) -> ConfidenceMeasure:
    return ConfidenceMeasure(
        value=value,
        origin=ConfidenceOrigin.PROVIDER_NATIVE,
        basis="controlled clustering provider",
    )


class ConflictedClusteringProvider(DiarizationProvider):
    def __init__(
        self, *, mixed_embeddings: bool = False, missing_labels: bool = False
    ) -> None:
        self.mixed_embeddings = mixed_embeddings
        self.missing_labels = missing_labels

    @property
    def capabilities(self) -> DiarizationProviderCapabilities:
        provider_id = (
            "test.mixed_embedding_clustering"
            if self.mixed_embeddings
            else (
                "test.unclustered_observations"
                if self.missing_labels
                else "test.conflicted_clustering"
            )
        )
        return DiarizationProviderCapabilities(
            identity=DiarizationProviderIdentity(
                provider_id=provider_id,
                display_name="Controlled conflicted clustering provider",
                provider_version="1.0.0",
                local=True,
            ),
            capabilities=(
                DiarizationCapability.TURN_SEGMENTATION,
                DiarizationCapability.OVERLAPPING_SPEECH,
                DiarizationCapability.SPEAKER_CLUSTERING,
                DiarizationCapability.SPEAKER_EMBEDDINGS,
            ),
            available=True,
            confidence_scores=True,
        )

    def diarize(
        self,
        request,
        normalized_audio: Path,
        *,
        evidence_root: Path | None = None,
    ) -> DiarizationProviderResponse:
        evidence = request.speech_intervals[0]
        base = evidence.normalized_audio_interval
        duration = base.duration_microseconds * 7 // 10
        starts = (
            base.start_microseconds,
            base.start_microseconds + base.duration_microseconds * 3 // 10,
        )
        chunk = next(
            item
            for item in request.chunks
            if item.chunk_id == evidence.processing_chunk_id
        )
        observations = []
        turns = []
        embeddings = []
        for ordinal, start in enumerate(starts):
            normalized = MediaInterval(
                domain=TimeDomain.NORMALIZED_CORPUS,
                start_microseconds=start,
                duration_microseconds=duration,
            )
            source = MediaInterval(
                domain=TimeDomain.SOURCE_MEDIA,
                start_microseconds=(
                    start + request.source_mapping_offset_microseconds
                ),
                duration_microseconds=duration,
            )
            observation_id = typed_id(
                "spkobs", request.request_id, ordinal
            )
            embedding_id = (
                typed_id("spkembed", request.request_id, ordinal)
                if self.mixed_embeddings
                else None
            )
            observations.append(
                ProviderSpeakerObservation(
                    observation_id=observation_id,
                    speech_interval_ids=(evidence.interval_id,),
                    source_interval=source,
                    normalized_audio_interval=normalized,
                    chunk_local_interval=MediaInterval(
                        domain=TimeDomain.CHUNK_LOCAL,
                        start_microseconds=(
                            start
                            - chunk.corpus_interval.start_microseconds
                        ),
                        duration_microseconds=duration,
                    ),
                    processing_chunk_id=chunk.chunk_id,
                    provider_speaker_label=(
                        None if self.missing_labels else "VOICE_GROUP_A"
                    ),
                    acoustic_evidence_available=True,
                    usability=ObservationUsability.PROVISIONAL,
                    usability_confidence=_confidence(),
                    embedding_id=embedding_id,
                )
            )
            turns.append(
                ProviderSpeakerTurn(
                    provider_turn_id=f"turn-{ordinal}",
                    observation_ids=(observation_id,),
                    source_interval=source,
                    normalized_audio_interval=normalized,
                    provider_speaker_label=(
                        None if self.missing_labels else "VOICE_GROUP_A"
                    ),
                    turn_kind=SpeakerTurnKind.SINGLE_SPEAKER,
                    boundary_confidence=_confidence(),
                    assignment_confidence=_confidence(),
                )
            )
            if embedding_id is not None:
                embeddings.append(
                    SpeakerEmbedding(
                        embedding_id=embedding_id,
                        observation_id=observation_id,
                        model_space_id=f"test.embedding_space_{ordinal}",
                        model_fingerprint=str(ordinal + 1) * 64,
                        dimension_count=192,
                        numeric_format="float32",
                        extraction_interval=normalized,
                        storage_disposition=(
                            EmbeddingStorageDisposition.OMITTED
                        ),
                    )
                )
        overlap_start = starts[1]
        overlap_duration = starts[0] + duration - overlap_start
        overlap_normalized = MediaInterval(
            domain=TimeDomain.NORMALIZED_CORPUS,
            start_microseconds=overlap_start,
            duration_microseconds=overlap_duration,
        )
        overlap = ProviderOverlapInterval(
            provider_overlap_id="conflict-overlap",
            source_interval=MediaInterval(
                domain=TimeDomain.SOURCE_MEDIA,
                start_microseconds=(
                    overlap_start
                    + request.source_mapping_offset_microseconds
                ),
                duration_microseconds=overlap_duration,
            ),
            normalized_audio_interval=overlap_normalized,
            classification=OverlapClassification.SIMULTANEOUS_SPEECH,
            estimated_active_speaker_count=2,
            candidate_provider_labels=(
                ()
                if self.missing_labels
                else ("VOICE_GROUP_A", "VOICE_GROUP_A")
            ),
            overlap_confidence=_confidence(0.9),
            speaker_count_confidence=_confidence(0.7),
        )
        normalized_hash = canonical_hash(
            {
                "request_id": request.request_id,
                "provider": request.provider.model_dump(mode="json"),
                "observations": [
                    item.model_dump(mode="json") for item in observations
                ],
                "turns": [item.model_dump(mode="json") for item in turns],
                "overlaps": [overlap.model_dump(mode="json")],
                "embeddings": [
                    item.model_dump(mode="json") for item in embeddings
                ],
            }
        )
        return DiarizationProviderResponse(
            response_id=typed_id(
                "diaresponse", request.request_id, "clustering"
            ),
            request_id=request.request_id,
            provider=request.provider,
            started_at=NOW,
            completed_at=NOW,
            observations=tuple(observations),
            turns=tuple(turns),
            overlaps=(overlap,),
            embeddings=tuple(embeddings),
            raw_evidence=RawProviderEvidence(
                disposition=RawEvidenceDisposition.UNAVAILABLE,
                explanation="controlled clustering evidence",
            ),
            normalized_evidence_sha256=normalized_hash,
            complete=True,
        )


def _write_fixture(path: Path) -> None:
    samples = array("h")
    for index in range(3 * 48_000):
        second = index / 48_000
        value = (
            int(0.25 * 32767 * math.sin(2 * math.pi * 440 * second))
            if 1 <= second < 2
            else 0
        )
        samples.append(value)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(48_000)
        output.writeframes(samples.tobytes())


def _prepare(tmp_path: Path, provider: DiarizationProvider):
    source = tmp_path / "clustering-fixture.wav"
    _write_fixture(source)
    phase1 = tmp_path / "phase1"
    request = prepare_ingestion_request(source, phase1)
    run_ingestion(request)
    corpus_root = (
        phase1 / "ingestions" / request.ingestion_id / "corpus"
    )
    _, _, activity_root, _ = detect_corpus_activity(
        corpus_root,
        tmp_path / "phase2",
        provider=FFmpegEnergySpeechActivityProvider(),
    )
    result = diarize_corpus(
        corpus_root,
        activity_root,
        tmp_path / "phase3",
        provider=provider,
    )
    return result


def test_clustering_contract_schemas_are_closed() -> None:
    assert len(CLUSTERING_CONTRACT_MODELS) == 8
    for model in CLUSTERING_CONTRACT_MODELS:
        schema = model.model_json_schema()
        assert schema["title"] == model.__name__
        assert schema.get("additionalProperties") is False


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_provisional_clustering_conflict_split_persistence_and_reuse(
    tmp_path: Path,
) -> None:
    provider = ConflictedClusteringProvider()
    _, _, diarization, _, diarization_root, _ = _prepare(
        tmp_path, provider
    )
    result = cluster_diarization(
        diarization_root,
        tmp_path / "phase3-clustering",
        capabilities=provider.capabilities,
    )
    run, report, root, reused = result

    assert not reused
    assert len(run.clusters) == 1
    assert len(run.memberships) == 2
    assert not run.unclustered_observation_ids
    assert run.consistency_results[0].disposition == (
        ClusterConsistencyDisposition.LIKELY_OVER_MERGED
    )
    assert len(run.split_proposals) == 1
    assert run.split_proposals[0].disposition == (
        ClusterProposalDisposition.REVIEW_REQUIRED
    )
    assert {
        item
        for partition in run.split_proposals[0].partitions
        for item in partition.observation_ids
    } == {item.observation_id for item in diarization.observations}
    assert not run.merge_proposals
    assert report.unresolved_conflict_count == 1
    assert report.status == "warning"
    assert "VOICE_GROUP_A" not in run.model_dump_json()
    assert (root / "clustering.json").is_file()
    assert (root / "report.json").is_file()
    assert main(
        ["--json", "diarization", "inspect-clustering", str(root)]
    ) == EXIT_SUCCESS
    assert main(
        [
            "--json",
            "diarization",
            "validate-clustering",
            str(root),
            str(diarization_root),
        ]
    ) == EXIT_SUCCESS
    assert main(
        ["--json", "diarization", "list-clusters", str(root)]
    ) == EXIT_SUCCESS
    assert main(
        [
            "--json",
            "diarization",
            "list-cluster-consistency",
            str(root),
        ]
    ) == EXIT_SUCCESS

    cached = cluster_diarization(
        diarization_root,
        tmp_path / "phase3-clustering",
        capabilities=provider.capabilities,
    )
    assert cached[-1]
    assert cached[0] == run
    limited = provider.capabilities.model_copy(
        update={
            "capabilities": (DiarizationCapability.TURN_SEGMENTATION,)
        }
    )
    with pytest.raises(ClusteringUnavailable, match="does not declare"):
        cluster_diarization(
            diarization_root,
            tmp_path / "phase3-clustering-unavailable",
            capabilities=limited,
        )

    (root / "report.json").unlink()
    with pytest.raises(
        ClusteringIntegrityError, match="cache.*incomplete"
    ):
        cluster_diarization(
            diarization_root,
            tmp_path / "phase3-clustering",
            capabilities=provider.capabilities,
        )


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_mixed_embedding_model_spaces_refuse_clustering(
    tmp_path: Path,
) -> None:
    provider = ConflictedClusteringProvider(mixed_embeddings=True)
    _, _, _, _, diarization_root, _ = _prepare(tmp_path, provider)
    with pytest.raises(
        ClusteringIntegrityError, match="incompatible embedding model spaces"
    ):
        cluster_diarization(
            diarization_root,
            tmp_path / "phase3-clustering",
            capabilities=provider.capabilities,
        )

@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_missing_acoustic_labels_remain_explicitly_unclustered(
    tmp_path: Path,
) -> None:
    provider = ConflictedClusteringProvider(missing_labels=True)
    _, _, diarization, _, diarization_root, _ = _prepare(
        tmp_path, provider
    )
    run, report, _, _ = cluster_diarization(
        diarization_root,
        tmp_path / "phase3-clustering",
        capabilities=provider.capabilities,
    )

    assert not run.clusters
    assert not run.memberships
    assert set(run.unclustered_observation_ids) == {
        item.observation_id for item in diarization.observations
    }
    assert report.unclustered_observation_count == len(
        diarization.observations
    )
    assert report.status == "warning"