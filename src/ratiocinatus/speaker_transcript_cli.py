"""CLI integration for speaker-labeled transcript presentation views."""

from __future__ import annotations

from pathlib import Path

from .correction_contracts import TranscriptRevision, TranscriptViewKind
from .identity_view import load_identity_view_assembly
from .kernel import load_contract
from .phase3_contracts import DiarizationRun
from .speaker_transcript import (
    build_speaker_labeled_transcript,
    load_speaker_labeled_transcript,
    persist_speaker_labeled_transcript,
    validate_speaker_labeled_transcript,
)
from .speaker_transcript_contracts import SpeakerLabeledTranscriptPolicy
from .transcript_contracts import TranscriptAssembly

SPEAKER_TRANSCRIPT_ACTIONS = {
    "speaker-transcript-render",
    "speaker-transcript-inspect",
    "speaker-transcript-list-spans",
    "speaker-transcript-validate",
}


def add_speaker_transcript_parsers(diasub) -> None:
    render = diasub.add_parser("speaker-transcript-render")
    render.add_argument("assembly_root", type=Path)
    render.add_argument("diarization_root", type=Path)
    render.add_argument("identity_view_root", type=Path)
    render.add_argument("destination", type=Path)
    render.add_argument("--revision-root", type=Path)
    render.add_argument(
        "--transcript-view",
        choices=("original_machine", "current_corrected"),
        default="original_machine",
    )

    validate = diasub.add_parser("speaker-transcript-validate")
    validate.add_argument("speaker_transcript_root", type=Path)
    validate.add_argument("assembly_root", type=Path)
    validate.add_argument("diarization_root", type=Path)
    validate.add_argument("identity_view_root", type=Path)
    validate.add_argument("--revision-root", type=Path)

    for action in (
        "speaker-transcript-inspect",
        "speaker-transcript-list-spans",
    ):
        parser = diasub.add_parser(action)
        parser.add_argument("speaker_transcript_root", type=Path)


def _load_lineage(args):
    assembly_root = args.assembly_root.expanduser().resolve(strict=True)
    diarization_root = args.diarization_root.expanduser().resolve(strict=True)
    assembly = load_contract(
        (assembly_root / "assembly.json").read_bytes(), TranscriptAssembly
    )
    diarization = load_contract(
        (diarization_root / "run.json").read_bytes(), DiarizationRun
    )
    identity_assembly, _ = load_identity_view_assembly(
        args.identity_view_root
    )
    revision = (
        load_contract(
            (
                args.revision_root.expanduser().resolve(strict=True)
                / "revision.json"
            ).read_bytes(),
            TranscriptRevision,
        )
        if args.revision_root is not None
        else None
    )
    return assembly, diarization, identity_assembly, revision


def run_speaker_transcript_command(args, emit, structured: bool):
    if args.action not in SPEAKER_TRANSCRIPT_ACTIONS:
        return None
    if args.action in {
        "speaker-transcript-inspect",
        "speaker-transcript-list-spans",
    }:
        view, report = load_speaker_labeled_transcript(
            args.speaker_transcript_root
        )
        if args.action == "speaker-transcript-list-spans":
            emit(
                tuple(
                    span
                    for segment in view.segments
                    for span in segment.attribution_spans
                ),
                structured,
            )
        else:
            emit(
                {
                    "view": view.model_dump(mode="json"),
                    "report": report.model_dump(mode="json"),
                },
                structured,
            )
        return 0

    assembly, diarization, identity_assembly, revision = _load_lineage(args)
    if args.action == "speaker-transcript-validate":
        view, report = load_speaker_labeled_transcript(
            args.speaker_transcript_root
        )
        validate_speaker_labeled_transcript(
            view,
            assembly,
            diarization,
            identity_assembly,
            revision=revision,
            report=report,
        )
        emit({"valid": True, "view_id": view.view_id}, structured)
        return 0

    protected = tuple(
        path.expanduser().resolve(strict=True)
        for path in (
            args.assembly_root,
            args.diarization_root,
            args.identity_view_root,
        )
    )
    destination = args.destination.expanduser().resolve()
    if any(
        destination == root or root in destination.parents
        for root in protected
    ):
        raise ValueError(
            "speaker transcript output must not modify source evidence"
        )
    policy = SpeakerLabeledTranscriptPolicy(
        transcript_view_kind=TranscriptViewKind(args.transcript_view)
    )
    view = build_speaker_labeled_transcript(
        assembly,
        diarization,
        identity_assembly,
        revision=revision,
        policy=policy,
    )
    persisted = persist_speaker_labeled_transcript(
        view,
        assembly,
        diarization,
        identity_assembly,
        destination,
        revision=revision,
    )
    emit(
        {
            "view": persisted[0].model_dump(mode="json"),
            "report": persisted[1].model_dump(mode="json"),
            "speaker_transcript_root": str(persisted[2]),
            "reused": persisted[3],
        },
        structured,
    )
    return 0
