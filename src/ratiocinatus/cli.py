"""Stable Phase 0 command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from .contracts import Capability, OperationRequest, OperationResult, ProvenanceRecord
from .media import MediaInspectionError, ToolUnavailableError
from .normalization import AudioNormalizationError
from .packets import PacketContinuityError
from .clustering import ClusteringIntegrityError, ClusteringUnavailable
from .clustering_evaluation import ClusteringEvaluationIntegrityError
from .diarization_evaluation import DiarizationEvaluationIntegrityError
from .identity import IdentityFoundationIntegrityError
from .identity_binding import IdentityBindingIntegrityError
from .identity_view import IdentityViewIntegrityError
from .speaker_transcript import SpeakerTranscriptIntegrityError
from .participant_subtitles import ParticipantSubtitleIntegrityError
from .reference_enrollment import ReferenceEnrollmentIntegrityError
from .reference_comparison import ReferenceComparisonIntegrityError
from .diarization import DiarizationIntegrityError
from .diarization_providers import DiarizationProviderUnavailable
from .speech_providers import SpeechProviderUnavailable
from .speech_activity import SpeechActivityIntegrityError
from .transcription import TranscriptionIntegrityError
from .transcript_assembly import TranscriptAssemblyIntegrityError
from .corrections import TranscriptCorrectionIntegrityError
from .subtitles import SubtitleExportIntegrityError
from .transcript_evaluation import TranscriptEvaluationIntegrityError
from .recovery import Phase2RecoveryError
from .phase3_recovery import Phase3RecoveryError
from .phase3_completion import Phase3CompletionIntegrityError
from .phase4_completion import Phase4CompletionIntegrityError
from .discourse_providers import DiscourseProviderUnavailable
from .discourse_baseline import DeterministicDiscourseIntegrityError
from .discourse_provider_analysis import ProviderDiscourseIntegrityError
from .discourse_consolidation import DiscourseConsolidationIntegrityError
from .question_answer_construction import QuestionAnswerIntegrityError
from .argument_relation_construction import ArgumentRelationIntegrityError
from .lexical_example_quotation_construction import LexicalConstructionIntegrityError
from .procedural_state_construction import ProceduralStateIntegrityError
from .materialization import ChunkMaterializationError
from .video import VideoAccessError
from .corpus_contracts import IngestionStage
from .ingestion import IngestionInterrupted
from .kernel import (
    FixedClock, MalformedProviderOutput, ProviderError, ProviderRegistry,
    RatiocinatusError, SystemClock, Workspace, canonical_bytes,
    canonical_hash, export_schemas, load_contract, resolve_configuration,
)
from .version import (
    __version__, CONTRACT_VERSION, REPORT_VERSION, SERIALIZATION_VERSION,
    WORKSPACE_VERSION,
)

EXIT_SUCCESS = 0
EXIT_INVALID = 2
EXIT_MISSING = 3
EXIT_UNAVAILABLE = 4
EXIT_INTEGRITY = 5
EXIT_INTERNAL = 10


def _clock(deterministic: bool):
    return (
        FixedClock(datetime(2000, 1, 1, tzinfo=timezone.utc))
        if deterministic else SystemClock()
    )


def _plain(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, tuple):
        return [_plain(v) for v in value]
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def _emit(value: Any, structured: bool) -> None:
    if structured:
        print(json.dumps(_plain(value), sort_keys=True, indent=2))
    elif isinstance(value, BaseModel):
        for key, item in value.model_dump(mode="json").items():
            print(f"{key}: {item}")
    elif isinstance(value, (list, tuple)):
        if not value:
            print("(none)")
        for item in value:
            if isinstance(item, BaseModel):
                identity = next(
                    (getattr(item, key) for key in (
                        "source_id", "artifact_id", "provider_id", "operation_id",
                        "provenance_id", "report_id",
                    ) if hasattr(item, key)), None,
                )
                print(identity or str(item))
            else:
                print(item)
    else:
        print(value)


def _error(exc: Exception, kind: str, structured: bool) -> None:
    if structured:
        print(
            json.dumps(
                {"error": kind, "message": str(exc)},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
    else:
        print(f"{kind}: {exc}", file=sys.stderr)


def _find_operation(workspace: Workspace, operation_id: str) -> dict[str, Any]:
    requests = workspace._records("operations/requests.jsonl", OperationRequest)
    results = workspace._records("operations/results.jsonl", OperationResult)
    provenance = workspace._records("provenance/records.jsonl", ProvenanceRecord)
    return {
        "request": next((r.model_dump(mode="json") for r in requests if r.operation_id == operation_id), None),
        "result": next((r.model_dump(mode="json") for r in results if r.operation_id == operation_id), None),
        "provenance": [p.model_dump(mode="json") for p in provenance if p.operation_id == operation_id],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ratiocinatus")
    parser.add_argument("--json", action="store_true", help="structured JSON output")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("version")
    schemas = sub.add_parser("schema-export")
    schemas.add_argument("destination", type=Path)

    workspace = sub.add_parser("workspace")
    wsub = workspace.add_subparsers(dest="action", required=True)
    for action in ("inspect", "validate"):
        p = wsub.add_parser(action); p.add_argument("workspace", type=Path)
    p = wsub.add_parser("init"); p.add_argument("workspace", type=Path)
    p.add_argument("--deterministic", action="store_true")
    p.add_argument("--copy-sources", action="store_true")
    p = wsub.add_parser("export"); p.add_argument("workspace", type=Path); p.add_argument("destination", type=Path)

    source = sub.add_parser("source")
    ssub = source.add_subparsers(dest="action", required=True)
    p = ssub.add_parser("register"); p.add_argument("workspace", type=Path); p.add_argument("source", type=Path)
    p = ssub.add_parser("list"); p.add_argument("workspace", type=Path)
    p = ssub.add_parser("verify"); p.add_argument("workspace", type=Path); p.add_argument("source_id")

    artifact = sub.add_parser("artifact")
    asub = artifact.add_subparsers(dest="action", required=True)
    p = asub.add_parser("list"); p.add_argument("workspace", type=Path)
    p = asub.add_parser("inspect"); p.add_argument("workspace", type=Path); p.add_argument("artifact_id")

    provider = sub.add_parser("provider")
    psub = provider.add_subparsers(dest="action", required=True)
    psub.add_parser("list")
    p = psub.add_parser("inspect"); p.add_argument("provider_id")
    p = psub.add_parser("invoke"); p.add_argument("workspace", type=Path)
    p.add_argument("provider_id"); p.add_argument("capability", choices=[c.value for c in Capability])
    p.add_argument("input"); p.add_argument("--mode", choices=["success", "failure", "malformed"], default="success")

    speech_provider = sub.add_parser("speech-provider")
    spsub = speech_provider.add_subparsers(dest="action", required=True)
    p = spsub.add_parser("list")
    p.add_argument(
        "--capability", choices=("speech_activity", "transcription")
    )
    p = spsub.add_parser("inspect")
    p.add_argument("provider_id")
    diarization_provider = sub.add_parser("diarization-provider")
    dpsub = diarization_provider.add_subparsers(
        dest="action", required=True
    )
    dpsub.add_parser("list")
    p = dpsub.add_parser("inspect")
    p.add_argument("provider_id")
    diarization = sub.add_parser("diarization")
    diasub = diarization.add_subparsers(dest="action", required=True)
    from .comparison_hypothesis_cli import add_comparison_hypothesis_parser
    from .identity_binding_cli import add_identity_binding_parsers
    from .identity_view_cli import add_identity_view_parsers
    from .speaker_transcript_cli import add_speaker_transcript_parsers
    from .participant_subtitle_cli import add_participant_subtitle_parsers
    from .reference_comparison_cli import add_reference_comparison_parsers
    from .reference_enrollment_cli import (
        add_reference_enrollment_parsers,
    )
    from .diarization_evaluation_cli import (
        add_diarization_evaluation_parsers,
    )
    add_comparison_hypothesis_parser(diasub)
    add_identity_binding_parsers(diasub)
    add_identity_view_parsers(diasub)
    add_speaker_transcript_parsers(diasub)
    add_participant_subtitle_parsers(diasub)
    add_reference_comparison_parsers(diasub)
    add_reference_enrollment_parsers(diasub)
    add_diarization_evaluation_parsers(diasub)
    p = diasub.add_parser("run")
    p.add_argument("corpus", type=Path)
    p.add_argument("activity_run_root", type=Path)
    p.add_argument("destination", type=Path)
    p.add_argument("--provider", default="unconfigured.diarization")
    p.add_argument("--speech-interval", action="append", default=[])
    p.add_argument("--transcript-assembly-root", type=Path)
    p.add_argument("--minimum-speakers", type=int)
    p.add_argument("--maximum-speakers", type=int)
    p.add_argument("--boundary-uncertainty-ms", type=int, default=50)
    p.add_argument("--boundary-review-threshold", type=float, default=0.5)
    p.add_argument("--boundary-competition-ms", type=int, default=100)
    p.add_argument("--timeout", type=int, default=600)
    p = diasub.add_parser("cluster")
    p.add_argument("diarization_root", type=Path)
    p.add_argument("destination", type=Path)
    p.add_argument("--provider", default="unconfigured.diarization")
    p.add_argument("--minimum-observation-ms", type=int, default=500)
    p = diasub.add_parser("inspect-clustering")
    p.add_argument("clustering_root", type=Path)
    p = diasub.add_parser("validate-clustering")
    p.add_argument("clustering_root", type=Path)
    p.add_argument("diarization_root", type=Path)
    for action in ("list-clusters", "list-cluster-consistency"):
        p = diasub.add_parser(action)
        p.add_argument("clustering_root", type=Path)
    p = diasub.add_parser("evaluate-clustering")
    p.add_argument("clustering_root", type=Path)
    p.add_argument("diarization_root", type=Path)
    p.add_argument("reference", type=Path)
    p.add_argument("destination", type=Path)
    p = diasub.add_parser("inspect-clustering-evaluation")
    p.add_argument("evaluation_root", type=Path)
    p = diasub.add_parser("validate-clustering-evaluation")
    p.add_argument("evaluation_root", type=Path)
    p.add_argument("clustering_root", type=Path)
    p.add_argument("diarization_root", type=Path)
    p = diasub.add_parser("identity-create")
    p.add_argument("clustering_root", type=Path)
    p.add_argument("diarization_root", type=Path)
    p.add_argument("destination", type=Path)
    p.add_argument("--predecessor", type=Path)
    p.add_argument("--label", required=True)
    p.add_argument("--alternate-label", action="append", default=[])
    p.add_argument("--kind", required=True)
    p.add_argument("--information-source", required=True)
    p.add_argument("--scope-kind", required=True)
    p.add_argument("--scope-target", required=True)
    p.add_argument("--scope-explanation", required=True)
    p.add_argument("--provenance", action="append", required=True)
    p = diasub.add_parser("identity-propose")
    p.add_argument("foundation_root", type=Path)
    p.add_argument("clustering_root", type=Path)
    p.add_argument("diarization_root", type=Path)
    p.add_argument("destination", type=Path)
    p.add_argument("--target", required=True)
    p.add_argument("--identity", required=True)
    p.add_argument("--source", required=True)
    p.add_argument("--scope-kind", required=True)
    p.add_argument("--scope-target", required=True)
    p.add_argument("--scope-explanation", required=True)
    p.add_argument("--supporting", action="append", required=True)
    p.add_argument("--contrary", action="append", default=[])
    p.add_argument("--creation-process", required=True)
    p = diasub.add_parser("identity-validate")
    p.add_argument("foundation_root", type=Path)
    p.add_argument("clustering_root", type=Path)
    p.add_argument("diarization_root", type=Path)
    p.add_argument("--predecessor", type=Path)
    for action in (
        "identity-inspect",
        "identity-list",
        "identity-list-hypotheses",
        "identity-list-conflicts",
    ):
        p = diasub.add_parser(action)
        p.add_argument("foundation_root", type=Path)
    p = diasub.add_parser("inspect")
    p.add_argument("run_root", type=Path)
    p = diasub.add_parser("validate")
    p.add_argument("run_root", type=Path)
    for action in ("list-turns", "list-boundaries", "list-overlaps"):
        p = diasub.add_parser(action)
        p.add_argument("run_root", type=Path)
    speech = sub.add_parser("speech")
    speech_sub = speech.add_subparsers(dest="action", required=True)
    p = speech_sub.add_parser("detect")
    p.add_argument("corpus", type=Path)
    p.add_argument("destination", type=Path)
    p.add_argument(
        "--provider", default="local.ffmpeg_energy_activity"
    )
    p.add_argument("--speech-threshold", type=float, default=0.65)
    p.add_argument("--non-speech-threshold", type=float, default=0.35)
    p.add_argument("--timeout", type=int, default=120)
    p = speech_sub.add_parser("inspect")
    p.add_argument("run_root", type=Path)
    p = speech_sub.add_parser("evaluate-activity")
    p.add_argument("run_root", type=Path)
    p.add_argument("schedule", type=Path)
    p.add_argument("variant")
    p.add_argument("--output", type=Path)
    p = speech_sub.add_parser("transcribe")
    p.add_argument("corpus", type=Path)
    p.add_argument("activity_run_root", type=Path)
    p.add_argument("destination", type=Path)
    p.add_argument("--provider", default="local.openai_whisper")
    p.add_argument("--language")
    p.add_argument("--speech-interval", action="append", default=[])
    p.add_argument("--segment-only", action="store_true")
    p.add_argument("--maximum-segment-ms", type=int, default=30000)
    p.add_argument("--merge-gap-ms", type=int, default=300)
    p.add_argument("--minimum-clip-ms", type=int, default=200)
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--no-retain-raw", action="store_true")
    p = speech_sub.add_parser("inspect-transcription")
    p.add_argument("run_root", type=Path)
    p = speech_sub.add_parser("assemble")
    p.add_argument("corpus", type=Path)
    p.add_argument("transcription_run_root", type=Path)
    p.add_argument("destination", type=Path)
    p.add_argument("--minimum-speech-confidence", type=float, default=0.50)
    p.add_argument("--minimum-text-confidence", type=float, default=0.50)
    p.add_argument("--minimum-word-confidence", type=float, default=0.50)
    p.add_argument("--minimum-timing-confidence", type=float, default=0.50)
    p.add_argument("--minimum-boundary-confidence", type=float, default=0.50)
    p.add_argument("--block-low-text-confidence", action="store_true")
    p.add_argument("--block-unavailable-text-confidence", action="store_true")
    p = speech_sub.add_parser("inspect-assembly")
    p.add_argument("assembly_root", type=Path)
    p = speech_sub.add_parser("correct")
    p.add_argument("assembly_root", type=Path)
    p.add_argument("correction_batch", type=Path)
    p.add_argument("destination", type=Path)
    p = speech_sub.add_parser("inspect-revision")
    p.add_argument("revision_root", type=Path)
    p = speech_sub.add_parser("render-transcript")
    p.add_argument("revision_root", type=Path)
    p.add_argument(
        "--view",
        choices=("original", "current", "difference", "history"),
        default="current",
    )
    p.add_argument("--output", type=Path)
    p = speech_sub.add_parser("correction-history")
    p.add_argument("revision_root", type=Path)
    p = speech_sub.add_parser("export-subtitles")
    p.add_argument("assembly_root", type=Path)
    p.add_argument("destination", type=Path)
    p.add_argument("--revision-root", type=Path)
    p.add_argument("--view", choices=("original", "current"), default="original")
    p.add_argument("--format", choices=("webvtt", "srt"), action="append", default=[])
    p.add_argument("--maximum-cue-duration-ms", type=int, default=7000)
    p.add_argument("--maximum-cue-characters", type=int, default=84)
    p.add_argument("--maximum-line-characters", type=int, default=42)
    p.add_argument("--maximum-lines", type=int, default=2)
    p = speech_sub.add_parser("inspect-subtitles")
    p.add_argument("export_root", type=Path)
    p = speech_sub.add_parser("validate-subtitles")
    p.add_argument("export_root", type=Path)
    p = speech_sub.add_parser("evaluate-transcript")
    p.add_argument("assembly_root", type=Path)
    p.add_argument("reference", type=Path)
    p.add_argument("destination", type=Path)
    p.add_argument("--revision-root", type=Path)
    p.add_argument("--view", choices=("original", "current"), default="original")
    p.add_argument("--subtitle-export-root", type=Path)
    p = speech_sub.add_parser("inspect-evaluation")
    p.add_argument("evaluation_root", type=Path)
    p = speech_sub.add_parser("validate-evaluation")
    p.add_argument("evaluation_root", type=Path)
    p = speech_sub.add_parser("repair-transcription-report")
    p.add_argument("run_root", type=Path)
    p = speech_sub.add_parser("inspect-recovery")
    p.add_argument("recovery_root", type=Path)
    p = speech_sub.add_parser("validate-recovery")
    p.add_argument("recovery_root", type=Path)
    operation = sub.add_parser("operation")
    osub = operation.add_subparsers(dest="action", required=True)
    p = osub.add_parser("inspect"); p.add_argument("workspace", type=Path); p.add_argument("operation_id")

    replay = sub.add_parser("replay")
    replay.add_argument("workspace", type=Path); replay.add_argument("operation_id")

    report = sub.add_parser("report")
    report.add_argument("workspace", type=Path)

    config = sub.add_parser("config")
    csub = config.add_subparsers(dest="action", required=True)
    p = csub.add_parser("inspect"); p.add_argument("workspace", type=Path)

    media = sub.add_parser("media")
    msub = media.add_subparsers(dest="action", required=True)
    for action in ("inspect", "streams", "select", "qualify", "packets", "timeline", "map-time"):
        p = msub.add_parser(action)
        p.add_argument("source", type=Path)
        p.add_argument("--ffprobe")
        p.add_argument("--timeout", type=int, default=60)
        if action in {"select", "qualify", "packets", "timeline", "map-time"}:
            p.add_argument("--audio-stream", type=int)
            p.add_argument("--video-stream", type=int)
            p.add_argument("--preferred-language", action="append", default=[])
            p.add_argument("--preferred-audio-layout", action="append", default=[])
            p.add_argument("--allow-no-audio", action="store_true")
        if action in {"qualify", "packets"}:
            p.add_argument("--probe-duration-ms", type=int, default=1000)
        if action == "qualify":
            p.add_argument("--ffmpeg")
            p.add_argument("--full-decode", action="store_true")
        if action == "map-time":
            p.add_argument("timestamp_microseconds", type=int)
            p.add_argument(
                "--from-domain", choices=("source_media", "normalized_corpus"),
                default="normalized_corpus",
            )
            p.add_argument("--clip", action="store_true")

    ingest = sub.add_parser("ingest")
    isub = ingest.add_subparsers(dest="action", required=True)
    p = isub.add_parser("plan")
    p.add_argument("source", type=Path)
    p.add_argument("--ffprobe")
    p.add_argument("--timeout", type=int, default=60)
    p.add_argument("--audio-stream", type=int)
    p.add_argument("--video-stream", type=int)
    p.add_argument("--target-seconds", type=int, default=600)
    p.add_argument("--overlap-seconds", type=int, default=5)
    p.add_argument("--minimum-seconds", type=int, default=30)
    p.add_argument("--maximum-seconds", type=int, default=900)
    for action in ("run", "resume"):
        p = isub.add_parser(action)
        p.add_argument("source", type=Path)
        p.add_argument("workspace", type=Path)
        p.add_argument("--ffprobe")
        p.add_argument("--ffmpeg")
        p.add_argument("--audio-stream", type=int)
        p.add_argument("--video-stream", type=int)
        p.add_argument("--sample-rate", type=int, default=16_000)
        p.add_argument("--interrupt-after", choices=[stage.value for stage in IngestionStage])
    for action in ("status", "validate"):
        p = isub.add_parser(action)
        p.add_argument("workspace", type=Path)
        p.add_argument("ingestion_id")

    derivative = sub.add_parser("derivative")
    dsub = derivative.add_subparsers(dest="action", required=True)
    p = dsub.add_parser("normalize-audio")
    p.add_argument("source", type=Path)
    p.add_argument("output_root", type=Path)
    p.add_argument("--ffprobe")
    p.add_argument("--ffmpeg")
    p.add_argument("--audio-stream", type=int)
    p.add_argument("--sample-rate", type=int, default=16_000)
    p.add_argument("--timeout", type=int, default=3600)
    p.add_argument("--invalid-cache-action", choices=("rebuild", "refuse"), default="rebuild")
    p.add_argument("--no-cache", action="store_true")
    p = dsub.add_parser("list")
    p.add_argument("output_root", type=Path)
    p = dsub.add_parser("inspect")
    p.add_argument("entry", type=Path)

    cache = sub.add_parser("cache")
    csub = cache.add_subparsers(dest="action", required=True)
    for action in ("inspect", "validate"):
        p = csub.add_parser(action)
        p.add_argument("output_root", type=Path)
        p.add_argument("--ffprobe")

    corpus = sub.add_parser("corpus")
    cosub = corpus.add_subparsers(dest="action", required=True)
    p = cosub.add_parser("list")
    p.add_argument("workspace", type=Path)
    for action in ("inspect", "validate"):
        p = cosub.add_parser(action)
        p.add_argument("corpus_root", type=Path)
    p = cosub.add_parser("export")
    p.add_argument("corpus_root", type=Path)
    p.add_argument("destination", type=Path)

    chunk = sub.add_parser("chunk")
    chsub = chunk.add_subparsers(dest="action", required=True)
    p = chsub.add_parser("list")
    p.add_argument("corpus_root", type=Path)
    p = chsub.add_parser("materialize")
    p.add_argument("corpus_root", type=Path)
    p.add_argument("ordinal", type=int)
    p.add_argument("output_root", type=Path)
    p.add_argument("--reason", choices=(
        "provider_required", "manual_export", "qualification"
    ), default="provider_required")
    p.add_argument("--ffprobe")
    p.add_argument("--ffmpeg")
    p.add_argument("--timeout", type=int, default=3600)
    p.add_argument(
        "--invalid-cache-action", choices=("rebuild", "refuse"), default="rebuild"
    )
    p.add_argument("--no-cache", action="store_true")

    video = sub.add_parser("video")
    vsub = video.add_subparsers(dest="action", required=True)
    for action in ("plan", "frame", "frames"):
        p = vsub.add_parser(action)
        p.add_argument("source", type=Path)
        p.add_argument("--ffprobe")
        p.add_argument("--ffmpeg")
        p.add_argument("--audio-stream", type=int)
        p.add_argument("--video-stream", type=int)
        p.add_argument("--timeout", type=int, default=120)
        if action == "frame":
            p.add_argument("timestamp_microseconds", type=int)
            p.add_argument("output", type=Path)
        if action == "frames":
            p.add_argument("start_microseconds", type=int)
            p.add_argument("duration_microseconds", type=int)
            p.add_argument("--max-frames", type=int, default=100_000)
    from .phase3_recovery_cli import add_phase3_recovery_parser

    add_phase3_recovery_parser(sub)
    from .phase3_completion_cli import add_phase3_completion_parser

    add_phase3_completion_parser(sub)
    from .phase4_completion_cli import add_phase4_completion_parser

    add_phase4_completion_parser(sub)
    from .phase5_completion_cli import add_phase5_completion_parsers

    add_phase5_completion_parsers(sub)
    from .discourse_cli import add_discourse_provider_parser

    add_discourse_provider_parser(sub)
    from .discourse_operations_cli import add_discourse_parser

    add_discourse_parser(sub)
    from .utterance_cli import add_utterance_parser

    add_utterance_parser(sub)
    return parser


def run(args: argparse.Namespace) -> int:
    structured = args.json
    registry = ProviderRegistry.with_mocks()
    if args.command == "version":
        _emit({
            "application": __version__, "contracts": CONTRACT_VERSION,
            "serialization": SERIALIZATION_VERSION,
            "workspace": WORKSPACE_VERSION, "reports": REPORT_VERSION,
        }, structured)
        return EXIT_SUCCESS
    if args.command == "schema-export":
        _emit([str(p) for p in export_schemas(args.destination)], structured)
        return EXIT_SUCCESS
    if args.command == "phase3-recovery":
        from .phase3_recovery_cli import run_phase3_recovery_command

        recovery_result = run_phase3_recovery_command(
            args, _emit, structured
        )
        assert recovery_result is not None
        return recovery_result
    if args.command == "phase3-report":
        from .phase3_completion_cli import run_phase3_completion_command

        completion_result = run_phase3_completion_command(
            args, _emit, structured
        )
        assert completion_result is not None
        return completion_result
    if args.command == "phase4-report":
        from .phase4_completion_cli import run_phase4_completion_command

        completion_result = run_phase4_completion_command(
            args, _emit, structured
        )
        assert completion_result is not None
        return completion_result
    if args.command in {"phase5-long", "phase5-report"}:
        from .phase5_completion_cli import run_phase5_completion_command

        completion_result = run_phase5_completion_command(
            args, _emit, structured
        )
        assert completion_result is not None
        return completion_result
    if args.command == "discourse-provider":
        from .discourse_cli import run_discourse_provider_command

        discourse_result = run_discourse_provider_command(
            args, _emit, structured
        )
        assert discourse_result is not None
        return discourse_result
    if args.command == "discourse":
        from .discourse_operations_cli import run_discourse_command

        discourse_result = run_discourse_command(args, _emit, structured)
        assert discourse_result is not None
        return discourse_result
    if args.command == "utterance":
        from .utterance_cli import run_utterance_command

        utterance_result = run_utterance_command(
            args, _emit, structured
        )
        assert utterance_result is not None
        return utterance_result
    if args.command == "diarization-provider":
        from .diarization_providers import DiarizationProviderRegistry
        diarization_registry = (
            DiarizationProviderRegistry.with_boundaries()
        )

        diarization_registry = DiarizationProviderRegistry.with_boundaries()
        if args.action == "list":
            _emit(diarization_registry.list(), structured)
        else:
            _emit(
                diarization_registry.get(args.provider_id).capabilities,
                structured,
            )
        return EXIT_SUCCESS
    if args.command == "diarization":
        from .diarization_evaluation_cli import (
            run_diarization_evaluation_command,
        )
        diarization_evaluation_result = run_diarization_evaluation_command(
            args, _emit, structured
        )
        if diarization_evaluation_result is not None:
            return diarization_evaluation_result

        from .participant_subtitle_cli import run_participant_subtitle_command
        subtitle_result = run_participant_subtitle_command(
            args, _emit, structured
        )
        if subtitle_result is not None:
            return subtitle_result

        from .speaker_transcript_cli import run_speaker_transcript_command
        transcript_result = run_speaker_transcript_command(
            args, _emit, structured
        )
        if transcript_result is not None:
            return transcript_result

        from .identity_view_cli import run_identity_view_command
        view_result = run_identity_view_command(args, _emit, structured)
        if view_result is not None:
            return view_result

        from .identity_binding_cli import run_identity_binding_command
        binding_result = run_identity_binding_command(
            args, _emit, structured
        )
        if binding_result is not None:
            return binding_result

        from .comparison_hypothesis_cli import (
            run_comparison_hypothesis_command,
        )
        hypothesis_result = run_comparison_hypothesis_command(
            args, _emit, structured
        )
        if hypothesis_result is not None:
            return hypothesis_result
        from .reference_comparison_cli import (
            run_reference_comparison_command,
        )
        comparison_result = run_reference_comparison_command(
            args, _emit, structured
        )
        if comparison_result is not None:
            return comparison_result
        from .reference_enrollment_cli import (
            run_reference_enrollment_command,
        )
        reference_result = run_reference_enrollment_command(
            args, _emit, structured
        )
        if reference_result is not None:
            return reference_result

        from .diarization import (
            diarize_corpus,
            validate_diarization_response,
            validate_diarization_run,
        )
        from .diarization_providers import DiarizationProviderRegistry
        diarization_registry = (
            DiarizationProviderRegistry.with_boundaries()
        )
        from .phase3_contracts import (
            DiarizationPolicy,
            DiarizationProviderResponse,
            DiarizationReport,
            DiarizationRequest,
            DiarizationRun,
        )

        if args.action in {
            "identity-create",
            "identity-propose",
            "identity-validate",
            "identity-inspect",
            "identity-list",
            "identity-list-hypotheses",
            "identity-list-conflicts",
        }:
            from .clustering_contracts import ClusteringRun
            from .identity import (
                add_identity_hypothesis,
                add_participant_identity,
                load_identity_foundation,
                persist_identity_foundation,
                validate_identity_foundation,
            )
            from .phase3_contracts import (
                IdentityHypothesisSource,
                IdentityKind,
                IdentityScope,
                IdentityScopeKind,
            )

            if args.action in {
                "identity-inspect",
                "identity-list",
                "identity-list-hypotheses",
                "identity-list-conflicts",
            }:
                foundation, identity_report = load_identity_foundation(
                    args.foundation_root
                )
                if args.action == "identity-list":
                    _emit(foundation.identities, structured)
                elif args.action == "identity-list-hypotheses":
                    _emit(foundation.hypotheses, structured)
                elif args.action == "identity-list-conflicts":
                    _emit(foundation.conflicts, structured)
                else:
                    _emit(
                        {
                            "foundation": foundation.model_dump(mode="json"),
                            "report": identity_report.model_dump(mode="json"),
                        },
                        structured,
                    )
                return EXIT_SUCCESS

            clustering_root = args.clustering_root.expanduser().resolve(
                strict=True
            )
            diarization_root = args.diarization_root.expanduser().resolve(
                strict=True
            )
            clustering = load_contract(
                (clustering_root / "clustering.json").read_bytes(),
                ClusteringRun,
            )
            diarization = load_contract(
                (diarization_root / "run.json").read_bytes(),
                DiarizationRun,
            )
            predecessor = None
            predecessor_path = getattr(args, "predecessor", None)
            if predecessor_path is not None:
                predecessor, _ = load_identity_foundation(predecessor_path)
            if args.action == "identity-validate":
                foundation, identity_report = load_identity_foundation(
                    args.foundation_root
                )
                validate_identity_foundation(
                    foundation,
                    clustering,
                    diarization,
                    predecessor=predecessor,
                    report=identity_report,
                )
                _emit(
                    {"valid": True, "foundation_id": foundation.foundation_id},
                    structured,
                )
                return EXIT_SUCCESS

            destination = args.destination.expanduser().resolve()
            if any(
                destination == root or root in destination.parents
                for root in (clustering_root, diarization_root)
            ):
                raise ValueError(
                    "identity output must not modify source evidence"
                )
            scope = IdentityScope(
                kind=IdentityScopeKind(args.scope_kind),
                target_id=args.scope_target,
                explanation=args.scope_explanation,
            )
            if args.action == "identity-create":
                foundation, identity = add_participant_identity(
                    clustering,
                    diarization,
                    canonical_display_label=args.label,
                    alternate_labels=tuple(args.alternate_label),
                    identity_kind=IdentityKind(args.kind),
                    information_source=args.information_source,
                    scope=scope,
                    provenance_references=tuple(args.provenance),
                    predecessor=predecessor,
                )
                persisted = persist_identity_foundation(
                    foundation,
                    clustering,
                    diarization,
                    destination,
                    predecessor=predecessor,
                )
                _emit(
                    {
                        "identity": identity.model_dump(mode="json"),
                        "foundation": persisted[0].model_dump(mode="json"),
                        "report": persisted[1].model_dump(mode="json"),
                        "foundation_root": str(persisted[2]),
                        "reused": persisted[3],
                    },
                    structured,
                )
                return EXIT_SUCCESS

            foundation, _ = load_identity_foundation(args.foundation_root)
            successor, hypothesis = add_identity_hypothesis(
                foundation,
                clustering,
                diarization,
                target_artifact_id=args.target,
                proposed_identity_id=args.identity,
                source=IdentityHypothesisSource(args.source),
                scope=scope,
                supporting_evidence_references=tuple(args.supporting),
                contrary_evidence_references=tuple(args.contrary),
                creation_process=args.creation_process,
            )
            persisted = persist_identity_foundation(
                successor,
                clustering,
                diarization,
                destination,
                predecessor=foundation,
            )
            _emit(
                {
                    "hypothesis": hypothesis.model_dump(mode="json"),
                    "foundation": persisted[0].model_dump(mode="json"),
                    "report": persisted[1].model_dump(mode="json"),
                    "foundation_root": str(persisted[2]),
                    "reused": persisted[3],
                },
                structured,
            )
            return EXIT_SUCCESS
        if args.action in {
            "evaluate-clustering",
            "inspect-clustering-evaluation",
            "validate-clustering-evaluation",
        }:
            from .clustering_evaluation import (
                evaluate_clustering_artifacts,
                validate_clustering_evaluation,
            )
            from .clustering_evaluation_contracts import (
                DiarizationEvaluation,
                DiarizationEvaluationReport,
            )
            from .clustering_contracts import ClusteringRun

            if args.action == "evaluate-clustering":
                evaluated = evaluate_clustering_artifacts(
                    args.clustering_root,
                    args.diarization_root,
                    args.reference,
                    args.destination,
                )
                _emit(
                    {
                        "evaluation": evaluated[0].model_dump(mode="json"),
                        "report": evaluated[1].model_dump(mode="json"),
                        "evaluation_root": str(evaluated[2]),
                        "reused": evaluated[3],
                    },
                    structured,
                )
                return EXIT_SUCCESS

            evaluation_root = args.evaluation_root.expanduser().resolve(
                strict=True
            )
            evaluation = load_contract(
                (evaluation_root / "evaluation.json").read_bytes(),
                DiarizationEvaluation,
            )
            report = load_contract(
                (evaluation_root / "report.json").read_bytes(),
                DiarizationEvaluationReport,
            )
            if args.action == "validate-clustering-evaluation":
                clustering_root = args.clustering_root.expanduser().resolve(
                    strict=True
                )
                diarization_root = args.diarization_root.expanduser().resolve(
                    strict=True
                )
                clustering = load_contract(
                    (clustering_root / "clustering.json").read_bytes(),
                    ClusteringRun,
                )
                diarization = load_contract(
                    (diarization_root / "run.json").read_bytes(),
                    DiarizationRun,
                )
                validate_clustering_evaluation(
                    evaluation, clustering, diarization, report
                )
                _emit(
                    {"valid": True, "evaluation_id": evaluation.evaluation_id},
                    structured,
                )
                return EXIT_SUCCESS
            _emit(
                {
                    "evaluation": evaluation.model_dump(mode="json"),
                    "report": report.model_dump(mode="json"),
                },
                structured,
            )
            return EXIT_SUCCESS
        if args.action in {
            "cluster",
            "inspect-clustering",
            "validate-clustering",
            "list-clusters",
            "list-cluster-consistency",
        }:
            from .clustering import cluster_diarization, validate_clustering_run
            from .clustering_contracts import (
                ClusteringPolicy,
                ClusteringReport,
                ClusteringRun,
            )

            if args.action == "cluster":
                clustering_provider = diarization_registry.get(args.provider)
                clustered = cluster_diarization(
                    args.diarization_root,
                    args.destination,
                    capabilities=clustering_provider.capabilities,
                    policy=ClusteringPolicy(
                        minimum_observation_microseconds=(
                            args.minimum_observation_ms * 1_000
                        )
                    ),
                )
                _emit(
                    {
                        "run": clustered[0].model_dump(mode="json"),
                        "report": clustered[1].model_dump(mode="json"),
                        "run_root": str(clustered[2]),
                        "reused": clustered[3],
                    },
                    structured,
                )
                return EXIT_SUCCESS

            clustering_root = args.clustering_root.expanduser().resolve(
                strict=True
            )
            clustered_run = load_contract(
                (clustering_root / "clustering.json").read_bytes(),
                ClusteringRun,
            )
            cluster_report = load_contract(
                (clustering_root / "report.json").read_bytes(),
                ClusteringReport,
            )
            if args.action == "validate-clustering":
                source_run = load_contract(
                    (
                        args.diarization_root.expanduser().resolve(strict=True)
                        / "run.json"
                    ).read_bytes(),
                    DiarizationRun,
                )
                validate_clustering_run(clustered_run, source_run)
                _emit({"valid": True, "run_id": clustered_run.run_id}, structured)
                return EXIT_SUCCESS
            if args.action == "list-clusters":
                _emit(clustered_run.clusters, structured)
                return EXIT_SUCCESS
            if args.action == "list-cluster-consistency":
                _emit(clustered_run.consistency_results, structured)
                return EXIT_SUCCESS
            _emit(
                {
                    "run": clustered_run.model_dump(mode="json"),
                    "report": cluster_report.model_dump(mode="json"),
                },
                structured,
            )
            return EXIT_SUCCESS

        if args.action == "run":
            provider = DiarizationProviderRegistry.with_boundaries().get(
                args.provider
            )
            result = diarize_corpus(
                args.corpus,
                args.activity_run_root,
                args.destination,
                provider=provider,
                policy=DiarizationPolicy(
                    minimum_speakers=args.minimum_speakers,
                    maximum_speakers=args.maximum_speakers,
                    boundary_uncertainty_microseconds=(
                        args.boundary_uncertainty_ms * 1_000
                    ),
                    boundary_review_confidence_threshold=(
                        args.boundary_review_threshold
                    ),
                    boundary_competition_window_microseconds=(
                        args.boundary_competition_ms * 1_000
                    ),

                    timeout_seconds=args.timeout,
                ),
                speech_interval_ids=tuple(args.speech_interval) or None,
                transcript_assembly_root=args.transcript_assembly_root,
            )
            _emit(
                {
                    "request": result[0].model_dump(mode="json"),
                    "run": result[2].model_dump(mode="json"),
                    "report": result[3].model_dump(mode="json"),
                    "run_root": str(result[4]),
                    "reused": result[5],
                },
                structured,
            )
            return EXIT_SUCCESS

        root = args.run_root.expanduser().resolve(strict=True)
        request = load_contract(
            (root / "request.json").read_bytes(), DiarizationRequest
        )
        response = load_contract(
            (root / "response.json").read_bytes(),
            DiarizationProviderResponse,
        )
        diarization_run = load_contract(
            (root / "run.json").read_bytes(), DiarizationRun
        )
        report = load_contract(
            (root / "report.json").read_bytes(), DiarizationReport
        )
        if args.action == "validate":
            validate_diarization_response(response, request, root)
            validate_diarization_run(diarization_run)
        listed = {
            "list-turns": diarization_run.turns,
            "list-boundaries": diarization_run.boundaries,
            "list-overlaps": diarization_run.overlaps,
        }
        if args.action in listed:
            _emit(listed[args.action], structured)
            return EXIT_SUCCESS
        _emit(
            {
                "request": request.model_dump(mode="json"),
                "response": response.model_dump(mode="json"),
                "run": diarization_run.model_dump(mode="json"),
                "report": report.model_dump(mode="json"),
                "valid": True if args.action == "validate" else None,
            },
            structured,
        )
        return EXIT_SUCCESS
    if args.command == "speech-provider":
        from .phase2_contracts import SpeechEvidenceCapability
        from .speech_providers import SpeechProviderRegistry

        speech_registry = SpeechProviderRegistry.with_boundaries()
        if args.action == "list":
            capability = (
                SpeechEvidenceCapability(args.capability)
                if args.capability
                else None
            )
            _emit(speech_registry.list(capability), structured)
        else:
            _emit(
                speech_registry.get(args.provider_id).capabilities,
                structured,
            )
        return EXIT_SUCCESS
    if args.command == "speech":
        from .phase2_contracts import (
            LanguageMode,
            SpeechActivityPolicy,
            SpeechActivityReport,
            SpeechActivityRun,
            TranscriptionPolicy,
            TranscriptionProviderResponse,
            TranscriptionReport,
            TranscriptionRequest,
            WordTimestampPolicy,
        )
        if args.action in {"inspect-recovery", "validate-recovery"}:
            from .recovery import validate_recovery_report
            from .recovery_contracts import Phase2RecoveryReport

            recovery = load_contract(
                (args.recovery_root / "report.json").read_bytes(),
                Phase2RecoveryReport,
            )
            validate_recovery_report(recovery, root=args.recovery_root)
            _emit(recovery, structured)
            return EXIT_SUCCESS if recovery.status == "passed" else EXIT_INTEGRITY
        if args.action == "repair-transcription-report":
            from .recovery import repair_transcription_report
            from .speech_providers import SpeechProviderRegistry

            request = load_contract(
                (args.run_root / "request.json").read_bytes(),
                TranscriptionRequest,
            )
            provider = SpeechProviderRegistry.with_boundaries().get(
                request.provider.provider_id
            )
            report, recovery = repair_transcription_report(
                args.run_root,
                provider,
                report_root=args.run_root.parents[1],
            )
            _emit(
                {
                    "report": report.model_dump(mode="json"),
                    "recovery": recovery.model_dump(mode="json"),
                },
                structured,
            )
            return EXIT_SUCCESS
        if args.action in {"inspect-evaluation", "validate-evaluation"}:
            from .evaluation_contracts import TranscriptEvaluationReport
            from .transcript_evaluation import validate_transcript_evaluation

            evaluation = load_contract(
                (args.evaluation_root / "report.json").read_bytes(),
                TranscriptEvaluationReport,
            )
            validate_transcript_evaluation(
                evaluation, root=args.evaluation_root
            )
            _emit(evaluation, structured)
            return EXIT_SUCCESS
        if args.action == "evaluate-transcript":
            from .correction_contracts import TranscriptViewKind
            from .transcript_evaluation import evaluate_transcript

            evaluation, root, reused = evaluate_transcript(
                args.assembly_root,
                args.reference,
                args.destination,
                revision_root=args.revision_root,
                view_kind=(
                    TranscriptViewKind.CURRENT_CORRECTED
                    if args.view == "current"
                    else TranscriptViewKind.ORIGINAL_MACHINE
                ),
                subtitle_export_root=args.subtitle_export_root,
            )
            _emit(
                {
                    "evaluation": evaluation.model_dump(mode="json"),
                    "root": str(root),
                    "reused": reused,
                },
                structured,
            )
            return EXIT_SUCCESS
        if args.action in {"inspect-subtitles", "validate-subtitles"}:
            from .subtitle_contracts import (
                SubtitleExportManifest,
                SubtitleValidationReport,
            )
            from .subtitles import validate_subtitle_export

            manifest = load_contract(
                (args.export_root / "manifest.json").read_bytes(),
                SubtitleExportManifest,
            )
            report = load_contract(
                (args.export_root / "validation-report.json").read_bytes(),
                SubtitleValidationReport,
            )
            validate_subtitle_export(
                manifest, args.export_root, report=report
            )
            _emit(
                report if args.action == "validate-subtitles" else {
                    "manifest": manifest.model_dump(mode="json"),
                    "report": report.model_dump(mode="json"),
                },
                structured,
            )
            return EXIT_SUCCESS if report.valid else EXIT_INTEGRITY
        if args.action == "export-subtitles":
            from .correction_contracts import TranscriptViewKind
            from .subtitle_contracts import SubtitleExportPolicy, SubtitleFormat
            from .subtitles import export_subtitles

            formats = tuple(
                SubtitleFormat(item) for item in args.format
            ) or (SubtitleFormat.WEBVTT, SubtitleFormat.SRT)
            manifest, report, root, reused = export_subtitles(
                args.assembly_root,
                args.destination,
                revision_root=args.revision_root,
                view_kind=(
                    TranscriptViewKind.CURRENT_CORRECTED
                    if args.view == "current"
                    else TranscriptViewKind.ORIGINAL_MACHINE
                ),
                policy=SubtitleExportPolicy(
                    formats=formats,
                    maximum_cue_duration_microseconds=(
                        args.maximum_cue_duration_ms * 1000
                    ),
                    maximum_cue_characters=args.maximum_cue_characters,
                    maximum_line_characters=args.maximum_line_characters,
                    maximum_lines_per_cue=args.maximum_lines,
                ),
            )
            _emit(
                {
                    "manifest": manifest.model_dump(mode="json"),
                    "report": report.model_dump(mode="json"),
                    "root": str(root),
                    "reused": reused,
                },
                structured,
            )
            return EXIT_SUCCESS if report.valid else EXIT_INTEGRITY
        if args.action in {
            "inspect-revision",
            "render-transcript",
            "correction-history",
        }:
            from .correction_contracts import (
                TranscriptRevision,
                TranscriptRevisionReport,
            )
            from .corrections import validate_transcript_revision

            revision = load_contract(
                (args.revision_root / "revision.json").read_bytes(),
                TranscriptRevision,
            )
            validate_transcript_revision(revision)
            if args.action == "inspect-revision":
                report = load_contract(
                    (args.revision_root / "report.json").read_bytes(),
                    TranscriptRevisionReport,
                )
                _emit(
                    {
                        "revision": revision.model_dump(mode="json"),
                        "report": report.model_dump(mode="json"),
                    },
                    structured,
                )
                return EXIT_SUCCESS
            if args.action == "correction-history":
                _emit(revision.correction_history, structured)
                return EXIT_SUCCESS
            rendered = {
                "original": revision.original_machine_view,
                "current": revision.current_corrected_view,
                "difference": revision.difference_report,
                "history": revision.correction_history,
            }[args.view]
            if args.output is not None:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_bytes(canonical_bytes(rendered))
            _emit(rendered, structured)
            return EXIT_SUCCESS
        if args.action == "correct":
            from .corrections import apply_correction_batch

            revision, report, root, reused = apply_correction_batch(
                args.assembly_root,
                args.correction_batch,
                args.destination,
            )
            _emit(
                {
                    "revision": revision.model_dump(mode="json"),
                    "report": report.model_dump(mode="json"),
                    "root": str(root),
                    "reused": reused,
                },
                structured,
            )
            return EXIT_SUCCESS
        if args.action == "inspect-assembly":
            from .transcript_contracts import (
                TranscriptAssembly,
                TranscriptAssemblyReport,
            )
            from .transcript_assembly import validate_transcript_assembly

            assembly = load_contract(
                (args.assembly_root / "assembly.json").read_bytes(),
                TranscriptAssembly,
            )
            report = load_contract(
                (args.assembly_root / "report.json").read_bytes(),
                TranscriptAssemblyReport,
            )
            validate_transcript_assembly(assembly)
            _emit(
                {
                    "assembly": assembly.model_dump(mode="json"),
                    "report": report.model_dump(mode="json"),
                },
                structured,
            )
            return EXIT_SUCCESS if report.status.value != "blocked" else EXIT_INTEGRITY
        if args.action == "assemble":
            from .transcript_assembly import assemble_transcript
            from .transcript_contracts import TranscriptAssemblyPolicy

            assembly, report, root, reused = assemble_transcript(
                args.corpus,
                args.transcription_run_root,
                args.destination,
                policy=TranscriptAssemblyPolicy(
                    minimum_speech_presence_confidence=(
                        args.minimum_speech_confidence
                    ),
                    minimum_text_confidence=args.minimum_text_confidence,
                    minimum_word_confidence=args.minimum_word_confidence,
                    minimum_timing_confidence=args.minimum_timing_confidence,
                    minimum_boundary_confidence=(
                        args.minimum_boundary_confidence
                    ),
                    block_low_text_confidence=(
                        args.block_low_text_confidence
                    ),
                    block_unavailable_text_confidence=(
                        args.block_unavailable_text_confidence
                    ),
                ),
            )
            _emit(
                {
                    "assembly": assembly.model_dump(mode="json"),
                    "report": report.model_dump(mode="json"),
                    "root": str(root),
                    "reused": reused,
                },
                structured,
            )
            return EXIT_SUCCESS if report.status.value != "blocked" else EXIT_INTEGRITY
        if args.action == "inspect-transcription":
            response = load_contract(
                (args.run_root / "response.json").read_bytes(),
                TranscriptionProviderResponse,
            )
            report = load_contract(
                (args.run_root / "report.json").read_bytes(),
                TranscriptionReport,
            )
            _emit(
                {
                    "response": response.model_dump(mode="json"),
                    "report": report.model_dump(mode="json"),
                },
                structured,
            )
            return EXIT_SUCCESS if response.complete else EXIT_UNAVAILABLE
        if args.action == "transcribe":
            from .speech_providers import SpeechProviderRegistry
            from .transcription import transcribe_corpus

            provider = SpeechProviderRegistry.with_boundaries().get(
                args.provider
            )
            request, response, report, root, reused = transcribe_corpus(
                args.corpus,
                args.activity_run_root,
                args.destination,
                provider=provider,
                policy=TranscriptionPolicy(
                    language_mode=(
                        LanguageMode.EXPLICIT
                        if args.language
                        else LanguageMode.AUTOMATIC_PROPOSAL
                    ),
                    language=args.language,
                    word_timestamps=(
                        WordTimestampPolicy.SEGMENT_ONLY
                        if args.segment_only
                        else WordTimestampPolicy.REQUEST_PROVIDER_NATIVE
                    ),
                    maximum_segment_microseconds=(
                        args.maximum_segment_ms * 1000
                    ),
                    merge_gap_microseconds=args.merge_gap_ms * 1000,
                    minimum_clip_microseconds=args.minimum_clip_ms * 1000,
                    decoding_temperature=args.temperature,

                    timeout_seconds=args.timeout,
                    retain_raw_evidence=not args.no_retain_raw,
                ),
                speech_interval_ids=(
                    tuple(args.speech_interval)
                    if args.speech_interval
                    else None
                ),
            )
            _emit(
                {
                    "request": request.model_dump(mode="json"),
                    "response": response.model_dump(mode="json"),
                    "report": report.model_dump(mode="json"),
                    "root": str(root),
                    "reused": reused,
                },
                structured,
            )
            return EXIT_SUCCESS if response.complete else EXIT_UNAVAILABLE
        if args.action in {"inspect", "evaluate-activity"}:
            run = load_contract(
                (args.run_root / "run.json").read_bytes(),
                SpeechActivityRun,
            )
            if args.action == "evaluate-activity":
                from .activity_evaluation import (
                    evaluate_speech_activity,
                    reference_from_line_schedule,
                )

                reference = reference_from_line_schedule(
                    args.schedule,
                    variant=args.variant,
                    normalized_audio_sha256=(
                        run.request.normalized_audio_sha256
                    ),
                    normalized_audio_duration_microseconds=(
                        run.request.normalized_audio_duration_microseconds
                    ),
                )
                evaluation = evaluate_speech_activity(run, reference)
                if args.output is not None:
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    args.output.write_bytes(canonical_bytes(evaluation))
                _emit(evaluation, structured)
                return EXIT_SUCCESS
            report = load_contract(
                (args.run_root / "report.json").read_bytes(),
                SpeechActivityReport,
            )
            _emit(
                {
                    "run": run.model_dump(mode="json"),
                    "report": report.model_dump(mode="json"),
                },
                structured,
            )
            return EXIT_SUCCESS if run.complete else EXIT_INTEGRITY
        from .speech_activity import detect_corpus_activity
        from .speech_providers import SpeechProviderRegistry

        provider = SpeechProviderRegistry.with_boundaries().get(args.provider)
        run, report, root, reused = detect_corpus_activity(
            args.corpus,
            args.destination,
            provider=provider,
            policy=SpeechActivityPolicy(
                speech_threshold=args.speech_threshold,
                non_speech_threshold=args.non_speech_threshold,
                timeout_seconds=args.timeout,
            ),
        )
        _emit(
            {
                "run": run.model_dump(mode="json"),
                "report": report.model_dump(mode="json"),
                "root": str(root),
                "reused": reused,
            },
            structured,
        )
        return EXIT_SUCCESS if run.complete else EXIT_INTEGRITY
    if args.command == "media":
        from .media import inspect_media

        inspection = inspect_media(
            args.source, ffprobe=args.ffprobe, timeout_seconds=args.timeout
        )
        if args.action in {"inspect", "streams"}:
            _emit(
                inspection if args.action == "inspect" else inspection.streams,
                structured,
            )
            return EXIT_SUCCESS
        from .selection import select_streams
        from .selection_contracts import StreamSelectionPolicy

        selection = select_streams(
            inspection,
            StreamSelectionPolicy(
                explicit_audio_stream_index=args.audio_stream,
                explicit_video_stream_index=args.video_stream,
                preferred_languages=tuple(args.preferred_language),
                preferred_audio_layouts=tuple(args.preferred_audio_layout),
                require_audio=not args.allow_no_audio,
            ),
        )
        if args.action == "select":
            _emit(selection, structured)
            return EXIT_SUCCESS if selection.valid else EXIT_INVALID
        if args.action == "packets":
            from .packet_contracts import PacketContinuityPolicy
            from .packets import qualify_packet_continuity

            result = qualify_packet_continuity(
                inspection,
                selection,
                policy=PacketContinuityPolicy(
                    probe_duration_microseconds=args.probe_duration_ms * 1000,

                    timeout_seconds=args.timeout,
                ),
                ffprobe=args.ffprobe,
            )
            _emit(result, structured)
            return EXIT_SUCCESS if result.valid else EXIT_INTEGRITY
        if args.action in {"timeline", "map-time"}:
            from .addressing import build_source_timeline, map_timestamp
            from .addressing_contracts import MediaTimestamp, TimeDomain

            timeline = build_source_timeline(inspection, selection)
            if args.action == "timeline":
                _emit(timeline, structured)
            else:
                _emit(
                    map_timestamp(
                        timeline,
                        MediaTimestamp(
                            domain=TimeDomain(args.from_domain),
                            microseconds=args.timestamp_microseconds,
                        ),
                        clip=args.clip,
                    ),
                    structured,
                )
            return EXIT_SUCCESS
        from .qualification import FFmpegDecodeQualificationProvider
        from .qualification_contracts import DecodeQualificationPolicy

        result = FFmpegDecodeQualificationProvider(args.ffmpeg).qualify(
            inspection,
            selection,
            DecodeQualificationPolicy(
                probe_duration_microseconds=args.probe_duration_ms * 1000,
                timeout_seconds=args.timeout,
                full_decode=args.full_decode,
            ),
        )
        _emit(result, structured)
        return EXIT_SUCCESS if result.valid else EXIT_INTEGRITY
    if args.command == "ingest" and args.action == "plan":
        from .addressing import build_source_timeline
        from .chunk_contracts import ChunkPolicy
        from .chunking import build_chunk_plan
        from .media import inspect_media
        from .selection import select_streams
        from .selection_contracts import StreamSelectionPolicy

        inspection = inspect_media(
            args.source, ffprobe=args.ffprobe, timeout_seconds=args.timeout
        )
        selection = select_streams(
            inspection,
            StreamSelectionPolicy(
                explicit_audio_stream_index=args.audio_stream,
                explicit_video_stream_index=args.video_stream,
            ),
        )
        timeline = build_source_timeline(inspection, selection)
        plan = build_chunk_plan(
            timeline,
            ChunkPolicy(
                target_duration_microseconds=args.target_seconds * 1_000_000,
                overlap_microseconds=args.overlap_seconds * 1_000_000,
                minimum_duration_microseconds=args.minimum_seconds * 1_000_000,
                maximum_duration_microseconds=args.maximum_seconds * 1_000_000,
            ),
        )
        _emit(plan, structured)
        return EXIT_SUCCESS
    if args.command == "ingest" and args.action in {"run", "resume"}:
        from .corpus_contracts import IngestionPolicy, IngestionStage
        from .ingestion import prepare_ingestion_request, run_ingestion
        from .normalization_contracts import AudioNormalizationPolicy
        from .selection_contracts import StreamSelectionPolicy

        policy = IngestionPolicy(
            selection=StreamSelectionPolicy(
                explicit_audio_stream_index=args.audio_stream,
                explicit_video_stream_index=args.video_stream,
            ),
            audio=AudioNormalizationPolicy(sample_rate=args.sample_rate),
        )
        request = prepare_ingestion_request(
            args.source,
            args.workspace,
            policy=policy,
            ffprobe=args.ffprobe,
            ffmpeg=args.ffmpeg,
        )
        manifest = run_ingestion(
            request,
            interrupt_after=(
                IngestionStage(args.interrupt_after)
                if args.interrupt_after
                else None
            ),
        )
        _emit(manifest, structured)
        return EXIT_SUCCESS
    if args.command == "ingest" and args.action in {"status", "validate"}:
        from .corpus import validate_corpus
        from .corpus_contracts import IngestionManifest

        root = args.workspace.resolve() / "ingestions" / args.ingestion_id
        if args.action == "status":
            _emit(
                load_contract((root / "manifest.json").read_bytes(), IngestionManifest),
                structured,
            )
            return EXIT_SUCCESS
        report = validate_corpus(root / "corpus")
        _emit(report, structured)
        return EXIT_SUCCESS if report.valid else EXIT_INTEGRITY
    if args.command == "corpus":
        from .corpus import export_corpus, load_corpus, validate_corpus

        if args.action == "list":
            roots = sorted(args.workspace.resolve().glob("ingestions/*/corpus/manifest.json"))
            _emit([str(path.parent) for path in roots], structured)
            return EXIT_SUCCESS
        if args.action == "inspect":
            _emit(load_corpus(args.corpus_root)["corpus"], structured)
            return EXIT_SUCCESS
        if args.action == "validate":
            report = validate_corpus(args.corpus_root)
            _emit(report, structured)
            return EXIT_SUCCESS if report.valid else EXIT_INTEGRITY
        _emit(str(export_corpus(args.corpus_root, args.destination)), structured)
        return EXIT_SUCCESS
    if args.command == "chunk":
        from .corpus import load_corpus
        from .materialization import materialize_audio_chunk
        from .materialization_contracts import ChunkMaterializationPolicy

        loaded = load_corpus(args.corpus_root)
        chunks = loaded["chunks"].chunks
        if args.action == "list":
            _emit(chunks, structured)
            return EXIT_SUCCESS
        if args.ordinal < 0 or args.ordinal >= len(chunks):
            raise ValueError(
                f"chunk ordinal {args.ordinal} is outside 0..{len(chunks) - 1}"
            )
        result = materialize_audio_chunk(
            chunks[args.ordinal],
            loaded["audio"],
            loaded["audio_path"],
            args.output_root,
            reason=args.reason,
            policy=ChunkMaterializationPolicy(
                timeout_seconds=args.timeout,
                invalid_cache_action=args.invalid_cache_action,
            ),
            ffmpeg=args.ffmpeg,
            ffprobe=args.ffprobe,
            use_cache=not args.no_cache,
        )
        _emit(result, structured)
        return EXIT_SUCCESS
    if args.command == "derivative":
        from .cache import list_derivatives, load_cache_entry

        if args.action == "list":
            _emit(list_derivatives(args.output_root), structured)
            return EXIT_SUCCESS
        if args.action == "inspect":
            _emit(load_cache_entry(args.entry), structured)
            return EXIT_SUCCESS
        from .media import inspect_media
        from .normalization import normalize_audio
        from .normalization_contracts import AudioNormalizationPolicy
        from .selection import select_streams
        from .selection_contracts import StreamSelectionPolicy

        inspection = inspect_media(
            args.source, ffprobe=args.ffprobe, timeout_seconds=min(args.timeout, 3600)
        )
        selection = select_streams(
            inspection,
            StreamSelectionPolicy(
                explicit_audio_stream_index=args.audio_stream,
            ),
        )
        result = normalize_audio(
            inspection,
            selection,
            args.output_root,
            policy=AudioNormalizationPolicy(
                sample_rate=args.sample_rate,
                timeout_seconds=args.timeout,
                invalid_cache_action=args.invalid_cache_action,
            ),
            ffmpeg=args.ffmpeg,
            ffprobe=args.ffprobe,
            use_cache=not args.no_cache,
        )
        _emit(result, structured)
        return EXIT_SUCCESS
    if args.command == "cache":
        from .cache import list_derivatives, validate_cache

        result = (
            list_derivatives(args.output_root)
            if args.action == "inspect"
            else validate_cache(args.output_root, args.ffprobe)
        )
        _emit(result, structured)
        if args.action == "validate" and any(not item["valid"] for item in result):
            return EXIT_INTEGRITY
        return EXIT_SUCCESS
    if args.command == "video":
        from .addressing_contracts import MediaInterval, TimeDomain
        from .media import inspect_media
        from .qualification import FFmpegDecodeQualificationProvider
        from .qualification_contracts import DecodeQualificationPolicy
        from .selection import select_streams
        from .selection_contracts import StreamSelectionPolicy
        from .video import create_video_access_plan, extract_frame, frames_over_interval
        from .video_contracts import VideoNormalizationPolicy

        inspection = inspect_media(
            args.source, ffprobe=args.ffprobe, timeout_seconds=args.timeout
        )
        selection = select_streams(
            inspection,
            StreamSelectionPolicy(
                explicit_audio_stream_index=args.audio_stream,
                explicit_video_stream_index=args.video_stream,
            ),
        )
        qualification = FFmpegDecodeQualificationProvider(args.ffmpeg).qualify(
            inspection,
            selection,
            DecodeQualificationPolicy(timeout_seconds=args.timeout),
        )
        plan = create_video_access_plan(
            inspection,
            selection,
            qualification,
            VideoNormalizationPolicy(timeout_seconds=args.timeout),
        )
        if args.action == "plan":
            _emit(plan, structured)
            return EXIT_SUCCESS
        if args.action == "frame":
            result = extract_frame(
                plan,
                args.timestamp_microseconds,
                args.output,
                ffmpeg=args.ffmpeg,
                ffprobe=args.ffprobe,
            )
        else:
            result = frames_over_interval(
                plan,
                MediaInterval(
                    domain=TimeDomain.NORMALIZED_CORPUS,
                    start_microseconds=args.start_microseconds,
                    duration_microseconds=args.duration_microseconds,
                ),
                ffprobe=args.ffprobe,
                max_frames=args.max_frames,
            )
        _emit(result, structured)
        return EXIT_SUCCESS
    if args.command == "workspace" and args.action == "init":
        config = resolve_configuration(
            str(args.workspace),
            cli_values={"deterministic": args.deterministic, "copy_sources": args.copy_sources},
        )
        result = Workspace.initialize(args.workspace, config, _clock(args.deterministic))
        _emit(result.manifest, structured); return EXIT_SUCCESS
    if args.command == "provider" and args.action in {"list", "inspect"}:
        if args.action == "list":
            _emit(registry.list(), structured)
        else:
            _emit(registry.get(args.provider_id).descriptor, structured)
        return EXIT_SUCCESS

    workspace_path = getattr(args, "workspace", None)
    workspace = Workspace.open(workspace_path)
    clock = _clock(workspace.config.deterministic)
    if args.command == "workspace":
        if args.action == "inspect": _emit(workspace.manifest, structured)
        elif args.action == "validate":
            report = workspace.validate(clock); _emit(report, structured)
            return EXIT_SUCCESS if report.valid else EXIT_INTEGRITY
        elif args.action == "export": _emit(str(workspace.export(args.destination)), structured)
    elif args.command == "source":
        if args.action == "register": _emit(workspace.register_source(args.source, clock), structured)
        elif args.action == "list": _emit(workspace.list_sources(), structured)
        elif args.action == "verify":
            valid = workspace.verify_source(args.source_id); _emit({"valid": valid}, structured)
            return EXIT_SUCCESS if valid else EXIT_INTEGRITY
    elif args.command == "artifact":
        artifacts = workspace.list_artifacts()
        if args.action == "list": _emit(artifacts, structured)
        else:
            artifact = next((a for a in artifacts if a.artifact_id == args.artifact_id), None)
            if artifact is None: raise FileNotFoundError(args.artifact_id)
            _emit(artifact, structured)
    elif args.command == "provider":
        provider = registry.get(args.provider_id)
        result = workspace.invoke_provider(
            provider, Capability(args.capability), args.input, clock, args.mode
        )
        _emit(result, structured)
    elif args.command == "operation":
        result = _find_operation(workspace, args.operation_id)
        if result["request"] is None: raise FileNotFoundError(args.operation_id)
        _emit(result, structured)
    elif args.command == "replay":
        result = workspace.replay(args.operation_id, registry, clock)
        _emit(result, structured)
        return EXIT_SUCCESS if result.status.value == "match" else EXIT_INTEGRITY
    elif args.command == "report":
        report = workspace.validate(clock)
        destination = workspace.root / "reports" / "workspace-report.json"
        destination.write_bytes(canonical_bytes(report))
        human = workspace.root / "reports" / "workspace-report.txt"
        human.write_text(
            f"Ratiocinatus workspace report\nWorkspace: {workspace.manifest.workspace_id}\n"
            f"Valid: {report.valid}\nFindings: {len(report.findings)}\n",
            encoding="utf-8",
        )
        _emit({"machine": str(destination), "human": str(human)}, structured)
    elif args.command == "config":
        _emit(workspace.config, structured)
    return EXIT_SUCCESS


def main(argv: list[str] | None = None) -> int:
    arguments = list(argv) if argv is not None else sys.argv[1:]
    structured = "--json" in arguments
    if "fixture" in arguments:
        from .fixture_cli import main as fixture_main
        return fixture_main(arguments)
    try:
        return run(build_parser().parse_args(arguments))
    except (ValidationError, ValueError) as exc:
        print(f"invalid request: {exc}", file=sys.stderr); return EXIT_INVALID
    except FileNotFoundError as exc:
        print(f"missing input: {exc}", file=sys.stderr); return EXIT_MISSING
    except ParticipantSubtitleIntegrityError as exc:
        print(f"participant subtitle integrity failure: {exc}", file=sys.stderr)
        return EXIT_INTEGRITY
    except SpeakerTranscriptIntegrityError as exc:
        print(f"speaker transcript integrity failure: {exc}", file=sys.stderr)
        return EXIT_INTEGRITY
    except IdentityViewIntegrityError as exc:
        print(f"identity-view integrity failure: {exc}", file=sys.stderr)
        return EXIT_INTEGRITY
    except IdentityBindingIntegrityError as exc:
        print(f"identity binding integrity failure: {exc}", file=sys.stderr)
        return EXIT_INTEGRITY
    except IdentityFoundationIntegrityError as exc:
        print(f"identity foundation integrity failure: {exc}", file=sys.stderr)
        return EXIT_INTEGRITY
    except ReferenceEnrollmentIntegrityError as exc:
        print(f"reference enrollment integrity failure: {exc}", file=sys.stderr)
        return EXIT_INTEGRITY
    except ReferenceComparisonIntegrityError as exc:
        print(f"reference comparison integrity failure: {exc}", file=sys.stderr)
        return EXIT_INTEGRITY
    except DiarizationEvaluationIntegrityError as exc:
        print(f"diarization evaluation integrity failure: {exc}", file=sys.stderr)
        return EXIT_INTEGRITY
    except ClusteringEvaluationIntegrityError as exc:
        print(f"clustering evaluation integrity failure: {exc}", file=sys.stderr)
        return EXIT_INTEGRITY
    except ClusteringIntegrityError as exc:
        print(f"clustering integrity failure: {exc}", file=sys.stderr)
        return EXIT_INTEGRITY
    except DiarizationIntegrityError as exc:
        print(f"diarization integrity failure: {exc}", file=sys.stderr)
        return EXIT_INTEGRITY
    except SpeechActivityIntegrityError as exc:
        print(f"speech activity integrity failure: {exc}", file=sys.stderr)
        return EXIT_INTEGRITY
    except TranscriptionIntegrityError as exc:
        print(f"transcription integrity failure: {exc}", file=sys.stderr)
        return EXIT_INTEGRITY
    except TranscriptAssemblyIntegrityError as exc:
        print(f"transcript assembly integrity failure: {exc}", file=sys.stderr)
        return EXIT_INTEGRITY
    except TranscriptCorrectionIntegrityError as exc:
        print(f"transcript correction integrity failure: {exc}", file=sys.stderr)
        return EXIT_INTEGRITY
    except Phase2RecoveryError as exc:
        _error(exc, "integrity_failure", structured)
        return EXIT_INTEGRITY
    except Phase3RecoveryError as exc:
        _error(exc, "integrity_failure", structured)
        return EXIT_INTEGRITY
    except Phase3CompletionIntegrityError as exc:
        _error(exc, "integrity_failure", structured)
        return EXIT_INTEGRITY
    except Phase4CompletionIntegrityError as exc:
        _error(exc, "integrity_failure", structured)
        return EXIT_INTEGRITY
    except DeterministicDiscourseIntegrityError as exc:
        _error(exc, "integrity_failure", structured)
        return EXIT_INTEGRITY
    except ProviderDiscourseIntegrityError as exc:
        _error(exc, "integrity_failure", structured)
        return EXIT_INTEGRITY
    except DiscourseConsolidationIntegrityError as exc:
        _error(exc, "integrity_failure", structured)
        return EXIT_INTEGRITY
    except QuestionAnswerIntegrityError as exc:
        _error(exc, "integrity_failure", structured)
        return EXIT_INTEGRITY
    except ArgumentRelationIntegrityError as exc:
        _error(exc, "integrity_failure", structured)
        return EXIT_INTEGRITY
    except LexicalConstructionIntegrityError as exc:
        _error(exc, "integrity_failure", structured)
        return EXIT_INTEGRITY
    except ProceduralStateIntegrityError as exc:
        _error(exc, "integrity_failure", structured)
        return EXIT_INTEGRITY
    except TranscriptEvaluationIntegrityError as exc:
        _error(exc, "integrity_failure", structured)
        return EXIT_INTEGRITY
    except SubtitleExportIntegrityError as exc:
        print(f"subtitle export integrity failure: {exc}", file=sys.stderr)
        return EXIT_INTEGRITY
    except ClusteringUnavailable as exc:
        print(f"clustering unavailable: {exc}", file=sys.stderr)
        return EXIT_UNAVAILABLE
    except DiarizationProviderUnavailable as exc:
        print(f"diarization provider unavailable: {exc}", file=sys.stderr)
        return EXIT_UNAVAILABLE
    except DiscourseProviderUnavailable as exc:
        print(f"discourse provider unavailable: {exc}", file=sys.stderr)
        return EXIT_UNAVAILABLE
    except SpeechProviderUnavailable as exc:
        print(f"speech provider unavailable: {exc}", file=sys.stderr)
        return EXIT_UNAVAILABLE
    except ToolUnavailableError as exc:
        print(f"tool unavailable: {exc}", file=sys.stderr); return EXIT_UNAVAILABLE
    except IngestionInterrupted as exc:
        print(f"ingestion interrupted: {exc}", file=sys.stderr); return 6
    except VideoAccessError as exc:
        print(f"video access failure: {exc}", file=sys.stderr); return EXIT_INTEGRITY
    except AudioNormalizationError as exc:
        print(f"audio normalization failure: {exc}", file=sys.stderr); return EXIT_INTEGRITY
    except ChunkMaterializationError as exc:
        print(f"chunk materialization failure: {exc}", file=sys.stderr); return EXIT_INTEGRITY
    except PacketContinuityError as exc:
        print(f"packet qualification failure: {exc}", file=sys.stderr); return EXIT_INTEGRITY
    except MediaInspectionError as exc:
        print(f"media inspection failure: {exc}", file=sys.stderr); return EXIT_INTEGRITY
    except (ProviderError, MalformedProviderOutput) as exc:
        print(f"provider failure: {exc}", file=sys.stderr); return EXIT_UNAVAILABLE
    except RatiocinatusError as exc:
        print(f"{exc.kind.value}: {exc}", file=sys.stderr); return EXIT_INTEGRITY
    except Exception as exc:
        print(f"internal failure: {exc}", file=sys.stderr); return EXIT_INTERNAL


if __name__ == "__main__":
    raise SystemExit(main())

