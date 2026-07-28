from __future__ import annotations

import json
import math
import shutil
import subprocess
import wave
from array import array
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ratiocinatus.activity import FFmpegEnergySpeechActivityProvider
from ratiocinatus.cli import EXIT_SUCCESS, main
from ratiocinatus.ingestion import prepare_ingestion_request, run_ingestion
from ratiocinatus.correction_contracts import (
    CorrectionActor,
    CorrectionActorKind,
    CorrectionType,
    TranscriptCorrectionDraft,
    TranscriptSegmentProposal,
)
from ratiocinatus.corrections import (
    TranscriptCorrectionIntegrityError,
    _state_from_segment,
    apply_correction_batch,
    prepare_correction_batch,
)
from ratiocinatus.recovery import repair_transcription_report
from ratiocinatus.recovery_contracts import RecoveryAction
from ratiocinatus.kernel import canonical_bytes
from ratiocinatus.phase2_contracts import (
    ConfidenceOrigin,
    LanguageMode,
    SpeechActivityClassification,
    SpeechEvidenceFailureKind,
    TranscriptionPolicy,
)
from ratiocinatus.speech_activity import detect_corpus_activity
from ratiocinatus.speech_evidence import prepare_transcription_request
from ratiocinatus.transcription import (
    TranscriptionIntegrityError,
    transcribe_corpus,
    validate_transcription_response,
)
from ratiocinatus.transcript_assembly import (
    TranscriptAssemblyIntegrityError,
    assemble_transcript,
)
from ratiocinatus.transcript_contracts import TranscriptAssemblyStatus
from ratiocinatus.whisper_transcription import (
    OpenAIWhisperTranscriptionProvider,
)


HAS_RUNTIME = bool(
    shutil.which("ffmpeg")
    and shutil.which("ffprobe")
    and (Path.home() / ".cache/whisper/small.pt").is_file()
)
NOW = datetime(2000, 1, 1, tzinfo=timezone.utc)


def write_silence_tone_silence(path: Path) -> None:
    samples = array("h")
    for index in range(3 * 48_000):
        second = index / 48_000
        value = (
            int(0.25 * 32767 * math.sin(2 * math.pi * 440 * second))
            if 1 <= second < 2
            else 0
        )
        samples.append(value)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(48_000)
        output.writeframes(samples.tobytes())


def prepare_case(tmp_path: Path):
    source = tmp_path / "speech-proxy.wav"
    write_silence_tone_silence(source)
    phase1 = tmp_path / "phase1"
    ingestion = prepare_ingestion_request(source, phase1)
    run_ingestion(ingestion)
    corpus_root = (
        phase1 / "ingestions" / ingestion.ingestion_id / "corpus"
    )
    activity, _, activity_root, _ = detect_corpus_activity(
        corpus_root,
        tmp_path / "phase2",
        provider=FFmpegEnergySpeechActivityProvider(),
    )
    speech_ids = tuple(
        item.interval_id
        for item in activity.intervals
        if item.classification
        == SpeechActivityClassification.PROBABLE_SPEECH
    )
    assert speech_ids
    provider = OpenAIWhisperTranscriptionProvider()
    request = prepare_transcription_request(
        activity,
        provider.capabilities.identity,
        NOW,
        speech_interval_ids=speech_ids,
        policy=TranscriptionPolicy(
            language_mode=LanguageMode.EXPLICIT,
            language="en",
        ),
    )
    return corpus_root, activity_root, activity, provider, request


def worker_result(request) -> bytes:
    interval = request.speech_intervals[0].normalized_audio_interval
    start = interval.start_microseconds / 1_000_000
    end = (
        interval.start_microseconds + interval.duration_microseconds
    ) / 1_000_000
    middle = (start + end) / 2
    return (
        json.dumps(
            {
                "language": "en",
                "text": " hello world",
                "segments": [
                    {
                        "id": 0,
                        "start": start,
                        "end": end,
                        "text": " hello world",
                        "avg_logprob": -0.2,
                        "words": [
                            {
                                "word": " hello",
                                "start": start,
                                "end": middle,
                                "probability": 0.9,
                            },
                            {
                                "word": " world",
                                "start": middle,
                                "end": end,
                                "probability": 0.8,
                            },
                        ],
                    }
                ],
            },
            sort_keys=True,
        )
        + "\n"
    ).encode()


@pytest.mark.skipif(not HAS_RUNTIME, reason="Whisper/FFmpeg runtime unavailable")
def test_whisper_normalization_persistence_reuse_and_corruption(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    corpus_root, activity_root, _, provider, request = prepare_case(tmp_path)

    original_run = subprocess.run

    def completed(*args, **kwargs):
        if "ratiocinatus.whisper_worker" not in args[0]:
            return original_run(*args, **kwargs)
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=worker_result(request),
            stderr=b"",
        )

    monkeypatch.setattr(subprocess, "run", completed)
    result = transcribe_corpus(
        corpus_root,
        activity_root,
        tmp_path / "phase2",
        provider=provider,
        policy=request.policy,
        speech_interval_ids=request.speech_interval_ids,
    )
    stored_request, response, report, stored, reused = result

    assert response.complete and not reused
    assert report.word_observation_count == 2
    assert response.raw_evidence.relative_path == "raw-provider-response.json"
    candidate = response.observations[0].candidates[0]
    assert candidate.text_confidence.origin == ConfidenceOrigin.DERIVED
    assert candidate.words[0].recognition_confidence.origin == (
        ConfidenceOrigin.PROVIDER_NATIVE
    )
    validate_transcription_response(response, stored_request, stored)

    repeated = transcribe_corpus(
        corpus_root,
        activity_root,
        tmp_path / "phase2",
        provider=provider,
        policy=request.policy,
        speech_interval_ids=request.speech_interval_ids,
    )
    assert repeated[4]
    assert repeated[1].response_id == response.response_id
    assert main([
        "--json",
        "speech",
        "transcribe",
        str(corpus_root),
        str(activity_root),
        str(tmp_path / "phase2"),
        "--language",
        "en",
    ]) == EXIT_SUCCESS
    transcribe_payload = json.loads(capsys.readouterr().out)
    assert transcribe_payload["reused"] is True
    assert main([
        "--json",
        "speech",
        "inspect-transcription",
        str(stored),
    ]) == EXIT_SUCCESS
    payload = json.loads(capsys.readouterr().out)
    assert payload["response"]["response_id"] == response.response_id

    (stored / "report.md").write_text("corrupt", encoding="utf-8")
    repaired_report, recovery = repair_transcription_report(
        stored, provider, report_root=tmp_path / "phase2"
    )
    assert repaired_report.response_id == response.response_id
    assert recovery.action == RecoveryAction.REPAIRED_WITHOUT_PROVIDER
    assert not recovery.provider_invoked
    assert recovery.quarantine_relative_path
    assert main([
        "--json", "speech", "repair-transcription-report", str(stored),
    ]) == EXIT_SUCCESS
    repair_payload = json.loads(capsys.readouterr().out)
    assert repair_payload["recovery"]["action"] == "reused_valid"

    assembled, assembly_report, assembly_root, assembly_reused = (
        assemble_transcript(
            corpus_root,
            stored,
            tmp_path / "phase2",
        )
    )
    assert not assembly_reused
    assert assembled.status == TranscriptAssemblyStatus.REVIEW_REQUIRED
    assert len(assembled.segments) == 1
    assert len(assembled.words) == 2
    assert assembly_report.review_region_count >= 2
    assert assemble_transcript(
        corpus_root,
        stored,
        tmp_path / "phase2",
    )[3]
    assert main([
        "--json",
        "speech",
        "assemble",
        str(corpus_root),
        str(stored),
        str(tmp_path / "phase2"),
    ]) == EXIT_SUCCESS
    assembly_payload = json.loads(capsys.readouterr().out)
    assert assembly_payload["reused"] is True
    assert main([
        "--json",
        "speech",
        "inspect-assembly",
        str(assembly_root),
    ]) == EXIT_SUCCESS
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["assembly"]["assembly_id"] == assembled.assembly_id

    prior = _state_from_segment(assembled)[0]
    draft = TranscriptCorrectionDraft(
        target_version_id=assembled.version.version_id,
        correction_type=CorrectionType.REPLACEMENT,
        target_artifact_ids=(prior.artifact_id,),
        prior_values=(prior,),
        proposed_values=(
            TranscriptSegmentProposal(
                source_interval=prior.source_interval,
                normalized_audio_interval=prior.normalized_audio_interval,
                text="Hello corrected world",
                normalized_text="Hello corrected world",
                language_claim=prior.language_claim,
            ),
        ),
        affected_source_interval=prior.source_interval,
        actor=CorrectionActor(
            kind=CorrectionActorKind.HUMAN,
            actor_id="test-reviewer",
            display_name="Test reviewer",
        ),
        corrected_at=response.completed_at,
        reason="Exercise append-only correction persistence.",
        evidence_or_review_references=("review:integration",),
    )
    batch = prepare_correction_batch(
        assembled.version.version_id, (draft,)
    )
    batch_path = tmp_path / "correction-batch.json"
    batch_path.write_bytes(canonical_bytes(batch))
    revision, revision_report, revision_root, revision_reused = (
        apply_correction_batch(
            assembly_root, batch_path, tmp_path / "phase2"
        )
    )
    assert not revision_reused
    assert revision.current_corrected_view.rendered_text == (
        "Hello corrected world"
    )
    assert revision_report.human_correction_count == 1
    assert apply_correction_batch(
        assembly_root, batch_path, tmp_path / "phase2"
    )[3]
    assert main([
        "--json", "speech", "correct", str(assembly_root),
        str(batch_path), str(tmp_path / "phase2"),
    ]) == EXIT_SUCCESS
    corrected_payload = json.loads(capsys.readouterr().out)
    assert corrected_payload["reused"] is True
    assert main([
        "--json", "speech", "inspect-revision", str(revision_root),
    ]) == EXIT_SUCCESS
    json.loads(capsys.readouterr().out)
    assert main([
        "--json", "speech", "render-transcript", str(revision_root),
        "--view", "current",
    ]) == EXIT_SUCCESS
    rendered = json.loads(capsys.readouterr().out)
    assert rendered["rendered_text"] == "Hello corrected world"
    assert main([
        "--json", "speech", "correction-history", str(revision_root),
    ]) == EXIT_SUCCESS
    history = json.loads(capsys.readouterr().out)
    assert len(history["corrections"]) == 1

    request_path = stored / "request.json"
    request_bytes = request_path.read_bytes()
    incompatible_request = json.loads(request_bytes)
    incompatible_request["corpus_id"] = "corpus_" + "0" * 32
    request_path.write_bytes(canonical_bytes(incompatible_request))
    with pytest.raises(
        ValueError, match="belongs to another corpus"
    ):
        assemble_transcript(corpus_root, stored, tmp_path / "phase2")
    request_path.write_bytes(request_bytes)
    correction_path = next((revision_root / "corrections").glob("*.json"))
    correction_path.write_text("{}", encoding="utf-8")
    with pytest.raises(TranscriptCorrectionIntegrityError):
        apply_correction_batch(
            assembly_root, batch_path, tmp_path / "phase2"
        )

    segment_path = next((assembly_root / "segments").glob("*.json"))
    segment_path.write_text("{}", encoding="utf-8")
    with pytest.raises(TranscriptAssemblyIntegrityError):
        assemble_transcript(
            corpus_root,
            stored,
            tmp_path / "phase2",
        )

    (stored / "raw-provider-response.json").write_text(
        "corrupt", encoding="utf-8"
    )
    with pytest.raises(
        TranscriptionIntegrityError, match="raw transcription evidence"
    ):
        transcribe_corpus(
            corpus_root,
            activity_root,
            tmp_path / "phase2",
            provider=provider,
            policy=request.policy,
            speech_interval_ids=request.speech_interval_ids,
        )


@pytest.mark.skipif(not HAS_RUNTIME, reason="Whisper/FFmpeg runtime unavailable")
def test_whisper_timeout_and_model_fingerprint_are_typed(
    tmp_path: Path, monkeypatch,
) -> None:
    corpus_root, _, _, provider, request = prepare_case(tmp_path)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], timeout=1)

    monkeypatch.setattr(subprocess, "run", timeout)
    response = provider.transcribe(
        request,
        corpus_root / "derivatives" / "audio.flac",
        evidence_root=tmp_path / "timeout",
    )
    assert not response.complete
    assert response.failure == SpeechEvidenceFailureKind.TIMEOUT

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0], returncode=0, stdout=b"not-json", stderr=b""
        ),
    )
    malformed = provider.transcribe(
        request,
        corpus_root / "derivatives" / "audio.flac",
        evidence_root=tmp_path / "malformed",
    )
    assert not malformed.complete
    assert malformed.failure == SpeechEvidenceFailureKind.MALFORMED_OUTPUT

    monkeypatch.setattr(
        OpenAIWhisperTranscriptionProvider,
        "EXPECTED_MODEL_SHA256",
        "0" * 64,
    )
    with pytest.raises(RuntimeError, match="model artifact hash"):
        OpenAIWhisperTranscriptionProvider()
