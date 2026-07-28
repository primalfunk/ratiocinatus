"""Qualify initial Whisper provider observations on controlled excerpts."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from ratiocinatus.ingestion import prepare_ingestion_request, run_ingestion
from ratiocinatus.media import sha256_file
from ratiocinatus.phase2_contracts import (
    LanguageMode,
    SpeechActivityClassification,
    TranscriptionPolicy,
)
from ratiocinatus.silero_activity import SileroSpeechActivityProvider
from ratiocinatus.speech_activity import detect_corpus_activity
from ratiocinatus.transcription import transcribe_corpus
from ratiocinatus.whisper_transcription import (
    OpenAIWhisperTranscriptionProvider,
)


VARIANTS = ("clean", "naturalized", "adversarial")
LINE_IDS = ("L001", "L002", "L003", "L004", "L005")


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", text.lower())


def _distance(left: list[str], right: list[str]) -> int:
    previous = list(range(len(right) + 1))
    for left_index, left_item in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_item in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1]
                    + (left_item != right_item),
                )
            )
        previous = current
    return previous[-1]


def _metrics(reference: str, hypothesis: str) -> dict[str, object]:
    reference_words = _tokens(reference)
    hypothesis_words = _tokens(hypothesis)
    reference_characters = list(" ".join(reference_words))
    hypothesis_characters = list(" ".join(hypothesis_words))
    word_edits = _distance(reference_words, hypothesis_words)
    character_edits = _distance(
        reference_characters, hypothesis_characters
    )
    return {
        "reference_word_count": len(reference_words),
        "hypothesis_word_count": len(hypothesis_words),
        "word_edit_count": word_edits,
        "word_error_rate": (
            word_edits / len(reference_words) if reference_words else None
        ),
        "reference_character_count": len(reference_characters),
        "character_edit_count": character_edits,
        "character_error_rate": (
            character_edits / len(reference_characters)
            if reference_characters
            else None
        ),
    }


def qualify_variant(
    fixture_root: Path,
    root: Path,
    variant: str,
    activity_provider: SileroSpeechActivityProvider,
    transcription_provider: OpenAIWhisperTranscriptionProvider,
) -> dict[str, object]:
    source = fixture_root / "media" / variant / "mix.flac"
    schedule_path = (
        fixture_root / "schedules" / variant / "line_schedule.json"
    )
    definitions_path = fixture_root / "script" / "line_definitions.json"
    schedule = json.loads(schedule_path.read_text(encoding="utf-8-sig"))
    definitions = json.loads(
        definitions_path.read_text(encoding="utf-8-sig")
    )
    scheduled = [
        item for item in schedule["lines"] if item["line_id"] in LINE_IDS
    ]
    definition_by_id = {
        item["line_id"]: item["text"] for item in definitions["lines"]
    }
    evaluation_start = min(item["start_microseconds"] for item in scheduled)
    evaluation_end = max(item["end_microseconds"] for item in scheduled)
    reference_text = " ".join(
        definition_by_id[line_id] for line_id in LINE_IDS
    )
    before = sha256_file(source)
    phase1 = root / "phase1" / variant
    ingestion = prepare_ingestion_request(source, phase1)
    run_ingestion(ingestion)
    corpus_root = (
        phase1 / "ingestions" / ingestion.ingestion_id / "corpus"
    )
    activity, _, activity_root, _ = detect_corpus_activity(
        corpus_root,
        root / "phase2" / variant,
        provider=activity_provider,
    )
    selected_ids = tuple(
        item.interval_id
        for item in activity.intervals
        if item.classification
        == SpeechActivityClassification.PROBABLE_SPEECH
        and item.normalized_audio_interval.start_microseconds
        < evaluation_end
        and (
            item.normalized_audio_interval.start_microseconds
            + item.normalized_audio_interval.duration_microseconds
        )
        > evaluation_start
    )
    policy = TranscriptionPolicy(
        language_mode=LanguageMode.EXPLICIT,
        language="en",
        timeout_seconds=600,
    )
    request, response, report, stored, reused_first = transcribe_corpus(
        corpus_root,
        activity_root,
        root / "phase2" / variant,
        provider=transcription_provider,
        policy=policy,
        speech_interval_ids=selected_ids,
    )
    repeated = transcribe_corpus(
        corpus_root,
        activity_root,
        root / "phase2" / variant,
        provider=transcription_provider,
        policy=policy,
        speech_interval_ids=selected_ids,
    )
    hypothesis = " ".join(
        candidate.proposed_text
        for observation in response.observations
        for candidate in observation.candidates
        if candidate.selected
    )
    boundaries = [
        position
        for item in scheduled
        for position in (
            item["start_microseconds"],
            item["end_microseconds"],
        )
    ]
    observed_boundaries = [
        position
        for observation in response.observations
        for position in (
            observation.normalized_audio_interval.start_microseconds,
            observation.normalized_audio_interval.start_microseconds
            + observation.normalized_audio_interval.duration_microseconds,
        )
    ]
    boundary_errors = [
        min(abs(position - reference) for reference in boundaries)
        for position in observed_boundaries
    ]
    return {
        "variant": variant,
        "source_sha256": before,
        "source_unchanged": before == sha256_file(source),
        "activity_run_id": activity.run_id,
        "request_id": request.request_id,
        "response_id": response.response_id,
        "response_complete": response.complete,
        "report_status": report.status,
        "selected_activity_interval_count": len(selected_ids),
        "observation_count": len(response.observations),
        "selected_candidate_count": report.selected_candidate_count,
        "unresolved_observation_count": (
            report.unresolved_observation_count
        ),
        "word_observation_count": report.word_observation_count,
        "raw_evidence_retained": (
            response.raw_evidence.disposition.value == "retained"
        ),
        "cache_first_reused": reused_first,
        "cache_second_reused": repeated[4],
        "stable_repeated_response": (
            repeated[1].response_id == response.response_id
        ),
        "evaluation_interval_microseconds": [
            evaluation_start,
            evaluation_end,
        ],
        "reference_line_ids": list(LINE_IDS),
        "metrics": _metrics(reference_text, hypothesis),
        "mean_nearest_line_boundary_error_microseconds": (
            sum(boundary_errors) / len(boundary_errors)
            if boundary_errors
            else None
        ),
        "hypothesis": hypothesis,
        "stored_relative": stored.relative_to(root).as_posix(),
    }


def qualify(root: Path, fixture_root: Path) -> dict[str, object]:
    root.mkdir(parents=True, exist_ok=True)
    activity_provider = SileroSpeechActivityProvider()
    transcription_provider = OpenAIWhisperTranscriptionProvider()
    results = [
        qualify_variant(
            fixture_root,
            root,
            variant,
            activity_provider,
            transcription_provider,
        )
        for variant in VARIANTS
    ]
    assertions = {
        "all_responses_complete": all(
            item["response_complete"] for item in results
        ),
        "all_sources_unchanged": all(
            item["source_unchanged"] for item in results
        ),
        "all_raw_evidence_retained": all(
            item["raw_evidence_retained"] for item in results
        ),
        "all_second_runs_reused": all(
            item["cache_second_reused"] for item in results
        ),
        "all_repeated_responses_stable": all(
            item["stable_repeated_response"] for item in results
        ),
        "all_variants_have_text": all(
            item["selected_candidate_count"] > 0 for item in results
        ),
        "all_variants_have_word_observations": all(
            item["word_observation_count"] > 0 for item in results
        ),
    }
    return {
        "qualification": "phase-2-initial-transcription-provider",
        "status": "passed" if all(assertions.values()) else "failed",
        "provider": transcription_provider.capabilities.model_dump(
            mode="json"
        ),
        "reference_policy": (
            "Public project-authored line text and schedules prepared before "
            "provider selection; evaluation excerpt is L001-L005."
        ),
        "results": results,
        "assertions": assertions,
        "limitations": [
            "WER, CER, and boundary measurements are controlled-excerpt "
            "observations, not general performance claims.",
            "Line schedules select the evaluation range but do not prompt "
            "or otherwise supply reference text to the provider.",
            "Nearest-line-boundary error is not segment assignment accuracy.",
            "Only one provider candidate is available in this slice.",
            "Hidden analytical references were not read.",
        ],
    }


def markdown(report: dict[str, object]) -> str:
    lines = [
        "# Phase 2 initial transcription-provider qualification",
        "",
        f"Status: **{str(report['status']).upper()}**",
        "",
        "| Variant | WER | CER | Observations | Words | Unresolved |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for item in report["results"]:
        metrics = item["metrics"]
        lines.append(
            f"| `{item['variant']}` | {metrics['word_error_rate']:.4f} | "
            f"{metrics['character_error_rate']:.4f} | "
            f"{item['observation_count']} | "
            f"{item['word_observation_count']} | "
            f"{item['unresolved_observation_count']} |"
        )
    lines.extend(
        [
            "",
            "The measurements cover public lines L001-L005 in each controlled "
            "variant. They qualify provider execution, evidence capture, "
            "mapping, failure boundaries, and cache reuse; they do not create "
            "canonical transcript text or establish general accuracy.",
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
