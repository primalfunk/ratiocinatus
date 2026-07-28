from __future__ import annotations

from pathlib import Path

import pytest

from ratiocinatus.phase4_export import (
    Phase4ExportIntegrityError,
    export_phase4_corpus,
    load_phase4_export,
    validate_phase4_export,
)
from ratiocinatus.phase4_review import (
    build_review_queue,
    create_review_ledger,
)

from test_phase3_clustering import HAS_FFMPEG
from test_phase3_speaker_transcript import NOW
from test_phase4_evaluation import _reference
from test_phase4_propagation_review import _artifact_set


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_portable_export_reloads_without_provider_execution(
    tmp_path: Path,
) -> None:
    artifacts = _artifact_set(tmp_path)
    ledger = create_review_ledger(
        artifacts.corpus, artifacts.transcript_views, created_at=NOW
    )
    queue = build_review_queue(ledger, artifacts, generated_at=NOW)
    reference = _reference(artifacts)
    first = export_phase4_corpus(
        artifacts,
        tmp_path / "export",
        Path("schemas"),
        review_ledger=ledger,
        review_queue=queue,
        reference=reference,
        created_at=NOW,
    )
    replay = export_phase4_corpus(
        artifacts,
        tmp_path / "export",
        Path("schemas"),
        review_ledger=ledger,
        review_queue=queue,
        reference=reference,
        created_at=NOW,
    )
    assert not first[3]
    assert replay[3]
    manifest, report = load_phase4_export(first[2])
    assert (manifest, report) == first[:2]
    assert report.status == "valid"
    assert not report.provider_execution_used
    assert not manifest.policy.provider_execution_required_for_inspection
    assert report.artifact_count >= 8
    assert report.schema_count > 0
    assert all(
        not Path(item.relative_path).is_absolute()
        for item in manifest.entries
    )


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_portable_export_detects_corruption(
    tmp_path: Path,
) -> None:
    artifacts = _artifact_set(tmp_path)
    manifest, _, root, _ = export_phase4_corpus(
        artifacts,
        tmp_path / "export",
        Path("schemas"),
        created_at=NOW,
    )
    target = root / manifest.entries[0].relative_path
    target.write_bytes(target.read_bytes() + b"corrupt")
    report = validate_phase4_export(root)
    assert report.status == "invalid"
    assert manifest.entries[0].relative_path in report.digest_mismatch_paths
    with pytest.raises(Phase4ExportIntegrityError, match="stale"):
        load_phase4_export(root)
