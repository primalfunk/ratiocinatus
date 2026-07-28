"""Deterministic Phase 4 turn-repair detection and successor records."""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path

from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase2_contracts import ConfidenceMeasure, ConfidenceOrigin
from .phase3_contracts import (
    DiarizationRun,
    SpeakerChangeBoundary,
    SpeakerTurn,
)
from .phase4_contracts import (
    UtteranceCorpus,
    UtteranceReviewStatus,
    UtteranceRun,
)
from .speaker_transcript_contracts import (
    SpeakerAttributionKind,
    SpeakerAttributionSpan,
    SpeakerLabeledTranscriptSegment,
    SpeakerLabeledTranscriptView,
)
from .transcript_contracts import TranscriptAssembly, TranscriptWord
from .turn_repair_contracts import (
    TurnRepairActionKind,
    TurnRepairConflict,
    TurnRepairConflictKind,
    TurnRepairCreationProcess,
    TurnRepairDecision,
    TurnRepairDecisionDisposition,
    TurnRepairPolicy,
    TurnRepairProposal,
    TurnRepairProposalDisposition,
    TurnRepairProposedChange,
    TurnRepairReport,
    TurnRepairRun,
    TurnRepairSuccessor,
)
from .utterance_segmentation import validate_utterance_corpus


class TurnRepairIntegrityError(RuntimeError):
    """Turn-repair evidence is corrupt or incompatible."""


def _atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.partial-{uuid.uuid4().hex}")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _seal(model, payload: dict):
    provisional = model(**payload, integrity_sha256="0" * 64)
    integrity = canonical_hash(
        provisional.model_dump(mode="json", exclude={"integrity_sha256"})
    )
    return model(**payload, integrity_sha256=integrity)


def _verify_seal(item, label: str) -> None:
    payload = item.model_dump(mode="json", exclude={"integrity_sha256"})
    if canonical_hash(payload) != item.integrity_sha256:
        raise TurnRepairIntegrityError(f"{label} integrity is invalid")


def _confidence(value: float | None, basis: str) -> ConfidenceMeasure:
    return ConfidenceMeasure(
        value=value,
        origin=(
            ConfidenceOrigin.DERIVED
            if value is not None
            else ConfidenceOrigin.UNAVAILABLE
        ),
        basis=basis,
    )


def _end(interval) -> int:
    return interval.start_microseconds + interval.duration_microseconds


def _conflict(
    corpus: UtteranceCorpus,
    kind: TurnRepairConflictKind,
    source_interval,
    normalized_interval,
    affected: tuple[str, ...],
    evidence: tuple[str, ...],
    contrary: tuple[str, ...],
    *,
    words: tuple[str, ...] = (),
    turns: tuple[str, ...] = (),
    boundaries: tuple[str, ...] = (),
    utterances: tuple[str, ...] = (),
) -> TurnRepairConflict:
    payload = {
        "conflict_id": typed_id(
            "turnconflict",
            corpus.corpus_id,
            kind.value,
            affected,
            source_interval.model_dump(mode="json"),
            normalized_interval.model_dump(mode="json"),
        ),
        "utterance_corpus_id": corpus.corpus_id,
        "kind": kind,
        "source_interval": source_interval,
        "normalized_audio_interval": normalized_interval,
        "affected_artifact_ids": tuple(dict.fromkeys(affected)),
        "transcript_word_ids": tuple(dict.fromkeys(words)),
        "speaker_turn_ids": tuple(dict.fromkeys(turns)),
        "speaker_boundary_ids": tuple(dict.fromkeys(boundaries)),
        "utterance_ids": tuple(dict.fromkeys(utterances)),
        "evidence_basis": evidence,
        "contrary_evidence": contrary,
        "review_status": UtteranceReviewStatus.REVIEW_REQUIRED,
    }
    return _seal(TurnRepairConflict, payload)


def _word_boundary_conflicts(
    corpus: UtteranceCorpus,
    assembly: TranscriptAssembly,
    diarization: DiarizationRun,
) -> tuple[TurnRepairConflict, ...]:
    owners = {
        word_id: utterance.utterance_id
        for utterance in corpus.utterances
        for component in utterance.components
        for word_id in component.transcript_word_ids
    }
    result: list[TurnRepairConflict] = []
    for boundary in diarization.boundaries:
        position = boundary.normalized_audio_microseconds
        for word in assembly.words:
            if not (
                word.normalized_audio_interval.start_microseconds
                < position
                < _end(word.normalized_audio_interval)
            ):
                continue
            utterance_id = owners.get(word.word_id)
            affected = (
                boundary.boundary_id,
                word.word_id,
                word.segment_id,
            ) + ((utterance_id,) if utterance_id is not None else ())
            result.append(
                _conflict(
                    corpus,
                    TurnRepairConflictKind.BOUNDARY_INSIDE_TRANSCRIPT_WORD,
                    word.source_interval,
                    word.normalized_audio_interval,
                    affected,
                    (
                        "speaker-change timestamp lies strictly inside word",
                        boundary.provider_basis,
                    ),
                    (
                        "word and speaker-boundary timing may both be uncertain",
                        word.timing_confidence.basis,
                    ),
                    words=(word.word_id,),
                    boundaries=(boundary.boundary_id,),
                    utterances=(
                        (utterance_id,) if utterance_id is not None else ()
                    ),
                )
            )
    return tuple(result)


def _internal_turn_boundary_conflicts(
    corpus: UtteranceCorpus,
    diarization: DiarizationRun,
) -> tuple[TurnRepairConflict, ...]:
    result: list[TurnRepairConflict] = []
    for turn in diarization.turns:
        start = turn.normalized_audio_interval.start_microseconds
        end = _end(turn.normalized_audio_interval)
        for boundary in diarization.boundaries:
            position = boundary.normalized_audio_microseconds
            if (
                boundary.boundary_id
                in {turn.start_boundary_id, turn.end_boundary_id}
                or not start < position < end
            ):
                continue
            result.append(
                _conflict(
                    corpus,
                    TurnRepairConflictKind.BOUNDARY_INSIDE_SPEAKER_TURN,
                    turn.source_interval,
                    turn.normalized_audio_interval,
                    (turn.turn_id, boundary.boundary_id),
                    (
                        "speaker-change boundary lies inside canonical turn",
                        boundary.provider_basis,
                    ),
                    (
                        "internal boundary may be a competing proposal",
                        turn.boundary_confidence.basis,
                    ),
                    turns=(turn.turn_id,),
                    boundaries=(boundary.boundary_id,),
                )
            )
    return tuple(result)


def _span_signature(span: SpeakerAttributionSpan) -> tuple:
    return (
        span.attribution_kind,
        span.identity_ids,
        span.reviewed_labels,
        span.original_machine_labels,
    )


def _segment_conflicts(
    corpus: UtteranceCorpus,
    speaker_view: SpeakerLabeledTranscriptView,
) -> tuple[TurnRepairConflict, ...]:
    utterances_by_word = {
        word_id: utterance.utterance_id
        for utterance in corpus.utterances
        for component in utterance.components
        for word_id in component.transcript_word_ids
    }
    result: list[TurnRepairConflict] = []
    for segment in speaker_view.segments:
        signatures = {_span_signature(item) for item in segment.attribution_spans}
        word_ids = tuple(
            dict.fromkeys(
                word_id
                for span in segment.attribution_spans
                for word_id in span.transcript_word_ids
            )
        )
        turn_ids = tuple(
            dict.fromkeys(
                turn_id
                for span in segment.attribution_spans
                for turn_id in span.speaker_turn_ids
            )
        )
        utterance_ids = tuple(
            dict.fromkeys(
                utterances_by_word[word_id]
                for word_id in word_ids
                if word_id in utterances_by_word
            )
        )
        if len(signatures) > 1:
            result.append(
                _conflict(
                    corpus,
                    TurnRepairConflictKind.TRANSCRIPT_SEGMENT_SPANS_SPEAKERS,
                    segment.source_interval,
                    segment.normalized_audio_interval,
                    (segment.segment_id,) + turn_ids + utterance_ids,
                    (
                        "one transcript segment contains distinct attribution spans",
                    ),
                    (
                        "segment boundaries are transcript-provider evidence",
                        "speaker spans remain provisional or review-derived",
                    ),
                    words=word_ids,
                    turns=turn_ids,
                    utterances=utterance_ids,
                )
            )
        for span in segment.attribution_spans:
            span_utterances = tuple(
                dict.fromkeys(
                    utterances_by_word[word_id]
                    for word_id in span.transcript_word_ids
                    if word_id in utterances_by_word
                )
            )
            if len(span.speaker_turn_ids) > 1:
                result.append(
                    _conflict(
                        corpus,
                        TurnRepairConflictKind.MIXED_SPEAKER_INTERVAL,
                        span.source_interval,
                        span.normalized_audio_interval,
                        (
                            span.span_id,
                            *span.speaker_turn_ids,
                            *span_utterances,
                        ),
                        (
                            "attribution span contains multiple speaker turns",
                            "overlap disclosure is preserved",
                        ),
                        (
                            "word-level speaker separation is unavailable",
                        ),
                        words=span.transcript_word_ids,
                        turns=span.speaker_turn_ids,
                        utterances=span_utterances,
                    )
                )
            if (
                span.attribution_kind
                in {
                    SpeakerAttributionKind.UNKNOWN,
                    SpeakerAttributionKind.UNATTRIBUTED,
                    SpeakerAttributionKind.CONFLICTED,
                    SpeakerAttributionKind.MULTIPLE_CANDIDATES,
                }
                and span.transcript_word_ids
            ):
                result.append(
                    _conflict(
                        corpus,
                        TurnRepairConflictKind.UNATTRIBUTED_TRANSCRIPT_WORDS,
                        span.source_interval,
                        span.normalized_audio_interval,
                        (span.span_id,) + span.transcript_word_ids,
                        (
                            f"attribution status is {span.attribution_kind.value}",
                        ),
                        (
                            "no single supported speaker target is available",
                        ),
                        words=span.transcript_word_ids,
                        turns=span.speaker_turn_ids,
                        utterances=span_utterances,
                    )
                )
    return tuple(result)


def _uncertain_component_conflicts(
    corpus: UtteranceCorpus,
) -> tuple[TurnRepairConflict, ...]:
    result: list[TurnRepairConflict] = []
    for utterance in corpus.utterances:
        for component in utterance.components:
            if not component.uncertain_word_attribution:
                continue
            result.append(
                _conflict(
                    corpus,
                    TurnRepairConflictKind.WORD_CROSSES_SPEAKER_BOUNDARY,
                    component.source_interval,
                    component.normalized_audio_interval,
                    (
                        component.component_id,
                        utterance.utterance_id,
                        *component.transcript_word_ids,
                    ),
                    (
                        "equal temporal support crossed a speaker boundary",
                    ),
                    (
                        "no uniquely stronger speaker attribution exists",
                    ),
                    words=component.transcript_word_ids,
                    turns=component.speaker_turn_ids,
                    utterances=(utterance.utterance_id,),
                )
            )
    return tuple(result)


def _nearest_word_edge(
    boundary: SpeakerChangeBoundary,
    word: TranscriptWord,
) -> tuple[int, int]:
    position = boundary.normalized_audio_microseconds
    edges = (
        word.normalized_audio_interval.start_microseconds,
        _end(word.normalized_audio_interval),
    )
    selected = min(edges, key=lambda edge: (abs(edge - position), edge))
    return selected, abs(selected - position)


def _proposal(
    corpus: UtteranceCorpus,
    conflict: TurnRepairConflict,
    assembly_words: dict[str, TranscriptWord],
    boundaries: dict[str, SpeakerChangeBoundary],
    turns: dict[str, SpeakerTurn],
    policy: TurnRepairPolicy,
    created_at: datetime,
) -> TurnRepairProposal:
    action = TurnRepairActionKind.MARK_UNRESOLVED
    position = None
    description = "Retain the conflict for review without changing source evidence."
    confidence = _confidence(None, "insufficient evidence for automatic repair")
    if conflict.kind == TurnRepairConflictKind.BOUNDARY_INSIDE_TRANSCRIPT_WORD:
        word = assembly_words[conflict.transcript_word_ids[0]]
        boundary = boundaries[conflict.speaker_boundary_ids[0]]
        edge, distance = _nearest_word_edge(boundary, word)
        if boundary.overlap_affected:
            action = TurnRepairActionKind.PRESERVE_MIXED_SPEAKER_INTERVAL
            description = (
                "Preserve the word and overlap interval as mixed-speaker evidence."
            )
            confidence = _confidence(0.90, "boundary is explicitly overlap-affected")
        elif distance <= policy.boundary_word_edge_tolerance_microseconds:
            action = TurnRepairActionKind.MOVE_BOUNDARY
            position = edge
            description = (
                "Propose moving the speaker boundary to the nearest word edge."
            )
            confidence = _confidence(
                0.70, "nearest word edge lies within configured tolerance"
            )
    elif conflict.kind == TurnRepairConflictKind.BOUNDARY_INSIDE_SPEAKER_TURN:
        turn = turns[conflict.speaker_turn_ids[0]]
        boundary = boundaries[conflict.speaker_boundary_ids[0]]
        left = (
            boundary.normalized_audio_microseconds
            - turn.normalized_audio_interval.start_microseconds
        )
        right = _end(turn.normalized_audio_interval) - (
            boundary.normalized_audio_microseconds
        )
        if min(left, right) >= policy.split_turn_minimum_side_microseconds:
            action = TurnRepairActionKind.SPLIT_TURN
            position = boundary.normalized_audio_microseconds
            description = (
                "Propose splitting the canonical turn at the internal boundary."
            )
            confidence = _confidence(
                0.75, "both proposed successor sides satisfy minimum duration"
            )
    elif conflict.kind in {
        TurnRepairConflictKind.TRANSCRIPT_SEGMENT_SPANS_SPEAKERS,
        TurnRepairConflictKind.MIXED_SPEAKER_INTERVAL,
        TurnRepairConflictKind.WORD_CROSSES_SPEAKER_BOUNDARY,
    }:
        action = TurnRepairActionKind.PRESERVE_MIXED_SPEAKER_INTERVAL
        description = (
            "Preserve mixed-speaker evidence; do not force word reassignment."
        )
        confidence = _confidence(0.90, "source evidence explicitly records ambiguity")
    change = TurnRepairProposedChange(
        action=action,
        source_turn_ids=conflict.speaker_turn_ids,
        source_boundary_ids=conflict.speaker_boundary_ids,
        source_utterance_ids=conflict.utterance_ids,
        source_transcript_word_ids=conflict.transcript_word_ids,
        proposed_boundary_normalized_microseconds=position,
        preserves_all_source_intervals=True,
        description=description,
    )
    payload = {
        "proposal_id": typed_id(
            "turnproposal",
            corpus.corpus_id,
            conflict.conflict_id,
            change.model_dump(mode="json"),
        ),
        "utterance_corpus_id": corpus.corpus_id,
        "conflict_ids": (conflict.conflict_id,),
        "proposed_change": change,
        "affected_artifact_ids": conflict.affected_artifact_ids,
        "evidence_basis": conflict.evidence_basis,
        "contrary_evidence": conflict.contrary_evidence,
        "confidence": confidence,
        "creation_process": TurnRepairCreationProcess.AUTOMATED_RULE,
        "disposition": TurnRepairProposalDisposition.PROPOSED,
        "review_status": UtteranceReviewStatus.REVIEW_REQUIRED,
        "policy_version": policy.policy_version,
        "created_at": created_at,
    }
    return _seal(TurnRepairProposal, payload)


def build_turn_repair_run(
    utterance_run: UtteranceRun,
    corpus: UtteranceCorpus,
    assembly: TranscriptAssembly,
    speaker_view: SpeakerLabeledTranscriptView,
    diarization: DiarizationRun,
    *,
    policy: TurnRepairPolicy | None = None,
    created_at: datetime | None = None,
) -> TurnRepairRun:
    """Detect bounded repair candidates without changing prior evidence."""
    validate_utterance_corpus(
        utterance_run, corpus, assembly, speaker_view, diarization
    )
    policy = policy or TurnRepairPolicy()
    timestamp = created_at or corpus.created_at
    conflicts = (
        _word_boundary_conflicts(corpus, assembly, diarization)
        + _internal_turn_boundary_conflicts(corpus, diarization)
        + _segment_conflicts(corpus, speaker_view)
        + _uncertain_component_conflicts(corpus)
    )
    unique_conflicts = tuple(
        {item.conflict_id: item for item in conflicts}.values()
    )
    words = {item.word_id: item for item in assembly.words}
    boundaries = {item.boundary_id: item for item in diarization.boundaries}
    turns = {item.turn_id: item for item in diarization.turns}
    proposals = tuple(
        _proposal(
            corpus,
            item,
            words,
            boundaries,
            turns,
            policy,
            timestamp,
        )
        for item in unique_conflicts
    )
    configuration_hash = canonical_hash(
        {
            "utterance_run": utterance_run.integrity_sha256,
            "utterance_corpus": corpus.integrity_sha256,
            "transcript_assembly": assembly.integrity_sha256,
            "speaker_view": speaker_view.integrity_sha256,
            "diarization": diarization.integrity_sha256,
            "policy": policy.model_dump(mode="json"),
        }
    )
    repair_run_id = typed_id(
        "turnrepairrun",
        corpus.corpus_id,
        configuration_hash,
        tuple(item.proposal_id for item in proposals),
    )
    return _seal(
        TurnRepairRun,
        {
            "repair_run_id": repair_run_id,
            "predecessor_repair_run_id": None,
            "utterance_corpus_id": corpus.corpus_id,
            "utterance_run_id": utterance_run.run_id,
            "phase2_transcript_assembly_id": assembly.assembly_id,
            "phase3_diarization_run_id": diarization.run_id,
            "phase3_speaker_transcript_view_id": speaker_view.view_id,
            "policy": policy,
            "configuration_hash": configuration_hash,
            "conflicts": unique_conflicts,
            "proposals": proposals,
            "decisions": (),
            "successors": (),
            "detected_at": timestamp,
            "updated_at": timestamp,
            "complete": True,
        },
    )


def decide_turn_repair(
    run: TurnRepairRun,
    proposal_id: str,
    disposition: TurnRepairDecisionDisposition,
    *,
    author: str,
    rationale: str,
    evidence_references: tuple[str, ...],
    decided_at: datetime,
) -> TurnRepairRun:
    """Append a review decision and an accepted derived successor."""
    _verify_seal(run, "turn-repair run")
    proposals = {item.proposal_id: item for item in run.proposals}
    if proposal_id not in proposals:
        raise TurnRepairIntegrityError("turn-repair proposal is unknown")
    if any(item.proposal_id == proposal_id for item in run.decisions):
        raise TurnRepairIntegrityError("turn-repair proposal is already decided")
    if decided_at < run.updated_at:
        raise TurnRepairIntegrityError("turn-repair decision time regresses")
    proposal = proposals[proposal_id]
    successor_id = (
        typed_id(
            "turnsuccessor",
            proposal_id,
            proposal.proposed_change.model_dump(mode="json"),
            decided_at.isoformat(),
        )
        if disposition == TurnRepairDecisionDisposition.ACCEPTED
        else None
    )
    decision_id = typed_id(
        "turndecision",
        proposal_id,
        disposition.value,
        author,
        rationale,
        evidence_references,
        decided_at.isoformat(),
        successor_id,
    )
    decision = _seal(
        TurnRepairDecision,
        {
            "decision_id": decision_id,
            "proposal_id": proposal_id,
            "disposition": disposition,
            "author": author,
            "rationale": rationale,
            "evidence_references": evidence_references,
            "decided_at": decided_at,
            "successor_id": successor_id,
        },
    )
    successors = run.successors
    if successor_id is not None:
        successors += (
            _seal(
                TurnRepairSuccessor,
                {
                    "successor_id": successor_id,
                    "proposal_id": proposal_id,
                    "decision_id": decision_id,
                    "utterance_corpus_id": run.utterance_corpus_id,
                    "source_artifact_ids": proposal.affected_artifact_ids,
                    "projected_change": proposal.proposed_change,
                    "predecessor_artifacts_preserved": True,
                    "applied_at": decided_at,
                },
            ),
        )
    decisions = run.decisions + (decision,)
    new_id = typed_id(
        "turnrepairrun",
        run.repair_run_id,
        tuple(item.integrity_sha256 for item in decisions),
        tuple(item.integrity_sha256 for item in successors),
    )
    payload = run.model_dump(
        exclude={
            "integrity_sha256",
            "repair_run_id",
            "predecessor_repair_run_id",
            "decisions",
            "successors",
            "updated_at",
        }
    )
    payload.update(
        {
            "repair_run_id": new_id,
            "predecessor_repair_run_id": run.repair_run_id,
            "decisions": decisions,
            "successors": successors,
            "updated_at": decided_at,
        }
    )
    return _seal(TurnRepairRun, payload)


def _report(run: TurnRepairRun) -> TurnRepairReport:
    decisions = {item.proposal_id: item for item in run.decisions}
    unresolved = sum(
        item.proposed_change.action == TurnRepairActionKind.MARK_UNRESOLVED
        and item.proposal_id not in decisions
        for item in run.proposals
    )
    return _seal(
        TurnRepairReport,
        {
            "report_id": typed_id(
                "turnrepairreport", run.repair_run_id, run.integrity_sha256
            ),
            "repair_run_id": run.repair_run_id,
            "utterance_corpus_id": run.utterance_corpus_id,
            "generated_at": run.updated_at,
            "conflict_count": len(run.conflicts),
            "proposal_count": len(run.proposals),
            "accepted_count": sum(
                item.disposition == TurnRepairDecisionDisposition.ACCEPTED
                for item in run.decisions
            ),
            "rejected_count": sum(
                item.disposition == TurnRepairDecisionDisposition.REJECTED
                for item in run.decisions
            ),
            "deferred_count": sum(
                item.disposition == TurnRepairDecisionDisposition.DEFERRED
                for item in run.decisions
            ),
            "unresolved_count": unresolved,
            "successor_count": len(run.successors),
            "review_required_count": len(run.proposals) - len(run.decisions),
            "limitations": (
                "Automated word reassignment is prohibited.",
                "Accepted repairs are derived successors, not source mutation.",
                "Synthetic mechanics do not establish repair accuracy.",
            ),
            "status": "warning" if run.proposals else "complete",
        },
    )


def validate_turn_repair_run(
    run: TurnRepairRun,
    utterance_run: UtteranceRun,
    corpus: UtteranceCorpus,
    assembly: TranscriptAssembly,
    speaker_view: SpeakerLabeledTranscriptView,
    diarization: DiarizationRun,
    *,
    report: TurnRepairReport | None = None,
) -> None:
    validate_utterance_corpus(
        utterance_run, corpus, assembly, speaker_view, diarization
    )
    _verify_seal(run, "turn-repair run")
    for item in run.conflicts:
        _verify_seal(item, item.conflict_id)
    for item in run.proposals:
        _verify_seal(item, item.proposal_id)
    for item in run.decisions:
        _verify_seal(item, item.decision_id)
    for item in run.successors:
        _verify_seal(item, item.successor_id)
    if (
        run.utterance_corpus_id != corpus.corpus_id
        or run.utterance_run_id != utterance_run.run_id
        or run.phase2_transcript_assembly_id != assembly.assembly_id
        or run.phase3_diarization_run_id != diarization.run_id
        or run.phase3_speaker_transcript_view_id != speaker_view.view_id
    ):
        raise TurnRepairIntegrityError(
            "turn-repair run and source lineage disagree"
        )
    expected = build_turn_repair_run(
        utterance_run,
        corpus,
        assembly,
        speaker_view,
        diarization,
        policy=run.policy,
        created_at=run.detected_at,
    )
    if (
        expected.configuration_hash != run.configuration_hash
        or expected.conflicts != run.conflicts
        or expected.proposals != run.proposals
    ):
        raise TurnRepairIntegrityError(
            "turn-repair detection is not the deterministic source projection"
        )
    if not run.decisions:
        if run != expected:
            raise TurnRepairIntegrityError(
                "base turn-repair run identity is invalid"
            )
    else:
        if run.predecessor_repair_run_id is None:
            raise TurnRepairIntegrityError(
                "reviewed repair run requires a predecessor"
            )
        expected_reviewed_id = typed_id(
            "turnrepairrun",
            run.predecessor_repair_run_id,
            tuple(item.integrity_sha256 for item in run.decisions),
            tuple(item.integrity_sha256 for item in run.successors),
        )
        if run.repair_run_id != expected_reviewed_id:
            raise TurnRepairIntegrityError(
                "reviewed turn-repair run identity is invalid"
            )
        if len({item.proposal_id for item in run.decisions}) != len(
            run.decisions
        ):
            raise TurnRepairIntegrityError(
                "turn-repair proposal has duplicate decisions"
            )
        proposals = {item.proposal_id: item for item in run.proposals}
        decisions = {item.decision_id: item for item in run.decisions}
        for successor in run.successors:
            proposal = proposals[successor.proposal_id]
            decision = decisions[successor.decision_id]
            if (
                decision.disposition
                != TurnRepairDecisionDisposition.ACCEPTED
                or decision.successor_id != successor.successor_id
                or successor.projected_change != proposal.proposed_change
                or successor.source_artifact_ids
                != proposal.affected_artifact_ids
            ):
                raise TurnRepairIntegrityError(
                    "turn-repair successor projection is invalid"
                )
    if report is not None:
        _verify_seal(report, "turn-repair report")
        if report != _report(run):
            raise TurnRepairIntegrityError(
                "turn-repair report projection is invalid"
            )


def turn_repair_report_markdown(report: TurnRepairReport) -> str:
    return "\n".join(
        (
            "# Phase 4 turn-repair report",
            "",
            f"- Repair run: `{report.repair_run_id}`",
            f"- Conflicts: {report.conflict_count}",
            f"- Proposals: {report.proposal_count}",
            f"- Accepted: {report.accepted_count}",
            f"- Rejected: {report.rejected_count}",
            f"- Deferred: {report.deferred_count}",
            f"- Derived successors: {report.successor_count}",
            f"- Review required: {report.review_required_count}",
            f"- Status: {report.status}",
            "",
        )
    )


def persist_turn_repair_run(
    run: TurnRepairRun,
    utterance_run: UtteranceRun,
    corpus: UtteranceCorpus,
    assembly: TranscriptAssembly,
    speaker_view: SpeakerLabeledTranscriptView,
    diarization: DiarizationRun,
    destination: Path,
) -> tuple[TurnRepairRun, TurnRepairReport, Path, bool]:
    destination = destination.expanduser().resolve()
    validate_turn_repair_run(
        run, utterance_run, corpus, assembly, speaker_view, diarization
    )
    report = _report(run)
    root = destination / "turn-repairs" / run.repair_run_id
    paths = (
        root / "run.json",
        root / "report.json",
        root / "report.md",
    )
    existing = tuple(path.exists() for path in paths)
    if any(existing) and not all(existing):
        raise TurnRepairIntegrityError("cached turn-repair run is incomplete")
    if all(existing):
        stored = load_contract(paths[0].read_bytes(), TurnRepairRun)
        stored_report = load_contract(
            paths[1].read_bytes(), TurnRepairReport
        )
        validate_turn_repair_run(
            stored,
            utterance_run,
            corpus,
            assembly,
            speaker_view,
            diarization,
            report=stored_report,
        )
        if (
            stored != run
            or stored_report != report
            or paths[2].read_text(encoding="utf-8")
            != turn_repair_report_markdown(report)
        ):
            raise TurnRepairIntegrityError(
                "cached turn-repair run is incompatible"
            )
        return stored, stored_report, root, True
    _atomic(paths[0], canonical_bytes(run))
    _atomic(paths[1], canonical_bytes(report))
    _atomic(paths[2], turn_repair_report_markdown(report).encode("utf-8"))
    return run, report, root, False


def load_turn_repair_run(
    root: Path,
) -> tuple[TurnRepairRun, TurnRepairReport]:
    root = root.expanduser().resolve(strict=True)
    return (
        load_contract((root / "run.json").read_bytes(), TurnRepairRun),
        load_contract((root / "report.json").read_bytes(), TurnRepairReport),
    )
