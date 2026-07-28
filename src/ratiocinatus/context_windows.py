"""Deterministic, budgeted Phase 4 utterance context windows."""

from __future__ import annotations

import os
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from .context_window_contracts import (
    ContextExclusionKind,
    ContextExclusionSummary,
    ContextInclusionReason,
    ContextWindowBundle,
    ContextWindowKind,
    ContextWindowMember,
    ContextWindowPolicy,
    ContextWindowReport,
    UtteranceContextWindow,
)
from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase4_contracts import (
    Utterance,
    UtteranceAnalysisRun,
    UtteranceCorpus,
    UtteranceRun,
    UtteranceTextKind,
)
from .quotation_contracts import QuotationEvidenceRun
from .turn_repair_contracts import TurnRepairRun
from .utterance_relation_contracts import UtteranceRelationRun
from .utterance_view_contracts import (
    SpeakerAttributedTranscriptBundle,
    SpeakerAttributedTranscriptReport,
    SpeakerAttributedViewKind,
)
from .utterance_views import validate_speaker_attributed_views


class ContextWindowIntegrityError(RuntimeError):
    """Context windows are corrupt or incompatible with their evidence."""


class ContextWindowBudgetError(ValueError):
    """A target utterance cannot fit inside the declared context budget."""


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
        raise ContextWindowIntegrityError(f"{label} integrity is invalid")


def _bounds(utterance: Utterance) -> tuple[int, int]:
    starts = [
        item.start_microseconds for item in utterance.normalized_audio_intervals
    ]
    ends = [
        item.start_microseconds + item.duration_microseconds
        for item in utterance.normalized_audio_intervals
    ]
    return min(starts), max(ends)


def _ordered(corpus: UtteranceCorpus) -> tuple[Utterance, ...]:
    return tuple(
        sorted(
            corpus.utterances,
            key=lambda item: (*_bounds(item), item.utterance_id),
        )
    )


def _text(utterance: Utterance) -> str:
    return next(
        item.text
        for item in utterance.text_views
        if item.kind == UtteranceTextKind.DISPLAY
    )


def _tokens(text: str, policy: ContextWindowPolicy) -> int:
    if not text:
        return 0
    width = policy.token_estimate_characters_per_token
    return max(1, (len(text) + width - 1) // width)


def _speaker_key(utterance: Utterance) -> str | None:
    return utterance.attribution.target_id


def _is_question(utterance: Utterance) -> bool:
    return _text(utterance).rstrip().rstrip("\"'”’)]}").endswith("?")


def _union_duration(utterances: tuple[Utterance, ...]) -> int:
    intervals = sorted(
        (
            item.start_microseconds,
            item.start_microseconds + item.duration_microseconds,
        )
        for utterance in utterances
        for item in utterance.source_intervals
    )
    total = 0
    start = end = None
    for item_start, item_end in intervals:
        if start is None:
            start, end = item_start, item_end
        elif item_start <= end:
            end = max(end, item_end)
        else:
            total += end - start
            start, end = item_start, item_end
    return total + (0 if start is None else end - start)


def _add(
    reasons: dict[str, set[ContextInclusionReason]],
    evidence: dict[str, set[str]],
    utterance_id: str,
    reason: ContextInclusionReason,
    *references: str,
) -> None:
    reasons[utterance_id].add(reason)
    evidence[utterance_id].update(references)


def _base_candidates(
    kind: ContextWindowKind,
    target_index: int,
    utterances: tuple[Utterance, ...],
    relations: UtteranceRelationRun,
    quotation: QuotationEvidenceRun,
    policy: ContextWindowPolicy,
) -> tuple[
    dict[str, set[ContextInclusionReason]],
    dict[str, set[str]],
    bool,
]:
    target = utterances[target_index]
    reasons: dict[str, set[ContextInclusionReason]] = defaultdict(set)
    evidence: dict[str, set[str]] = defaultdict(set)
    _add(
        reasons,
        evidence,
        target.utterance_id,
        ContextInclusionReason.TARGET,
        target.utterance_id,
    )
    structurally_available = True

    if kind == ContextWindowKind.PRECEDING:
        start = max(0, target_index - policy.preceding_utterance_count)
        for item in utterances[start:target_index]:
            _add(
                reasons,
                evidence,
                item.utterance_id,
                ContextInclusionReason.PRECEDING,
                item.utterance_id,
            )
    elif kind == ContextWindowKind.FOLLOWING:
        stop = target_index + 1 + policy.following_utterance_count
        for item in utterances[target_index + 1 : stop]:
            _add(
                reasons,
                evidence,
                item.utterance_id,
                ContextInclusionReason.FOLLOWING,
                item.utterance_id,
            )
    elif kind == ContextWindowKind.SAME_SPEAKER_HISTORY:
        speaker = _speaker_key(target)
        if speaker is None:
            structurally_available = False
        else:
            history = [
                item
                for item in utterances[:target_index]
                if _speaker_key(item) == speaker
            ][-policy.same_speaker_history_count :]
            for item in history:
                _add(
                    reasons,
                    evidence,
                    item.utterance_id,
                    ContextInclusionReason.SAME_SPEAKER,
                    item.attribution.attribution_id,
                )
    elif kind == ContextWindowKind.CURRENT_TURN_NEIGHBORHOOD:
        speaker = _speaker_key(target)
        if speaker is None:
            structurally_available = False
        else:
            left = target_index - 1
            while left >= 0 and _speaker_key(utterances[left]) == speaker:
                _add(
                    reasons,
                    evidence,
                    utterances[left].utterance_id,
                    ContextInclusionReason.CURRENT_TURN,
                    utterances[left].attribution.attribution_id,
                )
                left -= 1
            right = target_index + 1
            while (
                right < len(utterances)
                and _speaker_key(utterances[right]) == speaker
            ):
                _add(
                    reasons,
                    evidence,
                    utterances[right].utterance_id,
                    ContextInclusionReason.CURRENT_TURN,
                    utterances[right].attribution.attribution_id,
                )
                right += 1
    elif kind == ContextWindowKind.EXCHANGE:
        for index in (target_index - 1, target_index + 1):
            if 0 <= index < len(utterances):
                item = utterances[index]
                _add(
                    reasons,
                    evidence,
                    item.utterance_id,
                    ContextInclusionReason.EXCHANGE_NEIGHBOR,
                    item.utterance_id,
                )
    elif kind == ContextWindowKind.QUESTION_RESPONSE:
        question_index = None
        response_index = None
        if _is_question(target) and target_index + 1 < len(utterances):
            question_index, response_index = target_index, target_index + 1
        elif target_index > 0 and _is_question(utterances[target_index - 1]):
            question_index, response_index = target_index - 1, target_index
        if question_index is None:
            structurally_available = False
        else:
            question = utterances[question_index]
            response = utterances[response_index]
            _add(
                reasons,
                evidence,
                question.utterance_id,
                ContextInclusionReason.QUESTION,
                question.utterance_id,
            )
            _add(
                reasons,
                evidence,
                response.utterance_id,
                ContextInclusionReason.RESPONSE,
                response.utterance_id,
            )
    elif kind == ContextWindowKind.INTERRUPTION:
        matched = False
        for item in relations.interruptions:
            involved = {
                item.interrupted_utterance_id,
                item.interrupting_utterance_id,
            }
            if target.utterance_id not in involved:
                continue
            matched = True
            for utterance_id in involved - {None}:
                _add(
                    reasons,
                    evidence,
                    utterance_id,
                    ContextInclusionReason.INTERRUPTION,
                    item.interruption_id,
                )
            if item.continuation_relation_id is not None:
                continuation = next(
                    value
                    for value in relations.continuations
                    if value.continuation_id == item.continuation_relation_id
                )
                for utterance_id in (
                    continuation.predecessor_utterance_id,
                    *continuation.intervening_utterance_ids,
                    continuation.successor_utterance_id,
                ):
                    _add(
                        reasons,
                        evidence,
                        utterance_id,
                        ContextInclusionReason.CONTINUATION,
                        continuation.continuation_id,
                    )
        structurally_available = matched
    elif kind == ContextWindowKind.QUOTATION:
        quotation_ids = {
            item.quoting_utterance_id: item.quotation_id
            for item in quotation.quotations
        }
        if target.utterance_id not in quotation_ids:
            structurally_available = False
        else:
            _add(
                reasons,
                evidence,
                target.utterance_id,
                ContextInclusionReason.QUOTATION,
                quotation_ids[target.utterance_id],
            )
            for index in (target_index - 1, target_index + 1):
                if 0 <= index < len(utterances):
                    item = utterances[index]
                    _add(
                        reasons,
                        evidence,
                        item.utterance_id,
                        ContextInclusionReason.QUOTATION_NEIGHBOR,
                        quotation_ids[target.utterance_id],
                    )
    elif kind == ContextWindowKind.BOUNDED_TEMPORAL:
        target_start, target_end = _bounds(target)
        for item in utterances:
            item_start, item_end = _bounds(item)
            gap = max(target_start - item_end, item_start - target_end, 0)
            if gap <= policy.temporal_radius_microseconds:
                _add(
                    reasons,
                    evidence,
                    item.utterance_id,
                    ContextInclusionReason.TEMPORAL_PROXIMITY,
                    item.utterance_id,
                )
    return reasons, evidence, structurally_available


def _preserve_simultaneity(
    reasons: dict[str, set[ContextInclusionReason]],
    evidence: dict[str, set[str]],
    simultaneous: dict[str, tuple[str, ...]],
) -> None:
    pending = list(reasons)
    seen = set(pending)
    while pending:
        utterance_id = pending.pop()
        for peer in simultaneous.get(utterance_id, ()):
            _add(
                reasons,
                evidence,
                peer,
                ContextInclusionReason.SIMULTANEOUS_OVERLAP,
                utterance_id,
            )
            if peer not in seen:
                seen.add(peer)
                pending.append(peer)


def _select(
    target: Utterance,
    utterances: tuple[Utterance, ...],
    positions: dict[str, int],
    reasons: dict[str, set[ContextInclusionReason]],
    policy: ContextWindowPolicy,
) -> tuple[tuple[str, ...], dict[ContextExclusionKind, list[str]]]:
    by_id = {item.utterance_id: item for item in utterances}
    target_tokens = _tokens(_text(target), policy)
    target_duration = _union_duration((target,))
    if (
        target_tokens > policy.maximum_token_estimate
        or target_duration > policy.maximum_source_duration_microseconds
    ):
        raise ContextWindowBudgetError(
            f"target {target.utterance_id} exceeds the context budget"
        )
    selected = [target.utterance_id]
    omitted: dict[ContextExclusionKind, list[str]] = defaultdict(list)
    speaker_counts: dict[str, int] = defaultdict(int)
    target_speaker = _speaker_key(target) or target.utterance_id
    speaker_counts[target_speaker] += 1
    remaining = set(reasons) - {target.utterance_id}
    target_position = positions[target.utterance_id]
    preservation_reasons: set[ContextInclusionReason] = set()
    if policy.preserve_question_response:
        preservation_reasons.update(
            {ContextInclusionReason.QUESTION, ContextInclusionReason.RESPONSE}
        )
    if policy.preserve_interruption_relations:
        preservation_reasons.update(
            {
                ContextInclusionReason.INTERRUPTION,
                ContextInclusionReason.CONTINUATION,
            }
        )
    if policy.preserve_quotation_sources:
        preservation_reasons.update(
            {
                ContextInclusionReason.QUOTATION,
                ContextInclusionReason.QUOTATION_NEIGHBOR,
            }
        )
    if policy.preserve_simultaneous_overlap:
        preservation_reasons.add(ContextInclusionReason.SIMULTANEOUS_OVERLAP)
    while remaining:
        def priority(utterance_id: str):
            item = by_id[utterance_id]
            preserved = not bool(
                reasons[utterance_id].intersection(preservation_reasons)
            )
            speaker = _speaker_key(item) or item.utterance_id
            balance = (
                speaker_counts[speaker]
                if policy.speaker_balanced_selection
                else 0
            )
            distance = abs(positions[utterance_id] - target_position)
            return preserved, balance, distance, positions[utterance_id], utterance_id

        utterance_id = min(remaining, key=priority)
        remaining.remove(utterance_id)
        candidate = by_id[utterance_id]
        tentative = tuple(by_id[item] for item in (*selected, utterance_id))
        if len(tentative) > policy.maximum_utterance_count:
            omitted[ContextExclusionKind.MAXIMUM_UTTERANCE_COUNT].append(
                utterance_id
            )
            continue
        if sum(_tokens(_text(item), policy) for item in tentative) > (
            policy.maximum_token_estimate
        ):
            omitted[ContextExclusionKind.MAXIMUM_TOKEN_ESTIMATE].append(
                utterance_id
            )
            continue
        if _union_duration(tentative) > (
            policy.maximum_source_duration_microseconds
        ):
            omitted[ContextExclusionKind.MAXIMUM_SOURCE_DURATION].append(
                utterance_id
            )
            continue
        selected.append(utterance_id)
        speaker = _speaker_key(candidate) or candidate.utterance_id
        speaker_counts[speaker] += 1
    return tuple(selected), omitted


def _summary(
    bundle_id: str,
    window_key: tuple[str, str],
    kind: ContextExclusionKind,
    count: int,
    identifiers: tuple[str, ...],
    complete: bool,
) -> ContextExclusionSummary:
    explanations = {
        ContextExclusionKind.OUTSIDE_WINDOW_POLICY:
            "Utterances outside the declared window scope were excluded.",
        ContextExclusionKind.STRUCTURE_UNAVAILABLE:
            "The requested structural relation was not present.",
        ContextExclusionKind.MAXIMUM_UTTERANCE_COUNT:
            "Candidates exceeded the maximum utterance count.",
        ContextExclusionKind.MAXIMUM_TOKEN_ESTIMATE:
            "Candidates exceeded the maximum token estimate.",
        ContextExclusionKind.MAXIMUM_SOURCE_DURATION:
            "Candidates exceeded the maximum source duration.",
    }
    return _seal(
        ContextExclusionSummary,
        {
            "summary_id": typed_id(
                "contextomission", bundle_id, window_key, kind.value, identifiers
            ),
            "kind": kind,
            "omitted_utterance_count": count,
            "omitted_utterance_ids": identifiers,
            "identifiers_complete": complete,
            "explanation": explanations[kind],
        },
    )


def _window(
    bundle_id: str,
    view_bundle: SpeakerAttributedTranscriptBundle,
    kind: ContextWindowKind,
    target_index: int,
    utterances: tuple[Utterance, ...],
    relations: UtteranceRelationRun,
    quotation: QuotationEvidenceRun,
    policy: ContextWindowPolicy,
    created_at: datetime,
) -> UtteranceContextWindow:
    target = utterances[target_index]
    positions = {
        item.utterance_id: index for index, item in enumerate(utterances)
    }
    expanded = next(
        item
        for item in view_bundle.views
        if item.kind == SpeakerAttributedViewKind.OVERLAP_EXPANDED
    )
    rendered = {
        item.utterance_id: item for item in expanded.rendered_utterances
    }
    simultaneous = {
        key: value.simultaneous_with_utterance_ids
        for key, value in rendered.items()
    }
    reasons, evidence, structurally_available = _base_candidates(
        kind, target_index, utterances, relations, quotation, policy
    )
    if policy.preserve_simultaneous_overlap:
        _preserve_simultaneity(reasons, evidence, simultaneous)
    candidate_ids = set(reasons)
    selected_ids, omitted = _select(
        target, utterances, positions, reasons, policy
    )
    selected_ids = tuple(
        sorted(selected_ids, key=lambda item: positions[item])
    )
    by_id = {item.utterance_id: item for item in utterances}
    members = []
    for order_position, utterance_id in enumerate(selected_ids):
        utterance = by_id[utterance_id]
        presentation = rendered[utterance_id]
        text = _text(utterance)
        members.append(
            _seal(
                ContextWindowMember,
                {
                    "member_id": typed_id(
                        "contextmember",
                        bundle_id,
                        target.utterance_id,
                        kind.value,
                        utterance_id,
                    ),
                    "utterance_id": utterance_id,
                    "order_position": order_position,
                    "corpus_sequence_position": positions[utterance_id],
                    "temporal_group_id": presentation.temporal_group_id,
                    "temporal_lane": presentation.temporal_lane,
                    "simultaneous_with_utterance_ids": (
                        presentation.simultaneous_with_utterance_ids
                    ),
                    "source_intervals": utterance.source_intervals,
                    "normalized_audio_intervals": (
                        utterance.normalized_audio_intervals
                    ),
                    "inclusion_reasons": tuple(
                        sorted(reasons[utterance_id], key=lambda item: item.value)
                    ),
                    "character_count": len(text),
                    "token_estimate": _tokens(text, policy),
                    "evidence_references": tuple(
                        sorted(
                            {
                                utterance.utterance_id,
                                view_bundle.bundle_id,
                                *evidence[utterance_id],
                            }
                        )
                    ),
                },
            )
        )
    window_key = (target.utterance_id, kind.value)
    exclusions = []
    outside_count = len(utterances) - len(candidate_ids)
    if outside_count:
        exclusions.append(
            _summary(
                bundle_id,
                window_key,
                ContextExclusionKind.OUTSIDE_WINDOW_POLICY,
                outside_count,
                (),
                False,
            )
        )
    if not structurally_available:
        exclusions.append(
            _summary(
                bundle_id,
                window_key,
                ContextExclusionKind.STRUCTURE_UNAVAILABLE,
                0,
                (),
                True,
            )
        )
    for exclusion_kind in (
        ContextExclusionKind.MAXIMUM_UTTERANCE_COUNT,
        ContextExclusionKind.MAXIMUM_TOKEN_ESTIMATE,
        ContextExclusionKind.MAXIMUM_SOURCE_DURATION,
    ):
        identifiers = tuple(
            sorted(omitted.get(exclusion_kind, ()), key=lambda item: positions[item])
        )
        if identifiers:
            exclusions.append(
                _summary(
                    bundle_id,
                    window_key,
                    exclusion_kind,
                    len(identifiers),
                    identifiers,
                    True,
                )
            )
    selected = tuple(by_id[item] for item in selected_ids)
    intervals = tuple(
        sorted(
            {
                (
                    item.domain.value,
                    item.start_microseconds,
                    item.duration_microseconds,
                    canonical_hash(item.model_dump(mode="json")),
                ): item
                for utterance in selected
                for item in utterance.source_intervals
            }.values(),
            key=lambda item: (
                item.start_microseconds,
                item.duration_microseconds,
                canonical_hash(item.model_dump(mode="json")),
            ),
        )
    )
    truncated = any(omitted.values())
    return _seal(
        UtteranceContextWindow,
        {
            "context_window_id": typed_id(
                "contextwindow", bundle_id, target.utterance_id, kind.value
            ),
            "context_bundle_id": bundle_id,
            "utterance_corpus_id": target.utterance_corpus_id,
            "transcript_view_bundle_id": view_bundle.bundle_id,
            "target_utterance_id": target.utterance_id,
            "kind": kind,
            "policy": policy,
            "members": tuple(members),
            "source_intervals": intervals,
            "character_count": sum(item.character_count for item in members),
            "token_estimate": sum(item.token_estimate for item in members),
            "source_duration_microseconds": _union_duration(selected),
            "structurally_available": structurally_available,
            "truncated": truncated,
            "complete_exchange_considered": not truncated,
            "exclusions": tuple(exclusions),
            "ordering_basis": (
                "canonical temporal order with overlap groups, lanes, and "
                "simultaneous references preserved"
            ),
            "created_at": created_at,
        },
    )


def build_context_windows(
    view_bundle: SpeakerAttributedTranscriptBundle,
    utterance_run: UtteranceRun,
    corpus: UtteranceCorpus,
    analysis: UtteranceAnalysisRun,
    relations: UtteranceRelationRun,
    repair: TurnRepairRun,
    quotation: QuotationEvidenceRun,
    *,
    policy: ContextWindowPolicy | None = None,
    created_at: datetime | None = None,
) -> ContextWindowBundle:
    """Build every declared context kind for every canonical utterance."""
    validate_speaker_attributed_views(
        view_bundle,
        utterance_run,
        corpus,
        analysis,
        relations,
        repair,
        quotation,
    )
    policy = policy or ContextWindowPolicy()
    timestamp = created_at or view_bundle.generated_at
    configuration_hash = canonical_hash(
        {
            "transcript_view_bundle": view_bundle.integrity_sha256,
            "utterance_run": utterance_run.integrity_sha256,
            "corpus": corpus.integrity_sha256,
            "analysis": analysis.integrity_sha256,
            "relations": relations.integrity_sha256,
            "repair": repair.integrity_sha256,
            "quotation": quotation.integrity_sha256,
            "policy": policy.model_dump(mode="json"),
        }
    )
    bundle_id = typed_id(
        "contextbundle", corpus.corpus_id, view_bundle.bundle_id, configuration_hash
    )
    utterances = _ordered(corpus)
    windows = tuple(
        _window(
            bundle_id,
            view_bundle,
            kind,
            target_index,
            utterances,
            relations,
            quotation,
            policy,
            timestamp,
        )
        for target_index in range(len(utterances))
        for kind in ContextWindowKind
    )
    return _seal(
        ContextWindowBundle,
        {
            "context_bundle_id": bundle_id,
            "utterance_corpus_id": corpus.corpus_id,
            "utterance_run_id": utterance_run.run_id,
            "utterance_relation_run_id": relations.relation_run_id,
            "quotation_run_id": quotation.quotation_run_id,
            "transcript_view_bundle_id": view_bundle.bundle_id,
            "policy": policy,
            "configuration_hash": configuration_hash,
            "windows": windows,
            "created_at": timestamp,
        },
    )


def _report(bundle: ContextWindowBundle) -> ContextWindowReport:
    omissions = tuple(
        summary
        for window in bundle.windows
        for summary in window.exclusions
        if summary.kind
        not in {
            ContextExclusionKind.OUTSIDE_WINDOW_POLICY,
            ContextExclusionKind.STRUCTURE_UNAVAILABLE,
        }
    )
    return _seal(
        ContextWindowReport,
        {
            "report_id": typed_id(
                "contextreport",
                bundle.context_bundle_id,
                bundle.integrity_sha256,
            ),
            "context_bundle_id": bundle.context_bundle_id,
            "utterance_corpus_id": bundle.utterance_corpus_id,
            "created_at": bundle.created_at,
            "target_utterance_count": len(
                {item.target_utterance_id for item in bundle.windows}
            ),
            "window_count": len(bundle.windows),
            "truncated_window_count": sum(
                item.truncated for item in bundle.windows
            ),
            "structurally_unavailable_window_count": sum(
                not item.structurally_available for item in bundle.windows
            ),
            "omitted_utterance_count": sum(
                item.omitted_utterance_count for item in omissions
            ),
            "maximum_observed_token_estimate": max(
                (item.token_estimate for item in bundle.windows), default=0
            ),
            "maximum_observed_source_duration_microseconds": max(
                (
                    item.source_duration_microseconds
                    for item in bundle.windows
                ),
                default=0,
            ),
            "status": (
                "warning"
                if any(
                    item.truncated or not item.structurally_available
                    for item in bundle.windows
                )
                else "complete"
            ),
            "limitations": (
                "Question-response structure uses explicit terminal question "
                "punctuation and immediate canonical response order.",
                "Unknown speakers are not merged into same-speaker history.",
                "Token counts are deterministic estimates, not tokenizer output.",
            ),
        },
    )


def validate_context_windows(
    bundle: ContextWindowBundle,
    view_bundle: SpeakerAttributedTranscriptBundle,
    utterance_run: UtteranceRun,
    corpus: UtteranceCorpus,
    analysis: UtteranceAnalysisRun,
    relations: UtteranceRelationRun,
    repair: TurnRepairRun,
    quotation: QuotationEvidenceRun,
    *,
    report: ContextWindowReport | None = None,
) -> None:
    validate_speaker_attributed_views(
        view_bundle,
        utterance_run,
        corpus,
        analysis,
        relations,
        repair,
        quotation,
    )
    _verify_seal(bundle, "context-window bundle")
    for window in bundle.windows:
        _verify_seal(window, window.context_window_id)
        for member in window.members:
            _verify_seal(member, member.member_id)
        for exclusion in window.exclusions:
            _verify_seal(exclusion, exclusion.summary_id)
    if (
        bundle.utterance_corpus_id != corpus.corpus_id
        or bundle.utterance_run_id != utterance_run.run_id
        or bundle.utterance_relation_run_id != relations.relation_run_id
        or bundle.quotation_run_id != quotation.quotation_run_id
        or bundle.transcript_view_bundle_id != view_bundle.bundle_id
    ):
        raise ContextWindowIntegrityError(
            "context-window and source lineage disagree"
        )
    expected = build_context_windows(
        view_bundle,
        utterance_run,
        corpus,
        analysis,
        relations,
        repair,
        quotation,
        policy=bundle.policy,
        created_at=bundle.created_at,
    )
    if expected != bundle:
        raise ContextWindowIntegrityError(
            "context windows are not the deterministic source projection"
        )
    if report is not None:
        _verify_seal(report, "context-window report")
        if report != _report(bundle):
            raise ContextWindowIntegrityError(
                "context-window report is invalid"
            )


def context_window_report_markdown(report: ContextWindowReport) -> str:
    return "\n".join(
        (
            "# Phase 4 context-window report",
            "",
            f"- Bundle: `{report.context_bundle_id}`",
            f"- Targets: {report.target_utterance_count}",
            f"- Windows: {report.window_count}",
            f"- Truncated windows: {report.truncated_window_count}",
            (
                "- Structurally unavailable windows: "
                f"{report.structurally_unavailable_window_count}"
            ),
            f"- Budget-omitted utterances: {report.omitted_utterance_count}",
            (
                "- Maximum observed token estimate: "
                f"{report.maximum_observed_token_estimate}"
            ),
            (
                "- Maximum observed source duration (microseconds): "
                f"{report.maximum_observed_source_duration_microseconds}"
            ),
            f"- Status: {report.status}",
            "",
        )
    )


def persist_context_windows(
    bundle: ContextWindowBundle,
    view_bundle: SpeakerAttributedTranscriptBundle,
    utterance_run: UtteranceRun,
    corpus: UtteranceCorpus,
    analysis: UtteranceAnalysisRun,
    relations: UtteranceRelationRun,
    repair: TurnRepairRun,
    quotation: QuotationEvidenceRun,
    destination: Path,
) -> tuple[ContextWindowBundle, ContextWindowReport, Path, bool]:
    destination = destination.expanduser().resolve()
    validate_context_windows(
        bundle,
        view_bundle,
        utterance_run,
        corpus,
        analysis,
        relations,
        repair,
        quotation,
    )
    report = _report(bundle)
    root = destination / "context-windows" / bundle.context_bundle_id
    paths = (
        root / "bundle.json",
        root / "report.json",
        root / "report.md",
    )
    existing = tuple(path.exists() for path in paths)
    if any(existing) and not all(existing):
        raise ContextWindowIntegrityError(
            "cached context-window bundle is incomplete"
        )
    if all(existing):
        stored, stored_report = load_context_windows(root)
        validate_context_windows(
            stored,
            view_bundle,
            utterance_run,
            corpus,
            analysis,
            relations,
            repair,
            quotation,
            report=stored_report,
        )
        if (
            stored != bundle
            or stored_report != report
            or paths[2].read_text(encoding="utf-8")
            != context_window_report_markdown(report)
        ):
            raise ContextWindowIntegrityError(
                "cached context-window bundle is incompatible"
            )
        return stored, stored_report, root, True
    _atomic(paths[0], canonical_bytes(bundle))
    _atomic(paths[1], canonical_bytes(report))
    _atomic(
        paths[2], context_window_report_markdown(report).encode("utf-8")
    )
    return bundle, report, root, False


def load_context_windows(
    root: Path,
) -> tuple[ContextWindowBundle, ContextWindowReport]:
    root = root.expanduser().resolve(strict=True)
    return (
        load_contract(
            (root / "bundle.json").read_bytes(), ContextWindowBundle
        ),
        load_contract(
            (root / "report.json").read_bytes(), ContextWindowReport
        ),
    )
