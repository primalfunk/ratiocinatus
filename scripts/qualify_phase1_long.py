"""Run and record the Phase 1 long-recording qualification."""

from __future__ import annotations

import argparse
import json
import time
import tracemalloc
from pathlib import Path

from ratiocinatus.addressing import map_timestamp
from ratiocinatus.addressing_contracts import MediaTimestamp, TimeDomain
from ratiocinatus.corpus import load_corpus, validate_corpus
from ratiocinatus.corpus_contracts import IngestionStage, IngestionStageStatus
from ratiocinatus.ingestion import (
    IngestionInterrupted,
    prepare_ingestion_request,
    run_ingestion,
)
from ratiocinatus.materialization import materialize_audio_chunk
from ratiocinatus.media import sha256_file


def directory_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def qualify(
    source: Path,
    workspace: Path,
    materialization_root: Path,
) -> dict[str, object]:
    source = source.resolve(strict=True)
    workspace = workspace.resolve()
    materialization_root = materialization_root.resolve()
    request = prepare_ingestion_request(source, workspace)
    tracemalloc.start()
    started = time.perf_counter()
    interrupted = False
    try:
        run_ingestion(
            request,
            interrupt_after=IngestionStage.AUDIO_NORMALIZATION_COMMITTED,
        )
    except IngestionInterrupted:
        interrupted = True
    resume_started = time.perf_counter()
    manifest = run_ingestion(request)
    resume_seconds = time.perf_counter() - resume_started
    ingestion_seconds = time.perf_counter() - started
    _, python_peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    corpus_root = (
        workspace / "ingestions" / request.ingestion_id / "corpus"
    )
    loaded = load_corpus(corpus_root)
    integrity = validate_corpus(corpus_root)
    chunks = loaded["chunks"].chunks
    indices = (0, len(chunks) // 2, len(chunks) - 1)
    materialized: list[dict[str, object]] = []
    for index in indices:
        chunk = chunks[index]
        first_started = time.perf_counter()
        first = materialize_audio_chunk(
            chunk,
            loaded["audio"],
            loaded["audio_path"],
            materialization_root,
            reason="qualification",
        )
        first_seconds = time.perf_counter() - first_started
        hit_started = time.perf_counter()
        hit = materialize_audio_chunk(
            chunk,
            loaded["audio"],
            loaded["audio_path"],
            materialization_root,
            reason="qualification",
        )
        hit_seconds = time.perf_counter() - hit_started
        materialized.append(
            {
                "ordinal": index,
                "chunk_id": chunk.chunk_id,
                "cache_first": first.cache_disposition.value,
                "cache_second": hit.cache_disposition.value,
                "first_seconds": round(first_seconds, 6),
                "hit_seconds": round(hit_seconds, 6),
                "expected_duration_microseconds": (
                    first.materialized_chunk.expected_duration_microseconds
                ),
                "actual_duration_microseconds": (
                    first.materialized_chunk.actual_duration_microseconds
                ),
                "content_sha256": (
                    first.materialized_chunk.integrity.content_sha256
                ),
                "byte_size": first.materialized_chunk.integrity.byte_size,
                "integrity_valid": first.materialized_chunk.integrity.valid,
            }
        )
    duration = loaded["timeline"].corpus_duration_microseconds
    mapped_points = []
    for label, timestamp in (
        ("start", 0),
        ("middle", duration // 2),
        ("end", duration - 1),
    ):
        mapping = map_timestamp(
            loaded["timeline"],
            MediaTimestamp(
                domain=TimeDomain.NORMALIZED_CORPUS,
                microseconds=timestamp,
            ),
        )
        mapped_points.append(
            {
                "label": label,
                "corpus_microseconds": timestamp,
                "source_microseconds": (
                    mapping.mapped.microseconds if mapping.mapped else None
                ),
                "classification": mapping.classification.value,
            }
        )
    reused_stages = sorted(
        {
            record.stage.value
            for record in manifest.checkpoint.records
            if record.status == IngestionStageStatus.REUSED
        }
    )
    source_bytes = source.stat().st_size
    output_bytes = directory_bytes(workspace) + directory_bytes(
        materialization_root
    )
    assertions = {
        "source_at_least_two_hours": duration >= 7_200_000_000,
        "at_least_twelve_chunks": len(chunks) >= 12,
        "coverage_complete": loaded["chunks"].coverage_complete,
        "integrity_valid": integrity.valid,
        "interruption_observed": interrupted,
        "resume_complete": manifest.checkpoint.complete,
        "resume_reused_committed_stages": bool(reused_stages),
        "mapping_start_middle_end_exact": all(
            item["classification"] == "exact" for item in mapped_points
        ),
        "materialized_chunks_valid": all(
            item["integrity_valid"] for item in materialized
        ),
        "materialized_cache_hits": all(
            item["cache_second"] == "hit" for item in materialized
        ),
        "python_peak_below_256_mib": python_peak_bytes < 256 * 1024 * 1024,
    }
    return {
        "qualification": "phase-1-long-recording",
        "status": "passed" if all(assertions.values()) else "failed",
        "source": {
            "name": source.name,
            "sha256": sha256_file(source),
            "byte_size": source_bytes,
            "duration_microseconds": duration,
        },
        "ingestion": {
            "ingestion_id": request.ingestion_id,
            "corpus_id": loaded["corpus"].corpus_id,
            "processing_seconds": round(ingestion_seconds, 6),
            "resume_seconds": round(resume_seconds, 6),
            "python_allocator_peak_bytes": python_peak_bytes,
            "output_bytes": output_bytes,
            "output_to_source_ratio": round(output_bytes / source_bytes, 6),
            "reused_stages": reused_stages,
        },
        "chunks": {
            "count": len(chunks),
            "target_duration_microseconds": (
                loaded["chunks"].policy.target_duration_microseconds
            ),
            "overlap_microseconds": (
                loaded["chunks"].policy.overlap_microseconds
            ),
            "coverage_complete": loaded["chunks"].coverage_complete,
            "maximum_coverage_multiplicity": (
                loaded["chunks"].maximum_coverage_multiplicity
            ),
            "materialized_samples": materialized,
        },
        "mapped_points": mapped_points,
        "assertions": assertions,
    }


def markdown(report: dict[str, object]) -> str:
    source = report["source"]
    ingestion = report["ingestion"]
    chunks = report["chunks"]
    assertions = report["assertions"]
    lines = [
        "# Phase 1 long-recording qualification",
        "",
        f"Status: **{str(report['status']).upper()}**",
        "",
        "A reproducibly generated Apache-2.0 synthetic audiovisual source was "
        "ingested with an intentional interruption after audio normalization, "
        "then resumed from committed evidence.",
        "",
        "## Measurements",
        "",
        f"- Source duration: {source['duration_microseconds']} microseconds",
        f"- Source size: {source['byte_size']} bytes",
        f"- Source SHA-256: `{source['sha256']}`",
        f"- Operational chunks: {chunks['count']}",
        f"- End-to-end processing: {ingestion['processing_seconds']} seconds",
        f"- Resume pass: {ingestion['resume_seconds']} seconds",
        f"- Python allocator peak: {ingestion['python_allocator_peak_bytes']} bytes",
        f"- Corpus plus materialization output: {ingestion['output_bytes']} bytes",
        f"- Output/source ratio: {ingestion['output_to_source_ratio']}",
        "",
        "The Python peak is measured with `tracemalloc`. FFmpeg and FFprobe run "
        "as bounded-time streaming subprocesses, so their native allocations "
        "are not included in that Python allocator figure.",
        "",
        "## Gate results",
        "",
    ]
    lines.extend(
        f"- {'PASS' if passed else 'FAIL'} — {name.replace('_', ' ')}"
        for name, passed in assertions.items()
    )
    lines.extend(
        [
            "",
            "Three chunks (start, middle, and end) were materialized as FLAC, "
            "validated, hashed, and immediately re-requested to prove cache hits. "
            "Start, middle, and end corpus timestamps mapped exactly to source time.",
            "",
            "Machine-readable measurements are in "
            "`phase-1-long-recording-qualification.json`.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("materialization_root", type=Path)
    parser.add_argument("report_json", type=Path)
    parser.add_argument("report_markdown", type=Path)
    args = parser.parse_args()
    report = qualify(args.source, args.workspace, args.materialization_root)
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
