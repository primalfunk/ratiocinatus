"""CLI integration for compatible reference-voice comparisons."""

from __future__ import annotations

from pathlib import Path

from .clustering_contracts import ClusteringRun
from .identity import load_identity_foundation
from .kernel import load_contract
from .phase3_contracts import DiarizationRun
from .reference_comparison import compare_reference_voice
from .reference_comparison_contracts import (
    CalibrationStatus,
    ChannelCompatibility,
    ReferenceComparisonThresholdPolicy,
    TargetVoiceRepresentation,
    VoiceCalibrationContext,
    VoiceComparisonTargetKind,
)
from .reference_comparison_validation import (
    load_reference_comparison,
    persist_reference_comparison,
    validate_reference_comparison_run,
)
from .reference_enrollment_contracts import ReferenceAudioQuality
from .reference_enrollment_operations import load_reference_enrollment

COMPARISON_ACTIONS = {
    "reference-compare",
    "reference-comparison-inspect",
    "reference-comparison-list",
    "reference-comparison-validate",
}


def add_reference_comparison_parsers(diasub) -> None:
    compare = diasub.add_parser("reference-compare")
    compare.add_argument("clustering_root", type=Path)
    compare.add_argument("diarization_root", type=Path)
    compare.add_argument("foundation_root", type=Path)
    compare.add_argument("enrollment_root", type=Path)
    compare.add_argument("destination", type=Path)
    compare.add_argument("--target-kind", required=True)
    compare.add_argument("--target", required=True)
    compare.add_argument("--reference", required=True)
    compare.add_argument("--score", type=float)
    compare.add_argument("--provider", required=True)
    compare.add_argument("--method", required=True)
    compare.add_argument("--representation-reference", required=True)
    compare.add_argument("--representation-sha256", required=True)
    compare.add_argument("--model-space", required=True)
    compare.add_argument("--model-fingerprint", required=True)
    compare.add_argument("--extraction-provider", required=True)
    compare.add_argument("--speech-duration-us", type=int, required=True)
    compare.add_argument("--audio-quality", required=True)
    compare.add_argument("--channel-compatibility", required=True)
    compare.add_argument("--overlap-present", action="store_true")
    compare.add_argument("--provenance", action="append", required=True)
    compare.add_argument("--supporting", action="append", default=[])
    compare.add_argument("--contrary", action="append", default=[])
    compare.add_argument("--score-minimum", type=float, default=0.0)
    compare.add_argument("--score-maximum", type=float, default=1.0)
    compare.add_argument("--contradict-maximum", type=float, default=0.20)
    compare.add_argument(
        "--weakly-contradict-maximum", type=float, default=0.35
    )
    compare.add_argument(
        "--weakly-support-minimum", type=float, default=0.65
    )
    compare.add_argument("--support-minimum", type=float, default=0.80)
    compare.add_argument(
        "--calibration-status", default="unavailable"
    )
    compare.add_argument("--cohort-reference")
    compare.add_argument("--calibration-dataset-reference")
    compare.add_argument("--operating-point-reference")
    compare.add_argument("--false-accept-rate", type=float)
    compare.add_argument("--false-reject-rate", type=float)
    compare.add_argument("--calibration-limitation", action="append", default=[])

    validate = diasub.add_parser("reference-comparison-validate")
    validate.add_argument("comparison_root", type=Path)
    validate.add_argument("clustering_root", type=Path)
    validate.add_argument("diarization_root", type=Path)
    validate.add_argument("foundation_root", type=Path)
    validate.add_argument("enrollment_root", type=Path)

    for action in (
        "reference-comparison-inspect",
        "reference-comparison-list",
    ):
        parser = diasub.add_parser(action)
        parser.add_argument("comparison_root", type=Path)


def _load_lineage(args):
    clustering_root = args.clustering_root.expanduser().resolve(strict=True)
    diarization_root = args.diarization_root.expanduser().resolve(strict=True)
    clustering = load_contract(
        (clustering_root / "clustering.json").read_bytes(),
        ClusteringRun,
    )
    diarization = load_contract(
        (diarization_root / "run.json").read_bytes(),
        DiarizationRun,
    )
    foundation, _ = load_identity_foundation(args.foundation_root)
    enrollments, _ = load_reference_enrollment(args.enrollment_root)
    return clustering, diarization, foundation, enrollments


def run_reference_comparison_command(args, emit, structured: bool):
    if args.action not in COMPARISON_ACTIONS:
        return None
    if args.action in {
        "reference-comparison-inspect",
        "reference-comparison-list",
    }:
        run, report = load_reference_comparison(args.comparison_root)
        if args.action == "reference-comparison-list":
            emit(run.comparisons, structured)
        else:
            emit(
                {
                    "comparison": run.model_dump(mode="json"),
                    "report": report.model_dump(mode="json"),
                },
                structured,
            )
        return 0

    clustering, diarization, foundation, enrollments = _load_lineage(args)
    if args.action == "reference-comparison-validate":
        run, report = load_reference_comparison(args.comparison_root)
        validate_reference_comparison_run(
            run,
            clustering,
            diarization,
            foundation,
            enrollments,
            report=report,
        )
        emit(
            {
                "valid": True,
                "run_id": run.run_id,
                "report_id": report.report_id,
            },
            structured,
        )
        return 0

    target = TargetVoiceRepresentation(
        target_kind=VoiceComparisonTargetKind(args.target_kind),
        target_artifact_id=args.target,
        representation_reference=args.representation_reference,
        representation_sha256=args.representation_sha256,
        model_space_id=args.model_space,
        model_fingerprint=args.model_fingerprint,
        extraction_provider=args.extraction_provider,
        speech_duration_microseconds=args.speech_duration_us,
        audio_quality=ReferenceAudioQuality(args.audio_quality),
        channel_compatibility=ChannelCompatibility(
            args.channel_compatibility
        ),
        overlap_present=args.overlap_present,
        provenance_references=tuple(args.provenance),
    )
    policy = ReferenceComparisonThresholdPolicy(
        score_minimum=args.score_minimum,
        score_maximum=args.score_maximum,
        contradict_maximum=args.contradict_maximum,
        weakly_contradict_maximum=args.weakly_contradict_maximum,
        weakly_support_minimum=args.weakly_support_minimum,
        support_minimum=args.support_minimum,
    )
    calibration = VoiceCalibrationContext(
        status=CalibrationStatus(args.calibration_status),
        cohort_reference=args.cohort_reference,
        calibration_dataset_reference=args.calibration_dataset_reference,
        operating_point_reference=args.operating_point_reference,
        estimated_false_accept_rate=args.false_accept_rate,
        estimated_false_reject_rate=args.false_reject_rate,
        limitations=tuple(args.calibration_limitation),
    )
    run, comparison = compare_reference_voice(
        clustering,
        diarization,
        foundation,
        enrollments,
        target=target,
        reference_id=args.reference,
        score=args.score,
        threshold_policy=policy,
        calibration=calibration,
        comparison_provider=args.provider,
        comparison_method=args.method,
        supporting_evidence_references=tuple(args.supporting),
        contrary_evidence_references=tuple(args.contrary),
    )
    persisted = persist_reference_comparison(
        run,
        clustering,
        diarization,
        foundation,
        enrollments,
        args.destination,
    )
    emit(
        {
            "comparison": comparison.model_dump(mode="json"),
            "run": persisted[0].model_dump(mode="json"),
            "report": persisted[1].model_dump(mode="json"),
            "comparison_root": str(persisted[2]),
            "reused": persisted[3],
        },
        structured,
    )
    return 0
