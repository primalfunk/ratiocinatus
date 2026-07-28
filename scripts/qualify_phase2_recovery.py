"""Qualify selective Phase 2 cache quarantine and downstream recovery."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from qualify_phase2_transcript_evaluation import qualify as qualify_evaluation
from ratiocinatus.correction_contracts import (
    TranscriptRevision,
    TranscriptViewKind,
)
from ratiocinatus.corrections import (
    _verify_persisted_revision,
    apply_correction_batch,
    validate_transcript_revision,
)
from ratiocinatus.evaluation_contracts import TranscriptEvaluationReport
from ratiocinatus.kernel import load_contract
from ratiocinatus.phase2_contracts import (
    TranscriptionProviderResponse,
)
from ratiocinatus.recovery import (
    build_recovery_report,
    fingerprint,
    persist_recovery_report,
    recover_artifact,
    repair_transcription_report,
)
from ratiocinatus.recovery_contracts import Phase2RecoveryStage
from ratiocinatus.subtitle_contracts import (
    SubtitleExportManifest,
    SubtitleValidationReport,
)
from ratiocinatus.subtitles import (
    export_subtitles,
    validate_subtitle_export,
)
from ratiocinatus.transcript_assembly import (
    _verify_persisted as verify_persisted_assembly,
    assemble_transcript,
    validate_transcript_assembly,
)
from ratiocinatus.transcript_contracts import TranscriptAssembly
from ratiocinatus.transcript_evaluation import (
    evaluate_transcript,
    validate_transcript_evaluation,
)
from ratiocinatus.whisper_transcription import (
    OpenAIWhisperTranscriptionProvider,
)


def _one(path: Path, pattern: str) -> Path:
    values = list(path.glob(pattern))
    if len(values) != 1:
        raise RuntimeError(
            f"expected one value for {path / pattern}, found {len(values)}"
        )
    return values[0]


def _assembly_validator(root: Path) -> None:
    assembly = load_contract(
        (root / "assembly.json").read_bytes(), TranscriptAssembly
    )
    validate_transcript_assembly(assembly)
    verify_persisted_assembly(root, assembly)


def qualify(root: Path, fixture_root: Path) -> dict[str, object]:
    source = qualify_evaluation(root, fixture_root)
    by_variant = {item["variant"]: item for item in source["results"]}
    protected_paths: list[tuple[str, Path]] = []
    for variant in ("clean", "naturalized", "adversarial"):
        corpus_root = _one(
            root / "phase1" / variant / "ingestions", "*/corpus"
        )
        transcription_root = _one(
            root / "phase2" / variant / "transcription", "*"
        )
        protected_paths.extend(
            (
                (
                    f"{variant}-phase1-source",
                    corpus_root / "source" / "original.flac",
                ),
                (
                    f"{variant}-normalized-audio",
                    corpus_root / "derivatives" / "audio.flac",
                ),
                (
                    f"{variant}-transcription-response",
                    transcription_root / "response.json",
                ),
                (
                    f"{variant}-raw-provider-evidence",
                    transcription_root / "raw-provider-response.json",
                ),
            )
        )
    before = tuple(
        fingerprint(label, path) for label, path in protected_paths
    )
    records = []

    clean_transcription = _one(
        root / "phase2" / "clean" / "transcription", "*"
    )
    (clean_transcription / "report.md").write_text(
        "simulated interrupted report write", encoding="utf-8"
    )
    _, record = repair_transcription_report(
        clean_transcription,
        OpenAIWhisperTranscriptionProvider(),
        report_root=root,
    )
    records.append(record)

    clean = by_variant["clean"]
    clean_evaluation_seed = load_contract(
        (root / clean["stored_relative"] / "report.json").read_bytes(),
        TranscriptEvaluationReport,
    )
    clean_assembly = (
        root
        / "phase2"
        / "clean"
        / "transcript-assemblies"
        / clean_evaluation_seed.base_assembly_id
    )
    clean_transcription = _one(
        root / "phase2" / "clean" / "transcription", "*"
    )
    corpus_clean = _one(
        root / "phase1" / "clean" / "ingestions", "*/corpus"
    )
    segment = next((clean_assembly / "segments").glob("*.json"))
    segment.write_text("{}", encoding="utf-8")

    def rebuild_assembly() -> Path:
        return assemble_transcript(
            corpus_clean,
            clean_transcription,
            root / "phase2" / "clean",
        )[2]

    record, _ = recover_artifact(
        stage=Phase2RecoveryStage.TRANSCRIPT_ASSEMBLY,
        artifact_root=clean_assembly,
        report_root=root,
        artifact_id=clean_evaluation_seed.base_assembly_id,
        validate=_assembly_validator,
        rebuild=rebuild_assembly,
        upstream_artifact_ids=(
            load_contract(
                (clean_transcription / "response.json").read_bytes(),
                TranscriptionProviderResponse,
            ).response_id,
        ),
    )
    records.append(record)

    naturalized = by_variant["naturalized"]
    naturalized_evaluation_seed = load_contract(
        (
            root / naturalized["stored_relative"] / "report.json"
        ).read_bytes(),
        TranscriptEvaluationReport,
    )
    naturalized_assembly = (
        root
        / "phase2"
        / "naturalized"
        / "transcript-assemblies"
        / naturalized_evaluation_seed.base_assembly_id
    )
    naturalized_revision = (
        root
        / "phase2"
        / "naturalized"
        / "transcript-revisions"
        / (
            load_contract(
                (
                    root
                    / naturalized["stored_relative"]
                    / "report.json"
                ).read_bytes(),
                TranscriptEvaluationReport,
            ).revision_id
        )
    )
    revision_value = load_contract(
        (naturalized_revision / "revision.json").read_bytes(),
        TranscriptRevision,
    )
    (naturalized_revision / "difference.json").write_text(
        "{}", encoding="utf-8"
    )

    def validate_revision(path: Path) -> None:
        base = load_contract(
            (naturalized_assembly / "assembly.json").read_bytes(),
            TranscriptAssembly,
        )
        value = load_contract(
            (path / "revision.json").read_bytes(), TranscriptRevision
        )
        validate_transcript_revision(value, assembly=base)
        _verify_persisted_revision(path, value)

    batch_path = (
        root / "correction-inputs" / "naturalized.json"
    )

    def rebuild_revision() -> Path:
        return apply_correction_batch(
            naturalized_assembly,
            batch_path,
            root / "phase2" / "naturalized",
        )[2]

    record, _ = recover_artifact(
        stage=Phase2RecoveryStage.TRANSCRIPT_CORRECTION,
        artifact_root=naturalized_revision,
        report_root=root,
        artifact_id=revision_value.revision_id,
        validate=validate_revision,
        rebuild=rebuild_revision,
        upstream_artifact_ids=(
            naturalized_evaluation_seed.base_assembly_id,
        ),
    )
    records.append(record)

    adversarial = by_variant["adversarial"]
    adversarial_report_root = root / adversarial["stored_relative"]
    adversarial_evaluation = load_contract(
        (adversarial_report_root / "report.json").read_bytes(),
        TranscriptEvaluationReport,
    )
    adversarial_assembly = (
        root
        / "phase2"
        / "adversarial"
        / "transcript-assemblies"
        / adversarial_evaluation.base_assembly_id
    )
    adversarial_revision = (
        root
        / "phase2"
        / "adversarial"
        / "transcript-revisions"
        / adversarial_evaluation.revision_id
    )
    adversarial_subtitle = (
        root
        / "phase2"
        / "adversarial"
        / "subtitle-exports"
        / adversarial_evaluation.subtitle_cues.export_id
    )
    subtitle_manifest = load_contract(
        (adversarial_subtitle / "manifest.json").read_bytes(),
        SubtitleExportManifest,
    )
    (adversarial_subtitle / "transcript.srt").write_text(
        "corrupt", encoding="utf-8"
    )

    def validate_subtitle(path: Path) -> None:
        manifest = load_contract(
            (path / "manifest.json").read_bytes(), SubtitleExportManifest
        )
        report = load_contract(
            (path / "validation-report.json").read_bytes(),
            SubtitleValidationReport,
        )
        validate_subtitle_export(manifest, path, report=report)

    def rebuild_subtitle() -> Path:
        return export_subtitles(
            adversarial_assembly,
            root / "phase2" / "adversarial",
            revision_root=adversarial_revision,
            view_kind=TranscriptViewKind.CURRENT_CORRECTED,
            policy=subtitle_manifest.policy,
        )[2]

    record, _ = recover_artifact(
        stage=Phase2RecoveryStage.SUBTITLE_EXPORT,
        artifact_root=adversarial_subtitle,
        report_root=root,
        artifact_id=subtitle_manifest.export_id,
        validate=validate_subtitle,
        rebuild=rebuild_subtitle,
        upstream_artifact_ids=(
            adversarial_evaluation.transcript_version_id,
        ),
    )
    records.append(record)

    clean_evaluation_root = root / clean["stored_relative"]
    clean_evaluation = load_contract(
        (clean_evaluation_root / "report.json").read_bytes(),
        TranscriptEvaluationReport,
    )
    (clean_evaluation_root / "report.md").write_text(
        "corrupt", encoding="utf-8"
    )
    clean_revision = (
        root
        / "phase2"
        / "clean"
        / "transcript-revisions"
        / clean_evaluation.revision_id
    )
    clean_subtitle = (
        root
        / "phase2"
        / "clean"
        / "subtitle-exports"
        / clean_evaluation.subtitle_cues.export_id
    )
    reference = root / "evaluation-references" / "clean.json"

    def validate_evaluation(path: Path) -> None:
        value = load_contract(
            (path / "report.json").read_bytes(),
            TranscriptEvaluationReport,
        )
        validate_transcript_evaluation(value, root=path)

    def rebuild_evaluation() -> Path:
        return evaluate_transcript(
            clean_assembly,
            reference,
            root / "phase2" / "clean",
            revision_root=clean_revision,
            view_kind=TranscriptViewKind.CURRENT_CORRECTED,
            subtitle_export_root=clean_subtitle,
            policy=clean_evaluation.policy,
        )[1]

    record, _ = recover_artifact(
        stage=Phase2RecoveryStage.TRANSCRIPT_EVALUATION,
        artifact_root=clean_evaluation_root,
        report_root=root,
        artifact_id=clean_evaluation.evaluation_id,
        validate=validate_evaluation,
        rebuild=rebuild_evaluation,
        upstream_artifact_ids=(
            clean_evaluation.transcript_version_id,
            clean_evaluation.reference.reference_id,
        ),
    )
    records.append(record)

    after = tuple(
        fingerprint(label, path) for label, path in protected_paths
    )
    negative_proofs = (
        ("corrupt transcription report repaired without provider", not records[0].provider_invoked),
        ("corrupt assembly quarantined", bool(records[1].quarantine_relative_path)),
        ("corrupt correction quarantined", bool(records[2].quarantine_relative_path)),
        ("corrupt subtitle quarantined", bool(records[3].quarantine_relative_path)),
        ("corrupt evaluation quarantined", bool(records[4].quarantine_relative_path)),
        ("upstream evidence remained unchanged", before == after),
    )
    report = build_recovery_report(
        records=tuple(records),
        protected_before=before,
        protected_after=after,
        interruption_boundaries=(
            Phase2RecoveryStage.SPEECH_ACTIVITY,
            Phase2RecoveryStage.TRANSCRIPTION_RESPONSE,
            Phase2RecoveryStage.TRANSCRIPTION_REPORT,
            Phase2RecoveryStage.TRANSCRIPT_ASSEMBLY,
            Phase2RecoveryStage.TRANSCRIPT_CORRECTION,
            Phase2RecoveryStage.SUBTITLE_EXPORT,
            Phase2RecoveryStage.TRANSCRIPT_EVALUATION,
        ),
        negative_proofs=negative_proofs,
    )
    stored = persist_recovery_report(report, root)
    return {
        "qualification": "phase-2-cache-resume-recovery",
        "status": report.status,
        "source_evaluation_status": source["status"],
        "report_id": report.report_id,
        "records": [
            item.model_dump(mode="json") for item in report.records
        ],
        "protected_artifact_count": len(before),
        "protected_artifacts_unchanged": before == after,
        "interruption_boundaries": [
            item.value for item in report.interruption_boundaries
        ],
        "negative_proofs": dict(negative_proofs),
        "stored_relative": stored.relative_to(root).as_posix(),
        "limitations": [
            "Provider-process interruption and malformed-output behavior are "
            "covered by provider tests; this qualification does not force a "
            "second expensive Whisper inference.",
            "The transcription metadata repair path validates retained raw "
            "and normalized response evidence before rebuilding its report.",
            "Recovery quarantine is stage-local and never edits Phase 1 or "
            "validated transcription response evidence.",
        ],
    }


def markdown(report: dict[str, object]) -> str:
    lines = [
        "# Phase 2 cache, resume, and recovery qualification",
        "",
        f"Status: **{str(report['status']).upper()}**",
        "",
        "| Stage | Action | Provider invoked | Valid |",
        "|---|---|---|---|",
    ]
    for item in report["records"]:
        lines.append(
            f"| `{item['stage']}` | `{item['action']}` | "
            f"{item['provider_invoked']} | "
            f"{item['validated_after_recovery']} |"
        )
    lines.extend(
        [
            "",
            f"Protected artifacts unchanged: "
            f"`{report['protected_artifacts_unchanged']}`.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("fixture_root", type=Path)
    parser.add_argument("json_output", type=Path)
    parser.add_argument("markdown_output", type=Path)
    args = parser.parse_args()
    report = qualify(
        args.root.resolve(), args.fixture_root.resolve(strict=True)
    )
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.markdown_output.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
