from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

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

from test_phase3_clustering import (
    HAS_FFMPEG,
    ConflictedClusteringProvider,
    _prepare,
)

NOW = datetime(2000, 1, 1, tzinfo=timezone.utc)


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_reference_enrollment_cli_create_inspect_list_and_validate(
    tmp_path: Path,
) -> None:
    provider = ConflictedClusteringProvider()
    _, _, diarization, _, diarization_root, _ = _prepare(tmp_path, provider)
    clustering, _, _, _ = cluster_diarization(
        diarization_root,
        tmp_path / "clusters",
        capabilities=provider.capabilities,
    )
    cluster = clustering.clusters[0]
    scope = IdentityScope(
        kind=IdentityScopeKind.CLUSTER,
        target_id=cluster.cluster_id,
        explanation="Controlled CLI reference scope.",
    )
    foundation, identity = add_participant_identity(
        clustering,
        diarization,
        canonical_display_label="CLI reference participant",
        identity_kind=IdentityKind.NAMED_INDIVIDUAL,
        information_source="controlled fixture roster",
        scope=scope,
        provenance_references=("fixture:cli:identity",),
        created_at=NOW,
    )
    foundation_root = persist_identity_foundation(
        foundation,
        clustering,
        diarization,
        tmp_path / "identity",
    )[2]
    destination = tmp_path / "references"
    assert main(
        [
            "--json",
            "diarization",
            "reference-enroll",
            str(foundation_root),
            str(destination),
            "--identity",
            identity.identity_id,
            "--source",
            "fixture:cli:reference",
            "--license-status",
            "permission_granted",
            "--lawful-use-status",
            "consent_recorded",
            "--rights-basis",
            "fixture:cli:consent",
            "--provenance",
            "fixture:cli:recording",
            "--source-start-us",
            "0",
            "--source-duration-us",
            "5000000",
            "--speech-duration-us",
            "4000000",
            "--audio-quality",
            "acceptable",
            "--contamination",
            "clean",
            "--extraction-provider",
            "controlled.reference.extractor/1",
            "--model-space",
            "controlled.voice.v1",
            "--model-fingerprint",
            "a" * 64,
            "--representation-reference",
            "protected:cli-reference.embedding",
            "--representation-sha256",
            "b" * 64,
            "--scope-kind",
            "cluster",
            "--scope-target",
            cluster.cluster_id,
            "--scope-explanation",
            "Controlled CLI reference scope.",
        ]
    ) == EXIT_SUCCESS
    enrollment_root = next(
        (destination / "reference-enrollments").iterdir()
    )
    assert main(
        [
            "--json",
            "diarization",
            "reference-inspect",
            str(enrollment_root),
        ]
    ) == EXIT_SUCCESS
    assert main(
        [
            "--json",
            "diarization",
            "reference-list",
            str(enrollment_root),
        ]
    ) == EXIT_SUCCESS
    assert main(
        [
            "--json",
            "diarization",
            "reference-validate",
            str(enrollment_root),
            str(foundation_root),
        ]
    ) == EXIT_SUCCESS
