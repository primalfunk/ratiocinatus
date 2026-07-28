from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from ratiocinatus.addressing_contracts import MediaInterval, TimeDomain
from ratiocinatus.clustering import cluster_diarization
from ratiocinatus.cli import EXIT_SUCCESS, main
from ratiocinatus.identity import (
    add_participant_identity,
    persist_identity_foundation,
)
from ratiocinatus.phase3_contracts import (
    IdentityKind,
    IdentityScope,
    IdentityScopeKind,
)
from ratiocinatus.reference_enrollment_contracts import (
    ReferenceAudioQuality,
    ReferenceContamination,
    ReferenceLawfulUseStatus,
    ReferenceLicenseStatus,
)
from ratiocinatus.reference_enrollment_operations import (
    enroll_reference_voice,
    persist_reference_enrollment,
)

from test_phase3_clustering import (
    HAS_FFMPEG,
    ConflictedClusteringProvider,
    _prepare,
)

NOW = datetime(2000, 1, 1, tzinfo=timezone.utc)


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_reference_comparison_cli_create_inspect_list_and_validate(
    tmp_path: Path,
) -> None:
    provider = ConflictedClusteringProvider()
    _, _, diarization, _, diarization_root, _ = _prepare(tmp_path, provider)
    clustering, _, clustering_root, _ = cluster_diarization(
        diarization_root,
        tmp_path / "clusters",
        capabilities=provider.capabilities,
    )
    cluster = clustering.clusters[0]
    scope = IdentityScope(
        kind=IdentityScopeKind.CLUSTER,
        target_id=cluster.cluster_id,
        explanation="CLI comparison is bounded to this cluster.",
    )
    foundation, identity = add_participant_identity(
        clustering,
        diarization,
        canonical_display_label="CLI comparison participant",
        identity_kind=IdentityKind.NAMED_INDIVIDUAL,
        information_source="controlled CLI comparison roster",
        scope=scope,
        provenance_references=("fixture:cli:comparison-identity",),
        created_at=NOW,
    )
    foundation_root = persist_identity_foundation(
        foundation,
        clustering,
        diarization,
        tmp_path / "identity",
    )[2]
    enrollment, reference = enroll_reference_voice(
        foundation,
        identity_id=identity.identity_id,
        source_reference="fixture:cli:comparison-reference",
        license_status=ReferenceLicenseStatus.PERMISSION_GRANTED,
        lawful_use_status=ReferenceLawfulUseStatus.CONSENT_RECORDED,
        rights_basis_reference="fixture:cli:comparison-consent",
        recording_provenance_references=(
            "fixture:cli:comparison-recording",
        ),
        source_interval=MediaInterval(
            domain=TimeDomain.SOURCE_MEDIA,
            start_microseconds=0,
            duration_microseconds=5_000_000,
        ),
        audio_quality=ReferenceAudioQuality.ACCEPTABLE,
        speech_duration_microseconds=4_000_000,
        contamination=ReferenceContamination.CLEAN,
        extraction_provider="controlled.reference.extractor/1",
        model_space_id="controlled.voice.v1",
        model_fingerprint="a" * 64,
        representation_reference="protected:cli-comparison-reference",
        representation_sha256="b" * 64,
        enrollment_scope=scope,
        created_at=NOW,
    )
    enrollment_root = persist_reference_enrollment(
        enrollment,
        foundation,
        tmp_path / "enrollments",
    )[2]
    destination = tmp_path / "comparisons"
    assert main(
        [
            "--json",
            "diarization",
            "reference-compare",
            str(clustering_root),
            str(diarization_root),
            str(foundation_root),
            str(enrollment_root),
            str(destination),
            "--target-kind",
            "cluster",
            "--target",
            cluster.cluster_id,
            "--reference",
            reference.reference_id,
            "--score",
            "0.90",
            "--provider",
            "controlled.cli.comparison/1",
            "--method",
            "controlled cosine-like score",
            "--representation-reference",
            "protected:cli-comparison-target",
            "--representation-sha256",
            "a" * 64,
            "--model-space",
            "controlled.voice.v1",
            "--model-fingerprint",
            "a" * 64,
            "--extraction-provider",
            "controlled.target.extractor/1",
            "--speech-duration-us",
            "6000000",
            "--audio-quality",
            "acceptable",
            "--channel-compatibility",
            "compatible",
            "--provenance",
            "fixture:cli:comparison-target",
            "--supporting",
            "fixture:cli:score:0.90",
        ]
    ) == EXIT_SUCCESS
    comparison_root = next(
        (destination / "reference-comparisons").iterdir()
    )
    for action in (
        "reference-comparison-inspect",
        "reference-comparison-list",
    ):
        assert main(
            ["--json", "diarization", action, str(comparison_root)]
        ) == EXIT_SUCCESS
    assert main(
        [
            "--json",
            "diarization",
            "reference-comparison-validate",
            str(comparison_root),
            str(clustering_root),
            str(diarization_root),
            str(foundation_root),
            str(enrollment_root),
        ]
    ) == EXIT_SUCCESS
