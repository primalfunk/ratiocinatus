from __future__ import annotations

import shutil
import wave
from array import array
from pathlib import Path

import pytest

from ratiocinatus.chunk_contracts import ChunkPolicy
from ratiocinatus.cli import build_parser
from ratiocinatus.corpus import load_corpus
from ratiocinatus.corpus_contracts import IngestionPolicy
from ratiocinatus.ingestion import prepare_ingestion_request, run_ingestion
from ratiocinatus.materialization import (
    ChunkMaterializationError,
    list_materialized_chunks,
    materialize_audio_chunk,
)
from ratiocinatus.materialization_contracts import (
    MATERIALIZATION_CONTRACT_MODELS,
    ChunkMaterializationPolicy,
)
from ratiocinatus.normalization_contracts import CacheDisposition

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def write_wave(path: Path, seconds: int = 5) -> None:
    samples = array(
        "h",
        ((index % 2000) - 1000 for index in range(16_000 * seconds)),
    )
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(samples.tobytes())


def test_materialization_contract_schemas_are_closed() -> None:
    for model in MATERIALIZATION_CONTRACT_MODELS:
        assert model.model_json_schema().get("additionalProperties") is False


def test_chunk_cli_exposes_list_and_materialize() -> None:
    parser = build_parser()
    listed = parser.parse_args(["chunk", "list", "corpus"])
    assert listed.command == "chunk"
    assert listed.action == "list"
    materialize = parser.parse_args(
        ["chunk", "materialize", "corpus", "2", "output"]
    )
    assert materialize.ordinal == 2
    assert materialize.reason == "provider_required"


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg integration unavailable")
def test_materialization_lineage_cache_corruption_and_bypass(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.wav"
    write_wave(source)
    policy = IngestionPolicy(
        chunks=ChunkPolicy(
            target_duration_microseconds=2_000_000,
            overlap_microseconds=500_000,
            minimum_duration_microseconds=500_000,
            maximum_duration_microseconds=5_000_000,
        )
    )
    request = prepare_ingestion_request(
        source, tmp_path / "ingestion-workspace", policy=policy
    )
    run_ingestion(request)
    corpus_root = (
        Path(request.workspace)
        / "ingestions"
        / request.ingestion_id
        / "corpus"
    )
    loaded = load_corpus(corpus_root)
    chunk = loaded["chunks"].chunks[1]
    output_root = tmp_path / "chunk-workspace"

    first = materialize_audio_chunk(
        chunk,
        loaded["audio"],
        loaded["audio_path"],
        output_root,
        reason="qualification",
    )
    assert first.cache_disposition == CacheDisposition.MISS
    item = first.materialized_chunk
    assert item.chunk_id == chunk.chunk_id
    assert item.corpus_interval == chunk.corpus_interval
    assert item.source_interval == chunk.source_interval
    assert item.derivative_local_interval.start_microseconds == (
        chunk.corpus_interval.start_microseconds
    )
    assert item.integrity.valid
    assert item.sample_rate == loaded["audio"].sample_rate
    assert len(list_materialized_chunks(output_root)) == 1

    second = materialize_audio_chunk(
        chunk,
        loaded["audio"],
        loaded["audio_path"],
        output_root,
        reason="qualification",
    )
    assert second.cache_disposition == CacheDisposition.HIT
    assert (
        second.materialized_chunk.integrity.content_sha256
        == item.integrity.content_sha256
    )

    materialized_path = (
        Path(second.cache_entry_path)
        / second.materialized_chunk.relative_path
    )
    with materialized_path.open("ab") as stream:
        stream.write(b"corruption")
    rebuilt = materialize_audio_chunk(
        chunk,
        loaded["audio"],
        loaded["audio_path"],
        output_root,
        reason="qualification",
    )
    assert rebuilt.cache_disposition == CacheDisposition.REBUILT
    assert any((output_root / "cache/chunk-materialize/invalid").iterdir())

    rebuilt_path = (
        Path(rebuilt.cache_entry_path)
        / rebuilt.materialized_chunk.relative_path
    )
    with rebuilt_path.open("ab") as stream:
        stream.write(b"corruption again")
    with pytest.raises(ChunkMaterializationError, match="refuses rebuild"):
        materialize_audio_chunk(
            chunk,
            loaded["audio"],
            loaded["audio_path"],
            output_root,
            reason="qualification",
            policy=ChunkMaterializationPolicy(
                invalid_cache_action="refuse"
            ),
        )
    materialize_audio_chunk(
        chunk,
        loaded["audio"],
        loaded["audio_path"],
        output_root,
        reason="qualification",
    )

    bypass_root = tmp_path / "bypass"
    bypassed = materialize_audio_chunk(
        chunk,
        loaded["audio"],
        loaded["audio_path"],
        bypass_root,
        use_cache=False,
    )
    assert bypassed.cache_disposition == CacheDisposition.BYPASSED
    with pytest.raises(FileExistsError):
        materialize_audio_chunk(
            chunk,
            loaded["audio"],
            loaded["audio_path"],
            bypass_root,
            use_cache=False,
        )
