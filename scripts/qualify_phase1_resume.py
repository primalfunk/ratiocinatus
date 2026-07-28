"""Exercise Phase 1 interruption and recovery behavior stage by stage."""

from __future__ import annotations

import argparse
import errno
import json
import time
import wave
from array import array
from pathlib import Path

from ratiocinatus.chunk_contracts import ChunkPolicy
from ratiocinatus.corpus import load_corpus, validate_corpus
from ratiocinatus.corpus_contracts import (
    IngestionPolicy,
    IngestionStage,
    IngestionStageStatus,
)
import ratiocinatus.ingestion as ingestion_module
from ratiocinatus.ingestion import (
    IngestionInterrupted,
    prepare_ingestion_request,
    run_ingestion,
)
from ratiocinatus.kernel import load_contract
from ratiocinatus.normalization_contracts import AudioNormalizationResult


def write_source(path: Path, seconds: int = 4) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    samples = array(
        "h",
        ((index % 2000) - 1000 for index in range(16_000 * seconds)),
    )
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(samples.tobytes())


def stage_qualification(source: Path, root: Path) -> list[dict[str, object]]:
    results = []
    for stage in IngestionStage:
        workspace = root / "stages" / stage.value
        request = prepare_ingestion_request(source, workspace)
        interrupted = False
        started = time.perf_counter()
        try:
            run_ingestion(request, interrupt_after=stage)
        except IngestionInterrupted:
            interrupted = True
        manifest = run_ingestion(request)
        records = [
            record
            for record in manifest.checkpoint.records
            if record.stage == stage
        ]
        resumed = (
            any(record.status == IngestionStageStatus.REUSED for record in records)
            if stage != IngestionStage.COMPLETE
            else sum(
                record.status == IngestionStageStatus.COMMITTED
                for record in records
            )
            >= 2
        )
        corpus_root = (
            workspace / "ingestions" / request.ingestion_id / "corpus"
        )
        passed = bool(
            interrupted
            and any(
                record.status == IngestionStageStatus.INTERRUPTED
                for record in records
            )
            and resumed
            and manifest.checkpoint.complete
            and validate_corpus(corpus_root).valid
        )
        results.append(
            {
                "stage": stage.value,
                "passed": passed,
                "interrupted": interrupted,
                "resumed": resumed,
                "record_statuses": [
                    record.status.value for record in records
                ],
                "elapsed_seconds": round(time.perf_counter() - started, 6),
            }
        )
    return results


def fault_qualification(source: Path, root: Path) -> dict[str, bool]:
    partial_workspace = root / "faults/orphan-partial"
    partial_request = prepare_ingestion_request(source, partial_workspace)
    try:
        run_ingestion(
            partial_request,
            interrupt_after=IngestionStage.INSPECTION_COMMITTED,
        )
    except IngestionInterrupted:
        pass
    partial_run = (
        partial_workspace
        / "ingestions"
        / partial_request.ingestion_id
    )
    orphan = partial_run / "state/selection.json.partial-simulated"
    orphan.write_bytes(b'{"incomplete":')
    partial_manifest = run_ingestion(partial_request)
    failed_partial = next(
        (
            record
            for record in partial_manifest.checkpoint.records
            if record.stage == IngestionStage.SELECTION_COMMITTED
            and record.status == IngestionStageStatus.FAILED
        ),
        None,
    )
    partial_preserved = bool(
        failed_partial
        and failed_partial.artifact
        and (
            partial_run / failed_partial.artifact.relative_path
        ).read_bytes()
        == b'{"incomplete":'
    )

    derivative_workspace = root / "faults/derivative"
    derivative_request = prepare_ingestion_request(
        source, derivative_workspace
    )
    try:
        run_ingestion(
            derivative_request,
            interrupt_after=IngestionStage.AUDIO_NORMALIZATION_COMMITTED,
        )
    except IngestionInterrupted:
        pass
    derivative_run = (
        derivative_workspace
        / "ingestions"
        / derivative_request.ingestion_id
    )
    result = load_contract(
        (derivative_run / "state/audio-normalization.json").read_bytes(),
        AudioNormalizationResult,
    )
    assert isinstance(result, AudioNormalizationResult)
    derivative_path = (
        Path(result.cache_entry_path) / result.derivative.relative_path
    )
    with derivative_path.open("ab") as stream:
        stream.write(b"substitution")
    derivative_manifest = run_ingestion(derivative_request)
    derivative_rebuilt = bool(
        any(
            record.stage == IngestionStage.AUDIO_NORMALIZATION_COMMITTED
            and record.status == IngestionStageStatus.INVALIDATED
            for record in derivative_manifest.checkpoint.records
        )
        and validate_corpus(derivative_run / "corpus").valid
        and any(
            (derivative_workspace / "cache/audio-normalize/invalid").iterdir()
        )
    )

    changed = root / "changed-source.wav"
    write_source(changed)
    changed_request = prepare_ingestion_request(
        changed, root / "faults/changed-source"
    )
    with changed.open("ab") as stream:
        stream.write(b"changed")
    source_change_rejected = False
    try:
        run_ingestion(changed_request)
    except ValueError as exc:
        source_change_rejected = "source changed" in str(exc)

    config_workspace = root / "faults/configuration"
    default_request = prepare_ingestion_request(source, config_workspace)
    run_ingestion(default_request)
    changed_request = prepare_ingestion_request(
        source,
        config_workspace,
        policy=IngestionPolicy(
            chunks=ChunkPolicy(
                target_duration_microseconds=2_000_000,
                overlap_microseconds=500_000,
                minimum_duration_microseconds=500_000,
                maximum_duration_microseconds=5_000_000,
            )
        ),
    )
    changed_manifest = run_ingestion(changed_request)
    default_corpus = load_corpus(
        config_workspace
        / "ingestions"
        / default_request.ingestion_id
        / "corpus"
    )
    changed_run = (
        config_workspace / "ingestions" / changed_request.ingestion_id
    )
    changed_corpus = load_corpus(changed_run / "corpus")
    changed_audio_result = load_contract(
        (changed_run / "state/audio-normalization.json").read_bytes(),
        AudioNormalizationResult,
    )
    assert isinstance(changed_audio_result, AudioNormalizationResult)
    policy_isolated = bool(
        default_request.ingestion_id != changed_request.ingestion_id
        and default_corpus["audio"].content_sha256
        == changed_corpus["audio"].content_sha256
        and default_corpus["chunks"].plan_id
        != changed_corpus["chunks"].plan_id
        and changed_audio_result.cache_disposition.value == "hit"
        and changed_manifest.checkpoint.complete
    )
    incompatible = default_request.model_copy(
        update={"configuration_hash": "f" * 64}
    )
    incompatible_rejected = False
    try:
        run_ingestion(incompatible)
    except ValueError as exc:
        incompatible_rejected = "incompatible" in str(exc)

    def persistence_fault(label: str, error_number: int) -> bool:
        fault_workspace = root / f"faults/{label}"
        fault_request = prepare_ingestion_request(source, fault_workspace)
        original_atomic = ingestion_module._atomic
        injected = False

        def fail_once(path, value):
            nonlocal injected
            if path.name == "selection.json" and not injected:
                injected = True
                raise OSError(error_number, label)
            return original_atomic(path, value)

        ingestion_module._atomic = fail_once
        observed = False
        try:
            run_ingestion(fault_request)
        except OSError as exc:
            observed = exc.errno == error_number
        finally:
            ingestion_module._atomic = original_atomic
        manifest = run_ingestion(fault_request)
        selection_statuses = [
            record.status
            for record in manifest.checkpoint.records
            if record.stage == IngestionStage.SELECTION_COMMITTED
        ]
        inspection_reused = any(
            record.stage == IngestionStage.INSPECTION_COMMITTED
            and record.status == IngestionStageStatus.REUSED
            for record in manifest.checkpoint.records
        )
        return bool(
            observed
            and IngestionStageStatus.FAILED in selection_statuses
            and IngestionStageStatus.COMMITTED in selection_statuses
            and inspection_reused
            and manifest.checkpoint.complete
        )

    unsupported_workspace = root / "faults/unsupported-version"
    unsupported_request = prepare_ingestion_request(source, unsupported_workspace)
    try:
        run_ingestion(
            unsupported_request,
            interrupt_after=IngestionStage.CHUNK_PLAN_COMMITTED,
        )
    except IngestionInterrupted:
        pass
    unsupported_run = (
        unsupported_workspace / "ingestions" / unsupported_request.ingestion_id
    )
    chunk_path = unsupported_run / "state/chunk-plan.json"
    chunk_payload = json.loads(chunk_path.read_text(encoding="utf-8"))
    chunk_payload["format_version"] = "9.0.0"
    chunk_path.write_text(
        json.dumps(chunk_payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    unsupported_manifest = run_ingestion(unsupported_request)
    unsupported_version_rebuilt = bool(
        any(
            record.stage == IngestionStage.CHUNK_PLAN_COMMITTED
            and record.status == IngestionStageStatus.INVALIDATED
            for record in unsupported_manifest.checkpoint.records
        )
        and unsupported_manifest.checkpoint.complete
    )

    corpus_manifest_path = unsupported_run / "corpus/manifest.json"
    corpus_payload = json.loads(corpus_manifest_path.read_text(encoding="utf-8"))
    corpus_payload["format_version"] = "9.0.0"
    corpus_manifest_path.write_text(
        json.dumps(corpus_payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    corpus_was_invalid = not validate_corpus(corpus_manifest_path.parent).valid
    repaired_manifest = run_ingestion(unsupported_request)
    unsupported_corpus_rebuilt = bool(
        corpus_was_invalid
        and any(
            record.stage == IngestionStage.CORPUS_COMMITTED
            and record.status == IngestionStageStatus.INVALIDATED
            for record in repaired_manifest.checkpoint.records
        )
        and validate_corpus(corpus_manifest_path.parent).valid
    )

    original_version = ingestion_module._version
    base_tool_request = prepare_ingestion_request(
        source, root / "faults/tool-version"
    )

    def changed_version(executable, timeout_seconds):
        tool = original_version(executable, timeout_seconds)
        return tool.model_copy(
            update={"version_line": tool.version_line + " simulated-change"}
        )

    ingestion_module._version = changed_version
    try:
        changed_tool_request = prepare_ingestion_request(
            source, root / "faults/tool-version"
        )
    finally:
        ingestion_module._version = original_version
    tool_change_invalidated_identity = bool(
        base_tool_request.external_tool_identity_hashes
        != changed_tool_request.external_tool_identity_hashes
        and base_tool_request.configuration_hash
        != changed_tool_request.configuration_hash
        and base_tool_request.ingestion_id != changed_tool_request.ingestion_id
    )

    return {
        "orphan_partial_preserved_and_rebuilt": partial_preserved,
        "committed_derivative_detected_and_rebuilt": derivative_rebuilt,
        "changed_source_rejected": source_change_rejected,
        "chunk_policy_isolated_with_audio_reuse": policy_isolated,
        "incompatible_resume_configuration_rejected": incompatible_rejected,
        "write_denial_recorded_and_resumed": persistence_fault(
            "write-denial", errno.EACCES
        ),
        "full_disk_recorded_and_resumed": persistence_fault(
            "full-disk", errno.ENOSPC
        ),
        "unsupported_stage_version_rebuilt": unsupported_version_rebuilt,
        "unsupported_corpus_version_rebuilt": unsupported_corpus_rebuilt,
        "tool_version_change_invalidated_identity": tool_change_invalidated_identity,
    }


def qualify(root: Path) -> dict[str, object]:
    root = root.resolve()
    source = root / "resume-source.wav"
    write_source(source)
    started = time.perf_counter()
    stages = stage_qualification(source, root)
    faults = fault_qualification(source, root)
    assertions = {
        "resume_after_every_stage": all(item["passed"] for item in stages),
        **faults,
    }
    return {
        "qualification": "phase-1-resume-recovery",
        "status": "passed" if all(assertions.values()) else "failed",
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "stage_results": stages,
        "assertions": assertions,
    }


def markdown(report: dict[str, object]) -> str:
    lines = [
        "# Phase 1 resume and recovery qualification",
        "",
        f"Status: **{str(report['status']).upper()}**",
        "",
        f"Elapsed time: {report['elapsed_seconds']} seconds",
        "",
        "## Stage interruption matrix",
        "",
        "| Stage | Result | Recorded history |",
        "|---|---|---|",
    ]
    for item in report["stage_results"]:
        lines.append(
            f"| `{item['stage']}` | "
            f"{'PASS' if item['passed'] else 'FAIL'} | "
            f"`{', '.join(item['record_statuses'])}` |"
        )
    lines.extend(["", "## Recovery cases", ""])
    lines.extend(
        f"- {'PASS' if passed else 'FAIL'} - {name.replace('_', ' ')}"
        for name, passed in report["assertions"].items()
    )
    lines.extend(
        [
            "",
            "Machine-readable evidence is in "
            "`phase-1-resume-recovery-qualification.json`.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", type=Path)
    parser.add_argument("report_json", type=Path)
    parser.add_argument("report_markdown", type=Path)
    args = parser.parse_args()
    report = qualify(args.workspace)
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
