from __future__ import annotations

from pathlib import Path

import pytest

from ratiocinatus.cli import EXIT_SUCCESS, main
from ratiocinatus.correction_contracts import TranscriptViewKind
from ratiocinatus.corrections import (
    build_transcript_revision,
    prepare_correction_batch,
)
from ratiocinatus.identity_binding import append_manual_identity_binding
from ratiocinatus.identity_view import assemble_identity_views
from ratiocinatus.kernel import canonical_bytes
from ratiocinatus.participant_subtitle_contracts import (
    PARTICIPANT_SUBTITLE_CONTRACT_MODELS,
)
from ratiocinatus.participant_subtitles import (
    ParticipantSubtitleIntegrityError,
    export_participant_subtitles,
    validate_participant_subtitles,
)
from ratiocinatus.phase3_contracts import BindingAction
from ratiocinatus.speaker_transcript import (
    build_speaker_labeled_transcript,
    persist_speaker_labeled_transcript,
)
from ratiocinatus.speaker_transcript_contracts import (
    SpeakerLabeledTranscriptPolicy,
)
from ratiocinatus.subtitle_contracts import SubtitleFormat

from test_phase2_transcript_assembly import replacement_draft
from test_phase3_clustering import HAS_FFMPEG
from test_phase3_identity_binding import NOW, _certainty
from test_phase3_speaker_transcript import _speaker_inputs


def test_participant_subtitle_contract_schemas_are_closed() -> None:
    assert len(PARTICIPANT_SUBTITLE_CONTRACT_MODELS) == 4
    for model in PARTICIPANT_SUBTITLE_CONTRACT_MODELS:
        schema = model.model_json_schema()
        assert schema["title"] == model.__name__
        assert schema.get("additionalProperties") is False


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_participant_webvtt_and_srt_preserve_identity_and_unknown_lineage(
    tmp_path: Path,
) -> None:
    values, transcript, identity_assembly = _speaker_inputs(tmp_path)
    speaker_view = build_speaker_labeled_transcript(
        transcript,
        values[1],
        identity_assembly,
        created_at=NOW,
    )
    manifest, report, root, reused = export_participant_subtitles(
        speaker_view,
        transcript,
        tmp_path / "participant-subtitles",
    )
    assert not reused
    assert manifest.speaker_transcript_view_id == speaker_view.view_id
    assert manifest.source_transcript_version_id == (
        transcript.version.version_id
    )
    assert manifest.identity_view_assembly_id == identity_assembly.assembly_id
    assert manifest.reviewed_identity_view_id == (
        speaker_view.reviewed_identity_view_id
    )
    assert {item.subtitle_format for item in manifest.files} == {
        SubtitleFormat.WEBVTT,
        SubtitleFormat.SRT,
    }
    assert any(item.unresolved for item in manifest.cues)
    assert any(
        item.overlap_disclosed
        and item.speaker_label.startswith("OVERLAP: ")
        for item in manifest.cues
    )
    assert report.valid
    assert (root / "participant-transcript.vtt").read_text(
        encoding="utf-8"
    ).startswith("WEBVTT\n")
    assert "Reviewed identity view" in (
        root / "participant-transcript.vtt"
    ).read_text(encoding="utf-8")
    assert "-->" in (root / "participant-transcript.srt").read_text(
        encoding="utf-8"
    )


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_corrected_participant_subtitles_declare_revision(
    tmp_path: Path,
) -> None:
    values, transcript, identity_assembly = _speaker_inputs(tmp_path)
    revision, _ = build_transcript_revision(
        transcript,
        prepare_correction_batch(
            transcript.version.version_id,
            (replacement_draft(transcript),),
        ),
    )
    speaker_view = build_speaker_labeled_transcript(
        transcript,
        values[1],
        identity_assembly,
        revision=revision,
        policy=SpeakerLabeledTranscriptPolicy(
            transcript_view_kind=TranscriptViewKind.CURRENT_CORRECTED
        ),
        created_at=NOW,
    )
    manifest, _, _, _ = export_participant_subtitles(
        speaker_view,
        transcript,
        tmp_path / "corrected-subtitles",
    )
    assert manifest.source_revision_id == revision.revision_id
    assert manifest.source_transcript_version_id == (
        revision.version.version_id
    )
    assert manifest.cues[0].text == "Corrected words"


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_conflicted_speaker_transcript_refuses_participant_export(
    tmp_path: Path,
) -> None:
    values, transcript, _ = _speaker_inputs(tmp_path)
    (
        response,
        diarization,
        clustering,
        foundation,
        first,
        _,
        scope,
        identities,
    ) = values[:8]
    conflicted, _ = append_manual_identity_binding(
        foundation,
        clustering,
        diarization,
        target_artifact_id=scope.target_id,
        identity_id=identities[1].identity_id,
        scope=scope,
        action=BindingAction.BIND,
        author_id="reviewer:subtitle-conflict",
        author_display_name="Subtitle Conflict Reviewer",
        rationale="Independent conflicting branch for subtitle refusal.",
        supporting_evidence_references=("fixture:subtitle:conflict",),
        reviewer_certainty=_certainty(0.7),
        predecessor=first,
        created_at=NOW,
    )
    identity_assembly = assemble_identity_views(
        response,
        diarization,
        clustering,
        foundation,
        conflicted,
        created_at=NOW,
    )
    speaker_view = build_speaker_labeled_transcript(
        transcript,
        diarization,
        identity_assembly,
        created_at=NOW,
    )
    with pytest.raises(
        ParticipantSubtitleIntegrityError, match="refuses participant subtitles"
    ):
        export_participant_subtitles(
            speaker_view,
            transcript,
            tmp_path / "refused",
        )


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_participant_subtitle_cache_validation_corruption_and_cli(
    tmp_path: Path,
) -> None:
    values, transcript, identity_assembly = _speaker_inputs(tmp_path)
    speaker_view = build_speaker_labeled_transcript(
        transcript,
        values[1],
        identity_assembly,
        created_at=NOW,
    )
    output = tmp_path / "cached"
    manifest, report, root, _ = export_participant_subtitles(
        speaker_view, transcript, output
    )
    assert export_participant_subtitles(
        speaker_view, transcript, output
    )[-1]
    validate_participant_subtitles(
        manifest, root, speaker_view, transcript, report=report
    )
    (root / "participant-transcript.srt").write_text(
        "corrupt", encoding="utf-8"
    )
    with pytest.raises(
        ParticipantSubtitleIntegrityError, match="failed validation"
    ):
        export_participant_subtitles(speaker_view, transcript, output)

    assembly_root = tmp_path / "assembly"
    assembly_root.mkdir()
    (assembly_root / "assembly.json").write_bytes(canonical_bytes(transcript))
    speaker_root = persist_speaker_labeled_transcript(
        speaker_view,
        transcript,
        values[1],
        identity_assembly,
        tmp_path / "speaker-view",
    )[2]
    destination = tmp_path / "subtitle-cli"
    assert main(
        [
            "--json",
            "diarization",
            "participant-subtitle-export",
            str(speaker_root),
            str(assembly_root),
            str(destination),
        ]
    ) == EXIT_SUCCESS
    cli_root = next((destination / "participant-subtitles").iterdir())
    assert main(
        [
            "--json",
            "diarization",
            "participant-subtitle-inspect",
            str(cli_root),
        ]
    ) == EXIT_SUCCESS
    assert main(
        [
            "--json",
            "diarization",
            "participant-subtitle-list-cues",
            str(cli_root),
        ]
    ) == EXIT_SUCCESS
    assert main(
        [
            "--json",
            "diarization",
            "participant-subtitle-validate",
            str(cli_root),
            str(speaker_root),
            str(assembly_root),
        ]
    ) == EXIT_SUCCESS
