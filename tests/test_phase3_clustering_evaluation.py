from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from ratiocinatus.clustering import cluster_diarization
from ratiocinatus.cli import EXIT_SUCCESS, main
from ratiocinatus.clustering_evaluation import (
    ClusteringEvaluationIntegrityError,
    create_diarization_reference,
    evaluate_clustering,
    evaluate_clustering_artifacts,
    validate_clustering_evaluation,
)
from ratiocinatus.clustering_evaluation_contracts import (
    CLUSTERING_EVALUATION_CONTRACT_MODELS,
    DiarizationReference,
    EmbeddingQualificationDisposition,
)
from ratiocinatus.diarization_providers import DiarizationProvider
from ratiocinatus.kernel import canonical_bytes, canonical_hash
from ratiocinatus.phase3_contracts import EmbeddingStorageDisposition

from test_phase3_clustering import (
    HAS_FFMPEG,
    ConflictedClusteringProvider,
    _prepare,
)


class CompatibleMetadataEmbeddingProvider(DiarizationProvider):
    def __init__(self) -> None:
        self.base = ConflictedClusteringProvider(mixed_embeddings=True)

    @property
    def capabilities(self):
        return self.base.capabilities

    def diarize(
        self,
        request,
        normalized_audio: Path,
        *,
        evidence_root: Path | None = None,
    ):
        response = self.base.diarize(
            request,
            normalized_audio,
            evidence_root=evidence_root,
        )
        embeddings = tuple(
            item.model_copy(
                update={
                    "model_space_id": "test.compatible_embedding_space",
                    "model_fingerprint": "a" * 64,
                }
            )
            for item in response.embeddings
        )
        normalized_hash = canonical_hash(
            {
                "request_id": request.request_id,
                "provider": response.provider.model_dump(mode="json"),
                "observations": [
                    item.model_dump(mode="json")
                    for item in response.observations
                ],
                "turns": [
                    item.model_dump(mode="json") for item in response.turns
                ],
                "overlaps": [
                    item.model_dump(mode="json")
                    for item in response.overlaps
                ],
                "embeddings": [
                    item.model_dump(mode="json") for item in embeddings
                ],
            }
        )
        return response.model_copy(
            update={
                "embeddings": embeddings,
                "normalized_evidence_sha256": normalized_hash,
            }
        )


def test_clustering_evaluation_contract_schemas_are_closed() -> None:
    assert len(CLUSTERING_EVALUATION_CONTRACT_MODELS) == 7
    for model in CLUSTERING_EVALUATION_CONTRACT_MODELS:
        schema = model.model_json_schema()
        assert schema["title"] == model.__name__
        assert schema.get("additionalProperties") is False


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_controlled_pairwise_evaluation_and_embedding_metadata_qualification(
    tmp_path: Path,
) -> None:
    provider = CompatibleMetadataEmbeddingProvider()
    _, response, diarization, _, diarization_root, _ = _prepare(
        tmp_path, provider
    )
    clustering, _, clustering_root, _ = cluster_diarization(
        diarization_root,
        tmp_path / "clusters",
        capabilities=provider.capabilities,
    )
    observations = sorted(
        item.observation_id for item in diarization.observations
    )
    reference = create_diarization_reference(
        diarization,
        {
            observations[0]: "controlled_speaker_a",
            observations[1]: "controlled_speaker_b",
        },
        provenance=(
            "Project-authored controlled fixture labels fixed independently.",
        ),
        created_at=datetime(2000, 1, 1, tzinfo=timezone.utc),
    )
    reference_path = tmp_path / "reference.json"
    reference_path.write_bytes(canonical_bytes(reference))

    evaluation, report, root, reused = evaluate_clustering_artifacts(
        clustering_root,
        diarization_root,
        reference_path,
        tmp_path / "evaluations",
    )

    assert not reused
    assert evaluation.metrics.evaluated_pair_count == 1
    assert evaluation.metrics.different_speaker_same_cluster_pairs == 1
    assert evaluation.metrics.same_speaker_precision == 0.0
    assert evaluation.metrics.same_speaker_recall is None
    assert evaluation.metrics.reference_coverage == 1.0
    assert evaluation.embedding_qualification.disposition == (
        EmbeddingQualificationDisposition.QUALIFIED_METADATA_ONLY
    )
    assert not evaluation.embedding_qualification.comparison_eligible
    assert evaluation.status == "warning"
    assert report.status == "warning"
    assert (root / "evaluation.json").is_file()
    assert (root / "report.json").is_file()
    assert (root / "report.md").is_file()
    assert "controlled_speaker" not in clustering.model_dump_json()
    validate_clustering_evaluation(evaluation, clustering, diarization)
    cli_destination = tmp_path / "cli-evaluations"
    assert main(
        [
            "--json",
            "diarization",
            "evaluate-clustering",
            str(clustering_root),
            str(diarization_root),
            str(reference_path),
            str(cli_destination),
        ]
    ) == EXIT_SUCCESS
    assert main(
        ["--json", "diarization", "inspect-clustering-evaluation", str(root)]
    ) == EXIT_SUCCESS
    assert main(
        [
            "--json",
            "diarization",
            "validate-clustering-evaluation",
            str(root),
            str(clustering_root),
            str(diarization_root),
        ]
    ) == EXIT_SUCCESS

    cached = evaluate_clustering_artifacts(
        clustering_root,
        diarization_root,
        reference_path,
        tmp_path / "evaluations",
    )
    assert cached[-1]
    assert cached[0] == evaluation

    assert response.embeddings
    unsafe_embedding = response.embeddings[0].model_copy(
        update={
            "storage_disposition": (
                EmbeddingStorageDisposition.PROTECTED_REFERENCE
            ),
            "relative_path": "../outside-protected-root.bin",
            "content_sha256": "0" * 64,
            "byte_size": 1,
        }
    )
    unsafe_response = response.model_copy(
        update={
            "embeddings": (
                unsafe_embedding,
                *response.embeddings[1:],
            )
        }
    )
    blocked = evaluate_clustering(
        clustering,
        diarization,
        unsafe_response,
        reference,
        diarization_root,
    )
    assert blocked.status == "blocked"
    assert blocked.embedding_qualification.disposition == (
        EmbeddingQualificationDisposition.BLOCKED_INTEGRITY
    )


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_reference_lineage_and_partial_cache_are_refused(
    tmp_path: Path,
) -> None:
    provider = CompatibleMetadataEmbeddingProvider()
    _, _, diarization, _, diarization_root, _ = _prepare(tmp_path, provider)
    _, _, clustering_root, _ = cluster_diarization(
        diarization_root,
        tmp_path / "clusters",
        capabilities=provider.capabilities,
    )
    observations = sorted(
        item.observation_id for item in diarization.observations
    )
    reference = create_diarization_reference(
        diarization,
        {item: "controlled_same_voice" for item in observations},
        provenance=("Independent controlled fixture labels.",),
    )
    reference_path = tmp_path / "reference.json"
    reference_path.write_bytes(canonical_bytes(reference))
    evaluation, _, root, _ = evaluate_clustering_artifacts(
        clustering_root,
        diarization_root,
        reference_path,
        tmp_path / "evaluations",
    )
    assert evaluation.metrics.same_speaker_same_cluster_pairs == 1
    assert evaluation.metrics.same_speaker_f1 == 1.0

    (root / "report.json").unlink()
    with pytest.raises(
        ClusteringEvaluationIntegrityError, match="cache.*incomplete"
    ):
        evaluate_clustering_artifacts(
            clustering_root,
            diarization_root,
            reference_path,
            tmp_path / "evaluations",
        )

    invalid = reference.model_copy(
        update={"source_artifact_sha256": "f" * 64}
    )
    invalid_path = tmp_path / "invalid-reference.json"
    invalid_path.write_bytes(canonical_bytes(invalid))
    with pytest.raises(
        ClusteringEvaluationIntegrityError, match="integrity"
    ):
        evaluate_clustering_artifacts(
            clustering_root,
            diarization_root,
            invalid_path,
            tmp_path / "invalid-evaluation",
        )
