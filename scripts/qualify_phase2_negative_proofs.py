"""Run and normalize the Phase 2 work-order negative-proof matrix."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


CASES = (
    (
        "unsupported_audio_or_corpus_version",
        "tests/test_phase1_packet_continuity.py::"
        "test_phase1_versions_are_compatibility_gates",
        "strict contract ValidationError",
    ),
    (
        "missing_normalized_audio_derivative",
        "tests/test_phase1_corpus_ingestion.py::"
        "test_interruption_resume_portable_export_and_integrity",
        "invalid CorpusIntegrityReport with explicit missing finding",
    ),
    (
        "corrupted_audio_evidence",
        "tests/test_phase1_corpus_ingestion.py::"
        "test_interruption_resume_portable_export_and_integrity",
        "invalid CorpusIntegrityReport with hash/substitution finding",
    ),
    (
        "provider_unavailable",
        "tests/test_phase2_foundation.py::"
        "test_provider_registry_and_capability_cli_are_conservative",
        "SpeechProviderUnavailable",
    ),
    (
        "model_unavailable",
        "tests/test_phase2_transcription.py::"
        "test_whisper_timeout_and_model_fingerprint_are_typed",
        "SpeechProviderUnavailable for unqualified model fingerprint",
    ),
    (
        "provider_timeout",
        "tests/test_phase2_transcription.py::"
        "test_whisper_timeout_and_model_fingerprint_are_typed",
        "SpeechEvidenceFailureKind.TIMEOUT",
    ),
    (
        "malformed_provider_result",
        "tests/test_phase2_transcription.py::"
        "test_whisper_timeout_and_model_fingerprint_are_typed",
        "SpeechEvidenceFailureKind.MALFORMED_OUTPUT",
    ),
    (
        "timestamps_outside_requested_interval",
        "tests/test_phase2_transcript_assembly.py::"
        "test_transcription_temporal_confidence_and_lineage_negative_proofs",
        "TranscriptionIntegrityError",
    ),
    (
        "invalid_confidence_values",
        "tests/test_phase2_transcript_assembly.py::"
        "test_transcription_temporal_confidence_and_lineage_negative_proofs",
        "strict ConfidenceMeasure ValidationError",
    ),
    (
        "word_timestamps_reverse_order",
        "tests/test_phase2_transcript_assembly.py::"
        "test_transcription_temporal_confidence_and_lineage_negative_proofs",
        "strict ProviderTranscriptObservation ValidationError",
    ),
    (
        "duplicated_overlap_output",
        "tests/test_phase2_transcript_assembly.py::"
        "test_transcription_temporal_confidence_and_lineage_negative_proofs",
        "TranscriptionIntegrityError",
    ),
    (
        "incompatible_transcript_and_corpus_ids",
        "tests/test_phase2_transcription.py::"
        "test_whisper_normalization_persistence_reuse_and_corruption",
        "strict TranscriptionRequest ValidationError",
    ),
    (
        "invalid_correction_target",
        "tests/test_phase2_transcript_assembly.py::"
        "test_stale_prior_value_and_unknown_version_are_rejected",
        "TranscriptCorrectionIntegrityError",
    ),
    (
        "conflicting_correction_history",
        "tests/test_phase2_transcript_assembly.py::"
        "test_stale_prior_value_and_unknown_version_are_rejected",
        "TranscriptCorrectionIntegrityError",
    ),
    (
        "invalid_subtitle_timing",
        "tests/test_phase2_transcript_assembly.py::"
        "test_machine_subtitles_split_on_words_persist_and_detect_corruption",
        "strict SubtitleCue ValidationError",
    ),
    (
        "unsupported_subtitle_export_version",
        "tests/test_phase2_transcript_assembly.py::"
        "test_machine_subtitles_split_on_words_persist_and_detect_corruption",
        "strict SubtitleExportManifest ValidationError",
    ),
    (
        "incomplete_cached_artifacts",
        "tests/test_phase2_recovery.py::"
        "test_missing_stage_resumes_without_quarantine",
        "RecoveryAction.REBUILT_MISSING",
    ),
)


def qualify(repo_root: Path) -> dict[str, object]:
    nodes = tuple(dict.fromkeys(case[1] for case in CASES))
    started = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *nodes],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        shell=False,
    )
    elapsed = time.perf_counter() - started
    output = (completed.stdout + completed.stderr).strip()
    skipped = " skipped" in output or output.startswith("s")
    suite_passed = completed.returncode == 0 and not skipped
    cases = [
        {
            "case": name,
            "test_node": node,
            "expected_typed_result": expected,
            "status": "passed" if suite_passed else "failed",
        }
        for name, node, expected in CASES
    ]
    return {
        "qualification": "phase-2-negative-proofs",
        "status": "passed" if suite_passed else "failed",
        "case_count": len(cases),
        "selected_test_count": len(nodes),
        "processing_seconds": round(elapsed, 6),
        "pytest_return_code": completed.returncode,
        "pytest_output": output,
        "skipped_selected_tests": skipped,
        "cases": cases,
    }


def markdown(report: dict[str, object]) -> str:
    lines = [
        "# Phase 2 negative-proof qualification",
        "",
        f"Status: **{str(report['status']).upper()}**",
        "",
        "| Required negative case | Expected result | Status |",
        "|---|---|---|",
    ]
    for case in report["cases"]:
        lines.append(
            f"| `{case['case']}` | {case['expected_typed_result']} | "
            f"{str(case['status']).upper()} |"
        )
    lines.extend(
        [
            "",
            f"Selected tests: {report['selected_test_count']}",
            f"Required cases: {report['case_count']}",
            f"Processing: {report['processing_seconds']} seconds",
            "",
            "A case passes only through its asserted typed refusal or "
            "conservative degraded/recovery result. Selected tests may not be "
            "skipped.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report_json", type=Path)
    parser.add_argument("report_markdown", type=Path)
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    report = qualify(repo_root)
    args.report_json.parent.mkdir(parents=True, exist_ok=True)
    args.report_json.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.report_markdown.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
