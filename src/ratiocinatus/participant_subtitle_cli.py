"""CLI integration for participant-labeled subtitle derivatives."""

from __future__ import annotations

from pathlib import Path

from .kernel import load_contract
from .participant_subtitle_contracts import ParticipantSubtitlePolicy
from .participant_subtitles import (
    export_participant_subtitles,
    load_participant_subtitles,
    validate_participant_subtitles,
)
from .speaker_transcript import load_speaker_labeled_transcript
from .subtitle_contracts import SubtitleExportPolicy, SubtitleFormat
from .transcript_contracts import TranscriptAssembly

PARTICIPANT_SUBTITLE_ACTIONS = {
    "participant-subtitle-export",
    "participant-subtitle-inspect",
    "participant-subtitle-list-cues",
    "participant-subtitle-validate",
}


def add_participant_subtitle_parsers(diasub) -> None:
    export = diasub.add_parser("participant-subtitle-export")
    export.add_argument("speaker_transcript_root", type=Path)
    export.add_argument("assembly_root", type=Path)
    export.add_argument("destination", type=Path)
    export.add_argument(
        "--format",
        choices=("webvtt", "srt"),
        action="append",
        default=[],
    )
    export.add_argument("--maximum-cue-duration-ms", type=int, default=7000)
    export.add_argument("--maximum-cue-characters", type=int, default=84)
    export.add_argument("--maximum-line-characters", type=int, default=42)
    export.add_argument("--maximum-lines", type=int, default=2)

    validate = diasub.add_parser("participant-subtitle-validate")
    validate.add_argument("participant_subtitle_root", type=Path)
    validate.add_argument("speaker_transcript_root", type=Path)
    validate.add_argument("assembly_root", type=Path)

    for action in (
        "participant-subtitle-inspect",
        "participant-subtitle-list-cues",
    ):
        parser = diasub.add_parser(action)
        parser.add_argument("participant_subtitle_root", type=Path)


def _load_sources(args):
    speaker_view, _ = load_speaker_labeled_transcript(
        args.speaker_transcript_root
    )
    assembly_root = args.assembly_root.expanduser().resolve(strict=True)
    assembly = load_contract(
        (assembly_root / "assembly.json").read_bytes(), TranscriptAssembly
    )
    return speaker_view, assembly


def run_participant_subtitle_command(args, emit, structured: bool):
    if args.action not in PARTICIPANT_SUBTITLE_ACTIONS:
        return None
    if args.action in {
        "participant-subtitle-inspect",
        "participant-subtitle-list-cues",
    }:
        manifest, report = load_participant_subtitles(
            args.participant_subtitle_root
        )
        if args.action == "participant-subtitle-list-cues":
            emit(manifest.cues, structured)
        else:
            emit(
                {
                    "manifest": manifest.model_dump(mode="json"),
                    "report": report.model_dump(mode="json"),
                },
                structured,
            )
        return 0

    speaker_view, assembly = _load_sources(args)
    if args.action == "participant-subtitle-validate":
        manifest, report = load_participant_subtitles(
            args.participant_subtitle_root
        )
        validate_participant_subtitles(
            manifest,
            args.participant_subtitle_root,
            speaker_view,
            assembly,
            report=report,
        )
        emit({"valid": True, "export_id": manifest.export_id}, structured)
        return 0

    source_roots = (
        args.speaker_transcript_root.expanduser().resolve(strict=True),
        args.assembly_root.expanduser().resolve(strict=True),
    )
    destination = args.destination.expanduser().resolve()
    if any(
        destination == root or root in destination.parents
        for root in source_roots
    ):
        raise ValueError(
            "participant subtitle output must not modify source evidence"
        )
    formats = tuple(
        SubtitleFormat(item)
        for item in (args.format or ("webvtt", "srt"))
    )
    policy = ParticipantSubtitlePolicy(
        subtitle_policy=SubtitleExportPolicy(
            formats=formats,
            maximum_cue_duration_microseconds=(
                args.maximum_cue_duration_ms * 1000
            ),
            maximum_cue_characters=args.maximum_cue_characters,
            maximum_line_characters=args.maximum_line_characters,
            maximum_lines_per_cue=args.maximum_lines,
        )
    )
    result = export_participant_subtitles(
        speaker_view,
        assembly,
        destination,
        policy=policy,
    )
    emit(
        {
            "manifest": result[0].model_dump(mode="json"),
            "report": result[1].model_dump(mode="json"),
            "participant_subtitle_root": str(result[2]),
            "reused": result[3],
        },
        structured,
    )
    return 0
