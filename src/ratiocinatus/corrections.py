"""Deterministic append-only transcript correction application."""

from __future__ import annotations

import os
import unicodedata
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .correction_contracts import (
    CorrectionActorKind,
    CorrectionHistory,
    CorrectionPolicy,
    CorrectionType,
    TranscriptCorrection,
    TranscriptCorrectionBatch,
    TranscriptCorrectionDraft,
    TranscriptDifferenceEntry,
    TranscriptDifferenceReport,
    TranscriptRevision,
    TranscriptRevisionReport,
    TranscriptSegmentProposal,
    TranscriptSegmentState,
    TranscriptView,
    TranscriptViewKind,
)
from .transcript_assembly import (
    TranscriptAssemblyIntegrityError,
    _verify_persisted as _verify_persisted_assembly,
    validate_transcript_assembly,
)
from .transcript_contracts import (
    TranscriptArtifactDigest,
    TranscriptAssembly,
    TranscriptVersion,
)


class TranscriptCorrectionIntegrityError(RuntimeError):
    pass


def _atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.partial-{uuid.uuid4().hex}")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _seal(model: Any) -> Any:
    payload = model.model_dump(mode="json")
    payload.pop("integrity_sha256")
    return model.model_copy(update={"integrity_sha256": canonical_hash(payload)})


def _verify_seal(model: Any, label: str) -> None:
    payload = model.model_dump(mode="json")
    actual = payload.pop("integrity_sha256")
    if canonical_hash(payload) != actual:
        raise TranscriptCorrectionIntegrityError(
            f"{label} integrity hash does not match its content"
        )


def prepare_correction_batch(
    target_version_id: str,
    corrections: tuple[TranscriptCorrectionDraft, ...],
    *,
    policy: CorrectionPolicy | None = None,
) -> TranscriptCorrectionBatch:
    policy = policy or CorrectionPolicy()
    batch_id = typed_id(
        "correctionbatch",
        target_version_id,
        policy.model_dump(mode="json"),
        tuple(item.model_dump(mode="json") for item in corrections),
    )
    return TranscriptCorrectionBatch(
        batch_id=batch_id,
        target_version_id=target_version_id,
        policy=policy,
        corrections=corrections,
    )


def _state_from_segment(assembly: TranscriptAssembly) -> tuple[TranscriptSegmentState, ...]:
    words: dict[str, list[str]] = {}
    for word in assembly.words:
        words.setdefault(word.segment_id, []).append(word.word_id)
    return tuple(
        TranscriptSegmentState(
            artifact_id=segment.segment_id,
            source_interval=segment.source_interval,
            normalized_audio_interval=segment.normalized_audio_interval,
            text=segment.proposed_text,
            normalized_text=segment.normalized_text,
            language_claim=segment.language_claim,
            origin_segment_ids=(segment.segment_id,),
            retained_word_ids=tuple(words.get(segment.segment_id, ())),
        )
        for segment in assembly.segments
    )


def _view(
    *,
    version_id: str,
    kind: TranscriptViewKind,
    segments: tuple[TranscriptSegmentState, ...],
    created_at,
) -> TranscriptView:
    value = TranscriptView(
        view_id=typed_id(
            "txview",
            version_id,
            kind.value,
            tuple(item.model_dump(mode="json") for item in segments),
        ),
        version_id=version_id,
        view_kind=kind,
        segments=segments,
        retained_word_ids=tuple(
            word_id for item in segments for word_id in item.retained_word_ids
        ),
        rendered_text=" ".join(item.text.strip() for item in segments).strip(),
        created_at=created_at,
        integrity_sha256="0" * 64,
    )
    return _seal(value)


def _interval_end(interval) -> int:
    return interval.start_microseconds + interval.duration_microseconds


def _contains(outer, inner) -> bool:
    return (
        outer.start_microseconds <= inner.start_microseconds
        and _interval_end(inner) <= _interval_end(outer)
    )


def _ordered_contiguous(values: tuple[Any, ...], field: str) -> bool:
    intervals = [getattr(item, field) for item in values]
    return all(
        _interval_end(left) == right.start_microseconds
        for left, right in zip(intervals, intervals[1:])
    )


def _same_content(
    prior: TranscriptSegmentState,
    proposed: TranscriptSegmentProposal,
    *,
    ignore: str,
) -> bool:
    comparisons = {
        "text": prior.text == proposed.text,
        "normalized_text": prior.normalized_text == proposed.normalized_text,
        "language": prior.language_claim == proposed.language_claim,
        "source_interval": prior.source_interval == proposed.source_interval,
        "normalized_interval": (
            prior.normalized_audio_interval == proposed.normalized_audio_interval
        ),
    }
    return all(value for key, value in comparisons.items() if key != ignore)


def _validate_shape(
    draft: TranscriptCorrectionDraft,
    current: dict[str, TranscriptSegmentState],
    assembly: TranscriptAssembly,
) -> None:
    kind = draft.correction_type
    prior = draft.prior_values
    proposed = draft.proposed_values
    for artifact_id, expected in zip(draft.target_artifact_ids, prior):
        if artifact_id not in current:
            raise TranscriptCorrectionIntegrityError(
                f"correction target is unknown: {artifact_id}"
            )
        if current[artifact_id] != expected:
            raise TranscriptCorrectionIntegrityError(
                f"stale or incorrect prior value for {artifact_id}"
            )
    ordered_ids = tuple(
        item.artifact_id
        for item in sorted(
            current.values(),
            key=lambda value: (
                value.normalized_audio_interval.start_microseconds,
                value.artifact_id,
            ),
        )
    )
    if prior:
        positions = [ordered_ids.index(item.artifact_id) for item in prior]
        if positions != sorted(positions) or (
            len(positions) > 1
            and positions != list(range(positions[0], positions[-1] + 1))
        ):
            raise TranscriptCorrectionIntegrityError(
                "correction targets must be ordered adjacent transcript artifacts"
            )
    if kind == CorrectionType.INSERTION:
        if len(proposed) < 1 or draft.target_artifact_ids[0] not in current:
            raise TranscriptCorrectionIntegrityError(
                "insertion requires an existing anchor and proposed segment"
            )
    elif kind == CorrectionType.DELETION:
        if not prior or proposed:
            raise TranscriptCorrectionIntegrityError(
                "deletion requires prior values and no proposed value"
            )
    elif kind == CorrectionType.REPLACEMENT:
        if len(prior) != 1 or len(proposed) != 1:
            raise TranscriptCorrectionIntegrityError(
                "replacement requires one prior and one proposed segment"
            )
        if (
            prior[0].source_interval != proposed[0].source_interval
            or prior[0].normalized_audio_interval
            != proposed[0].normalized_audio_interval
            or prior[0].text == proposed[0].text
        ):
            raise TranscriptCorrectionIntegrityError(
                "replacement cannot change segment boundaries"
            )
    elif kind == CorrectionType.SPLIT:
        if (
            len(prior) != 1
            or len(proposed) < 2
            or not _ordered_contiguous(proposed, "source_interval")
            or not _ordered_contiguous(proposed, "normalized_audio_interval")
            or proposed[0].source_interval.start_microseconds
            != prior[0].source_interval.start_microseconds
            or _interval_end(proposed[-1].source_interval)
            != _interval_end(prior[0].source_interval)
            or proposed[0].normalized_audio_interval.start_microseconds
            != prior[0].normalized_audio_interval.start_microseconds
            or _interval_end(proposed[-1].normalized_audio_interval)
            != _interval_end(prior[0].normalized_audio_interval)
        ):
            raise TranscriptCorrectionIntegrityError(
                "split proposals must contiguously and exactly cover one target"
            )
    elif kind == CorrectionType.MERGE:
        if (
            len(prior) < 2
            or len(proposed) != 1
            or proposed[0].source_interval.start_microseconds
            != prior[0].source_interval.start_microseconds
            or _interval_end(proposed[0].source_interval)
            != _interval_end(prior[-1].source_interval)
            or proposed[0].normalized_audio_interval.start_microseconds
            != prior[0].normalized_audio_interval.start_microseconds
            or _interval_end(proposed[0].normalized_audio_interval)
            != _interval_end(prior[-1].normalized_audio_interval)
        ):
            raise TranscriptCorrectionIntegrityError(
                "merge must replace adjacent targets with their exact outer span"
            )
    elif kind == CorrectionType.BOUNDARY_ADJUSTMENT:
        if (
            len(prior) != 1
            or len(proposed) != 1
            or prior[0].text != proposed[0].text
            or prior[0].normalized_text != proposed[0].normalized_text
            or prior[0].language_claim != proposed[0].language_claim
            or (
                prior[0].source_interval == proposed[0].source_interval
                and prior[0].normalized_audio_interval
                == proposed[0].normalized_audio_interval
            )
        ):
            raise TranscriptCorrectionIntegrityError(
                "boundary adjustment must change only mapped intervals"
            )
    elif kind == CorrectionType.LANGUAGE_CORRECTION:
        if (
            len(prior) != 1
            or len(proposed) != 1
            or not _same_content(prior[0], proposed[0], ignore="language")
            or prior[0].language_claim == proposed[0].language_claim
        ):
            raise TranscriptCorrectionIntegrityError(
                "language correction must change only the language claim"
            )
    elif kind == CorrectionType.NORMALIZATION_ONLY:
        if (
            len(prior) != 1
            or len(proposed) != 1
            or not _same_content(
                prior[0], proposed[0], ignore="normalized_text"
            )
            or prior[0].normalized_text == proposed[0].normalized_text
        ):
            raise TranscriptCorrectionIntegrityError(
                "normalization-only correction must change only normalized text"
            )
    elif kind == CorrectionType.UNCERTAINTY_ANNOTATION:
        if (
            len(prior) != 1
            or len(proposed) != 1
            or not _same_content(prior[0], proposed[0], ignore="")
            or not proposed[0].uncertainty_annotation
        ):
            raise TranscriptCorrectionIntegrityError(
                "uncertainty correction must preserve content and add annotation"
            )
    elif kind == CorrectionType.RESTORE_EARLIER_CANDIDATE:
        if len(prior) != 1 or len(proposed) != 1:
            raise TranscriptCorrectionIntegrityError(
                "candidate restoration requires one target and proposal"
            )
        original_id = prior[0].origin_segment_ids[0]
        segment = next(
            (item for item in assembly.segments if item.segment_id == original_id),
            None,
        )
        if (
            segment is None
            or proposed[0].restored_candidate_id
            not in segment.alternative_candidate_ids
            or prior[0].source_interval != proposed[0].source_interval
            or prior[0].normalized_audio_interval
            != proposed[0].normalized_audio_interval
        ):
            raise TranscriptCorrectionIntegrityError(
                "restored candidate is not a retained alternative"
            )

    if kind not in {
        CorrectionType.NORMALIZATION_ONLY,
        CorrectionType.UNCERTAINTY_ANNOTATION,
    }:
        for value in proposed:
            if value.normalized_text != _normalize(value.text):
                raise TranscriptCorrectionIntegrityError(
                    "proposed normalized text does not match assembly policy"
                )
    mapping_offset = (
        assembly.segments[0].source_interval.start_microseconds
        - assembly.segments[0].normalized_audio_interval.start_microseconds
    ) if assembly.segments else 0
    for value in proposed:
        if (
            value.source_interval.start_microseconds
            - value.normalized_audio_interval.start_microseconds
            != mapping_offset
        ):
            raise TranscriptCorrectionIntegrityError(
                "proposed segment source mapping is invalid"
            )
    for value in (*prior, *proposed):
        if not _contains(
            draft.affected_source_interval, value.source_interval
        ):
            raise TranscriptCorrectionIntegrityError(
                "affected source interval does not cover correction values"
            )


def _result_state(
    proposal: TranscriptSegmentProposal,
    *,
    correction_id: str,
    position: int,
    prior: tuple[TranscriptSegmentState, ...],
    kind: CorrectionType,
) -> TranscriptSegmentState:
    origins = tuple(
        dict.fromkeys(
            segment_id
            for item in prior
            for segment_id in item.origin_segment_ids
        )
    )
    retained: tuple[str, ...] = ()
    if kind in {
        CorrectionType.LANGUAGE_CORRECTION,
        CorrectionType.NORMALIZATION_ONLY,
        CorrectionType.UNCERTAINTY_ANNOTATION,
    }:
        retained = tuple(
            word_id for item in prior for word_id in item.retained_word_ids
        )

    corrections = (correction_id,)
    inherited_corrections = tuple(
        dict.fromkeys(
            correction
            for item in prior
            for correction in item.applied_correction_ids
        )
    )
    annotations = tuple(
        annotation
        for item in prior
        for annotation in item.uncertainty_annotations
    )
    if proposal.uncertainty_annotation:
        annotations += (proposal.uncertainty_annotation,)
    artifact_id = typed_id(
        "txviewsegment",
        correction_id,
        position,
        proposal.model_dump(mode="json"),
        origins,
    )
    return TranscriptSegmentState(
        artifact_id=artifact_id,
        source_interval=proposal.source_interval,
        normalized_audio_interval=proposal.normalized_audio_interval,
        text=proposal.text,
        normalized_text=proposal.normalized_text,
        language_claim=proposal.language_claim,
        origin_segment_ids=origins,
        retained_word_ids=retained,
        applied_correction_ids=inherited_corrections + corrections,
        uncertainty_annotations=annotations,
    )


def _validate_view_order(states: tuple[TranscriptSegmentState, ...]) -> None:
    previous_end = 0
    for state in states:
        start = state.normalized_audio_interval.start_microseconds
        if start < previous_end:
            raise TranscriptCorrectionIntegrityError(
                "corrected transcript segments overlap or regress"
            )
        previous_end = _interval_end(state.normalized_audio_interval)


def build_transcript_revision(
    assembly: TranscriptAssembly,
    batch: TranscriptCorrectionBatch,
) -> tuple[TranscriptRevision, TranscriptRevisionReport]:
    validate_transcript_assembly(assembly)
    if batch.target_version_id != assembly.version.version_id:
        raise TranscriptCorrectionIntegrityError(
            "correction batch targets an unknown transcript version"
        )
    expected_batch = prepare_correction_batch(
        batch.target_version_id,
        batch.corrections,
        policy=batch.policy,
    )
    if expected_batch.batch_id != batch.batch_id:
        raise TranscriptCorrectionIntegrityError(
            "correction batch identity does not match its content"
        )
    target_ids = [
        target
        for correction in batch.corrections
        for target in correction.target_artifact_ids
    ]
    if len(target_ids) != len(set(target_ids)):
        raise TranscriptCorrectionIntegrityError(
            "correction batch contains conflicting target history"
        )
    for draft in batch.corrections:
        if (
            draft.actor.kind == CorrectionActorKind.HUMAN
            and not batch.policy.allow_human
        ) or (
            draft.actor.kind == CorrectionActorKind.AUTOMATED_PROCESS
            and not batch.policy.allow_automated_process
        ):
            raise TranscriptCorrectionIntegrityError(
                "correction actor is prohibited by policy"
            )
        if (
            batch.policy.require_evidence_or_review_reference
            and not draft.evidence_or_review_references
        ):
            raise TranscriptCorrectionIntegrityError(
                "correction requires an evidence or review reference"
            )

    original_states = _state_from_segment(assembly)
    current = {item.artifact_id: item for item in original_states}
    correction_ids = tuple(
        typed_id(
            "correction",
            batch.batch_id,
            position,
            draft.model_dump(mode="json"),
        )
        for position, draft in enumerate(batch.corrections)
    )
    resulting_version_id = typed_id(
        "txversion",
        assembly.version.version_id,
        batch.batch_id,
        correction_ids,
    )
    records: list[TranscriptCorrection] = []
    differences: list[TranscriptDifferenceEntry] = []

    for correction_id, draft in zip(correction_ids, batch.corrections):
        _validate_shape(draft, current, assembly)
        result_states = tuple(
            _result_state(
                proposal,
                correction_id=correction_id,
                position=position,
                prior=draft.prior_values,
                kind=draft.correction_type,
            )
            for position, proposal in enumerate(draft.proposed_values)
        )
        if draft.correction_type != CorrectionType.INSERTION:
            for target in draft.target_artifact_ids:
                current.pop(target)
        for state in result_states:
            current[state.artifact_id] = state
        record = _seal(
            TranscriptCorrection(
                correction_id=correction_id,
                target_version_id=batch.target_version_id,
                resulting_version_id=resulting_version_id,
                correction_type=draft.correction_type,
                target_artifact_ids=draft.target_artifact_ids,
                prior_values=draft.prior_values,
                proposed_values=draft.proposed_values,
                resulting_segment_ids=tuple(
                    item.artifact_id for item in result_states
                ),
                affected_source_interval=draft.affected_source_interval,
                actor=draft.actor,
                corrected_at=draft.corrected_at,
                reason=draft.reason,
                evidence_or_review_references=(
                    draft.evidence_or_review_references
                ),
                integrity_sha256="0" * 64,
            )
        )
        records.append(record)
        differences.append(
            TranscriptDifferenceEntry(
                correction_id=correction_id,
                correction_type=draft.correction_type,
                prior_values=draft.prior_values,
                proposed_values=result_states,
                affected_source_interval=draft.affected_source_interval,
                actor=draft.actor,
                reason=draft.reason,
            )
        )

    corrected_states = tuple(
        sorted(
            current.values(),
            key=lambda item: (
                item.normalized_audio_interval.start_microseconds,
                item.artifact_id,
            ),
        )
    )
    _validate_view_order(corrected_states)
    if any(
        _interval_end(item.normalized_audio_interval)
        > assembly.normalized_audio_duration_microseconds
        or item.source_interval.start_microseconds
        != item.normalized_audio_interval.start_microseconds
        + assembly.source_mapping_offset_microseconds
        for item in corrected_states
    ):
        raise TranscriptCorrectionIntegrityError(
            "corrected transcript segment exceeds base assembly addressing"
        )
    created_at = max(item.corrected_at for item in batch.corrections)
    original_view = _view(
        version_id=assembly.version.version_id,
        kind=TranscriptViewKind.ORIGINAL_MACHINE,
        segments=original_states,
        created_at=assembly.assembled_at,
    )
    corrected_view = _view(
        version_id=resulting_version_id,
        kind=TranscriptViewKind.CURRENT_CORRECTED,
        segments=corrected_states,
        created_at=created_at,
    )
    correction_digests = tuple(
        TranscriptArtifactDigest(
            artifact_id=item.correction_id,
            content_sha256=canonical_hash(item),
        )
        for item in records
    )
    word_by_id = {item.word_id: item for item in assembly.words}
    retained_words = tuple(
        TranscriptArtifactDigest(
            artifact_id=word_id,
            content_sha256=canonical_hash(word_by_id[word_id]),
        )
        for word_id in corrected_view.retained_word_ids
    )
    version = _seal(
        TranscriptVersion(
            version_id=resulting_version_id,
            corpus_id=assembly.version.corpus_id,
            transcription_response_id=(
                assembly.version.transcription_response_id
            ),
            predecessor_version_id=assembly.version.version_id,
            version_kind="corrected",
            assembly_policy=assembly.version.assembly_policy,
            segments=tuple(
                TranscriptArtifactDigest(
                    artifact_id=item.artifact_id,
                    content_sha256=canonical_hash(item),
                )
                for item in corrected_states
            ),
            words=retained_words,
            low_confidence_regions=assembly.version.low_confidence_regions,
            corrections=correction_digests,
            created_at=created_at,
            integrity_sha256="0" * 64,
        )
    )
    difference = _seal(
        TranscriptDifferenceReport(
            difference_id=typed_id(
                "txdiff", assembly.version.version_id, resulting_version_id
            ),
            base_version_id=assembly.version.version_id,
            resulting_version_id=resulting_version_id,
            entries=tuple(differences),
            generated_at=created_at,
            integrity_sha256="0" * 64,
        )
    )
    history = _seal(
        CorrectionHistory(
            history_id=typed_id(
                "txhistory", assembly.version.version_id, resulting_version_id
            ),
            base_version_id=assembly.version.version_id,
            current_version_id=resulting_version_id,
            version_chain=(
                assembly.version.version_id,
                resulting_version_id,
            ),
            corrections=correction_digests,
            generated_at=created_at,
            integrity_sha256="0" * 64,
        )
    )
    revision_id = typed_id(
        "txrevision",
        assembly.assembly_id,
        batch.batch_id,
        resulting_version_id,
    )
    revision = _seal(
        TranscriptRevision(
            revision_id=revision_id,
            base_assembly_id=assembly.assembly_id,
            base_version_id=assembly.version.version_id,
            version=version,
            corrections=tuple(records),
            original_machine_view=original_view,
            current_corrected_view=corrected_view,
            difference_report=difference,
            correction_history=history,
            status=assembly.status,
            created_at=created_at,
            integrity_sha256="0" * 64,
        )
    )
    counts = Counter(item.correction_type for item in records)
    report = TranscriptRevisionReport(
        report_id=typed_id("txrevisionreport", revision_id),
        revision_id=revision_id,
        base_version_id=assembly.version.version_id,
        resulting_version_id=resulting_version_id,
        generated_at=created_at,
        correction_count=len(records),
        human_correction_count=sum(
            item.actor.kind == CorrectionActorKind.HUMAN for item in records
        ),
        automated_correction_count=sum(
            item.actor.kind == CorrectionActorKind.AUTOMATED_PROCESS
            for item in records
        ),
        affected_duration_microseconds=sum(
            item.affected_source_interval.duration_microseconds
            for item in records
        ),
        correction_types=tuple(
            (kind, counts[kind]) for kind in sorted(counts, key=lambda x: x.value)
        ),
        original_segment_count=len(original_states),
        corrected_segment_count=len(corrected_states),
        status=revision.status,
    )
    validate_transcript_revision(revision, assembly=assembly)
    return revision, report


def validate_transcript_revision(
    revision: TranscriptRevision,
    *,
    assembly: TranscriptAssembly | None = None,
) -> None:
    _verify_seal(revision, "transcript revision")
    _verify_seal(revision.version, "corrected transcript version")
    _verify_seal(revision.original_machine_view, "original machine view")
    _verify_seal(revision.current_corrected_view, "current corrected view")
    _verify_seal(revision.difference_report, "difference report")
    _verify_seal(revision.correction_history, "correction history")
    for correction in revision.corrections:
        _verify_seal(correction, correction.correction_id)
        if (
            correction.target_version_id != revision.base_version_id
            or correction.resulting_version_id != revision.version.version_id
        ):
            raise TranscriptCorrectionIntegrityError(
                "correction version lineage is incompatible"
            )
    if revision.version.version_kind != "corrected" or (
        revision.version.predecessor_version_id != revision.base_version_id
    ):
        raise TranscriptCorrectionIntegrityError(
            "corrected version predecessor lineage is invalid"
        )
    if (
        revision.original_machine_view.version_id != revision.base_version_id
        or revision.original_machine_view.view_kind
        != TranscriptViewKind.ORIGINAL_MACHINE
        or revision.current_corrected_view.version_id
        != revision.version.version_id
        or revision.current_corrected_view.view_kind
        != TranscriptViewKind.CURRENT_CORRECTED
        or revision.correction_history.version_chain
        != (revision.base_version_id, revision.version.version_id)
    ):
        raise TranscriptCorrectionIntegrityError(
            "revision views or history have incompatible version lineage"
        )
    expected_corrections = tuple(
        TranscriptArtifactDigest(
            artifact_id=item.correction_id,
            content_sha256=canonical_hash(item),
        )
        for item in revision.corrections
    )
    if (
        revision.version.corrections != expected_corrections
        or revision.correction_history.corrections != expected_corrections
    ):
        raise TranscriptCorrectionIntegrityError(
            "corrected version correction digests disagree"
        )
    _validate_view_order(revision.original_machine_view.segments)
    _validate_view_order(revision.current_corrected_view.segments)
    expected_segments = tuple(
        TranscriptArtifactDigest(
            artifact_id=item.artifact_id,
            content_sha256=canonical_hash(item),
        )
        for item in revision.current_corrected_view.segments
    )
    if revision.version.segments != expected_segments:
        raise TranscriptCorrectionIntegrityError(
            "corrected version segment digests disagree with current view"
        )
    record_ids = tuple(item.correction_id for item in revision.corrections)
    if tuple(
        item.correction_id for item in revision.difference_report.entries
    ) != record_ids:
        raise TranscriptCorrectionIntegrityError(
            "difference entries do not match correction history"
        )
    resulting_ids = {
        item.artifact_id for item in revision.current_corrected_view.segments
    }
    if any(
        segment_id not in resulting_ids
        for correction in revision.corrections
        if correction.correction_type != CorrectionType.DELETION
        for segment_id in correction.resulting_segment_ids
    ):
        raise TranscriptCorrectionIntegrityError(
            "correction result references missing current segment"
        )
    if assembly is not None:
        validate_transcript_assembly(assembly)
        if (
            revision.base_assembly_id != assembly.assembly_id
            or revision.base_version_id != assembly.version.version_id
        ):
            raise TranscriptCorrectionIntegrityError(
                "revision belongs to another base assembly"
            )
        expected_original = _state_from_segment(assembly)
        if revision.original_machine_view.segments != expected_original:
            raise TranscriptCorrectionIntegrityError(
                "original machine view differs from base assembly"
            )


def _report_markdown(report: TranscriptRevisionReport) -> str:
    return "\n".join(
        [
            "# Phase 2 transcript revision report",
            "",
            f"Status: **{report.status.value.upper()}**",
            "",
            f"Revision: `{report.revision_id}`",
            "",
            f"- Corrections: {report.correction_count}",
            f"- Human corrections: {report.human_correction_count}",
            f"- Automated corrections: {report.automated_correction_count}",
            f"- Original segments: {report.original_segment_count}",
            f"- Current segments: {report.corrected_segment_count}",
            "",
            "The original machine view remains embedded and unchanged. "
            "The current view is an append-only correction overlay.",
            "",
        ]
    )


def _verify_persisted_revision(
    root: Path, revision: TranscriptRevision
) -> None:
    artifacts = (
        ("version.json", TranscriptVersion, revision.version),
        (
            "views/original-machine.json",
            TranscriptView,
            revision.original_machine_view,
        ),
        (
            "views/current-corrected.json",
            TranscriptView,
            revision.current_corrected_view,
        ),
        (
            "difference.json",
            TranscriptDifferenceReport,
            revision.difference_report,
        ),
        (
            "correction-history.json",
            CorrectionHistory,
            revision.correction_history,
        ),
    )
    for relative, model, expected in artifacts:
        try:
            actual = load_contract((root / relative).read_bytes(), model)
        except Exception as exc:
            raise TranscriptCorrectionIntegrityError(
                f"persisted revision artifact is missing or malformed: {relative}"
            ) from exc
        if actual != expected:
            raise TranscriptCorrectionIntegrityError(
                f"persisted revision artifact differs: {relative}"
            )
    for correction in revision.corrections:
        relative = f"corrections/{correction.correction_id}.json"
        try:
            actual = load_contract(
                (root / relative).read_bytes(), TranscriptCorrection
            )
        except Exception as exc:
            raise TranscriptCorrectionIntegrityError(
                f"persisted correction is missing or malformed: {relative}"
            ) from exc
        if actual != correction:
            raise TranscriptCorrectionIntegrityError(
                f"persisted correction differs: {relative}"
            )

def apply_correction_batch(
    assembly_root: Path,
    batch_path: Path,
    destination: Path,
) -> tuple[TranscriptRevision, TranscriptRevisionReport, Path, bool]:
    assembly_root = assembly_root.expanduser().resolve(strict=True)
    batch_path = batch_path.expanduser().resolve(strict=True)
    destination = destination.expanduser().resolve()
    if destination == assembly_root or assembly_root in destination.parents:
        raise ValueError(
            "correction output must not modify the base assembly directory"
        )
    assembly = load_contract(
        (assembly_root / "assembly.json").read_bytes(), TranscriptAssembly
    )
    validate_transcript_assembly(assembly)
    try:
        _verify_persisted_assembly(assembly_root, assembly)
    except TranscriptAssemblyIntegrityError as exc:
        raise TranscriptCorrectionIntegrityError(str(exc)) from exc
    batch = load_contract(
        batch_path.read_bytes(), TranscriptCorrectionBatch
    )
    revision, report = build_transcript_revision(assembly, batch)
    root = destination / "transcript-revisions" / revision.revision_id
    revision_path = root / "revision.json"
    report_path = root / "report.json"
    if revision_path.exists() or report_path.exists():
        if not revision_path.exists() or not report_path.exists():
            raise TranscriptCorrectionIntegrityError(
                "cached transcript revision is incomplete"
            )
        stored = load_contract(
            revision_path.read_bytes(), TranscriptRevision
        )
        stored_report = load_contract(
            report_path.read_bytes(), TranscriptRevisionReport
        )
        if stored != revision or stored_report != report:
            raise TranscriptCorrectionIntegrityError(
                "cached transcript revision is incompatible"
            )
        validate_transcript_revision(stored, assembly=assembly)
        _verify_persisted_revision(root, stored)
        return stored, stored_report, root, True

    _atomic(revision_path, canonical_bytes(revision))
    _atomic(root / "version.json", canonical_bytes(revision.version))
    for item in revision.corrections:
        _atomic(
            root / "corrections" / f"{item.correction_id}.json",
            canonical_bytes(item),
        )
    _atomic(
        root / "views" / "original-machine.json",
        canonical_bytes(revision.original_machine_view),
    )
    _atomic(
        root / "views" / "current-corrected.json",
        canonical_bytes(revision.current_corrected_view),
    )
    _atomic(
        root / "difference.json",
        canonical_bytes(revision.difference_report),
    )
    _atomic(
        root / "correction-history.json",
        canonical_bytes(revision.correction_history),
    )
    _atomic(report_path, canonical_bytes(report))
    _atomic(root / "report.md", _report_markdown(report).encode("utf-8"))
    return revision, report, root, False
