"""Qualify append-only human correction and corrected transcript views."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from qualify_phase2_transcript_assembly import qualify as qualify_assembly
from ratiocinatus.correction_contracts import (
    CorrectionActor,
    CorrectionActorKind,
    CorrectionType,
    TranscriptCorrectionDraft,
    TranscriptSegmentProposal,
)
from ratiocinatus.corrections import (
    _state_from_segment,
    apply_correction_batch,
    prepare_correction_batch,
)
from ratiocinatus.kernel import canonical_bytes, load_contract
from ratiocinatus.media import sha256_file
from ratiocinatus.transcript_contracts import TranscriptAssembly

CORRECTED_AT = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)


def qualify(root: Path, fixture_root: Path) -> dict[str, object]:
    source = qualify_assembly(root, fixture_root)
    results: list[dict[str, object]] = []
    for item in source["results"]:
        variant = item["variant"]
        assembly_root = root / item["stored_relative"]
        assembly_path = assembly_root / "assembly.json"
        assembly = load_contract(
            assembly_path.read_bytes(), TranscriptAssembly
        )
        before = sha256_file(assembly_path)
        state_by_id = {
            state.artifact_id: state
            for state in _state_from_segment(assembly)
        }
        target_index = next(
            (
                index
                for index, segment in enumerate(assembly.segments[:-1])
                if "instead of 8p." in segment.proposed_text
                and assembly.segments[index + 1].proposed_text.strip() == "M."
            ),
            None,
        )
        if target_index is None:
            raise RuntimeError(
                f"{variant} controlled transcript lacks expected split "
                "'8p.' / 'M.' machine observation"
            )
        targets = assembly.segments[target_index : target_index + 2]
        prior_values = tuple(state_by_id[item.segment_id] for item in targets)
        first, second = prior_values
        normalized_start = first.normalized_audio_interval.start_microseconds
        normalized_end = (
            second.normalized_audio_interval.start_microseconds
            + second.normalized_audio_interval.duration_microseconds
        )
        source_start = first.source_interval.start_microseconds
        source_end = (
            second.source_interval.start_microseconds
            + second.source_interval.duration_microseconds
        )
        corrected_text = first.text.replace("8p.", "8 p.m.")
        proposal = TranscriptSegmentProposal(
            source_interval=first.source_interval.model_copy(
                update={"duration_microseconds": source_end - source_start}
            ),
            normalized_audio_interval=(
                first.normalized_audio_interval.model_copy(
                    update={
                        "duration_microseconds": normalized_end - normalized_start
                    }
                )
            ),
            text=corrected_text,
            normalized_text=" ".join(corrected_text.split()),
            language_claim=first.language_claim,
        )
        draft = TranscriptCorrectionDraft(
            target_version_id=assembly.version.version_id,
            correction_type=CorrectionType.MERGE,
            target_artifact_ids=tuple(item.artifact_id for item in prior_values),
            prior_values=prior_values,
            proposed_values=(proposal,),
            affected_source_interval=proposal.source_interval,
            actor=CorrectionActor(
                kind=CorrectionActorKind.HUMAN,
                actor_id="controlled-reviewer",
                display_name="Controlled qualification reviewer",
            ),
            corrected_at=CORRECTED_AT,
            reason=(
                "Restore the public L001 orthography '8 p.m.' in the "
                "controlled machine transcript."
            ),
            evidence_or_review_references=("public-line:L001",),
        )
        batch = prepare_correction_batch(
            assembly.version.version_id, (draft,)
        )
        batch_path = root / "correction-inputs" / f"{variant}.json"
        batch_path.parent.mkdir(parents=True, exist_ok=True)
        batch_path.write_bytes(canonical_bytes(batch))
        revision, report, stored, first_reused = apply_correction_batch(
            assembly_root,
            batch_path,
            root / "phase2" / variant,
        )
        repeated = apply_correction_batch(
            assembly_root,
            batch_path,
            root / "phase2" / variant,
        )
        results.append(
            {
                "variant": variant,
                "revision_id": revision.revision_id,
                "base_version_id": revision.base_version_id,
                "resulting_version_id": revision.version.version_id,
                "version_predecessor_valid": (
                    revision.version.predecessor_version_id
                    == revision.base_version_id
                ),
                "human_correction_count": report.human_correction_count,
                "automated_correction_count": (
                    report.automated_correction_count
                ),
                "original_text_retained": (
                    "8p. M."
                    in revision.original_machine_view.rendered_text
                ),
                "corrected_text_visible": (
                    "8 p.m."
                    in revision.current_corrected_view.rendered_text
                ),
                "difference_entry_count": len(
                    revision.difference_report.entries
                ),
                "history_correction_count": len(
                    revision.correction_history.corrections
                ),
                "corrected_segment_words_withheld": not any(
                    word_id
                    in revision.current_corrected_view.retained_word_ids
                    for prior in prior_values
                    for word_id in prior.retained_word_ids
                ),
                "base_assembly_unchanged": (
                    before == sha256_file(assembly_path)
                ),
                "cache_first_reused": first_reused,
                "cache_second_reused": repeated[3],
                "stable_repeated_revision": repeated[0] == revision,
                "stored_relative": stored.relative_to(root).as_posix(),
            }
        )
    assertions = {
        "source_assembly_qualification_passed": source["status"] == "passed",
        "all_base_assemblies_unchanged": all(
            item["base_assembly_unchanged"] for item in results
        ),
        "all_successor_lineages_valid": all(
            item["version_predecessor_valid"] for item in results
        ),
        "all_corrections_human_only": all(
            item["human_correction_count"] == 1
            and item["automated_correction_count"] == 0
            for item in results
        ),
        "all_original_and_current_views_distinct": all(
            item["original_text_retained"]
            and item["corrected_text_visible"]
            for item in results
        ),
        "all_differences_and_histories_complete": all(
            item["difference_entry_count"] == 1
            and item["history_correction_count"] == 1
            for item in results
        ),
        "all_invalidated_word_claims_withheld": all(
            item["corrected_segment_words_withheld"] for item in results
        ),
        "all_second_runs_reused": all(
            item["cache_second_reused"] for item in results
        ),
        "all_repeated_revisions_stable": all(
            item["stable_repeated_revision"] for item in results
        ),
    }
    return {
        "qualification": "phase-2-append-only-transcript-corrections",
        "status": "passed" if all(assertions.values()) else "failed",
        "correction_scope": (
            "One controlled human merge per variant restores the public "
            "L001 orthography '8 p.m.' from the observed '8p. M.'."
        ),
        "results": results,
        "assertions": assertions,
        "limitations": [
            "This qualification demonstrates correction mechanics and lineage, "
            "not independent transcript accuracy.",
            "Text-changing corrections conservatively withhold inherited word "
            "evidence from the corrected view until it is re-aligned.",
            "Subtitle export is qualified separately as a presentation derivative.",
        ],
    }


def markdown(report: dict[str, object]) -> str:
    lines = [
        "# Phase 2 append-only transcript-correction qualification",
        "",
        f"Status: **{str(report['status']).upper()}**",
        "",
        "| Variant | Human | Automated | Original retained | Corrected visible | Cache |",
        "|---|---:|---:|---|---|---|",
    ]
    for item in report["results"]:
        lines.append(
            f"| `{item['variant']}` | {item['human_correction_count']} | "
            f"{item['automated_correction_count']} | "
            f"{item['original_text_retained']} | "
            f"{item['corrected_text_visible']} | "
            f"{'reused' if item['cache_second_reused'] else 'miss'} |"
        )
    lines.extend(
        [
            "",
            "The original machine text remains unchanged. Each corrected view "
            "is a successor-version overlay with a persisted human correction, "
            "difference entry, and history record.",
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
