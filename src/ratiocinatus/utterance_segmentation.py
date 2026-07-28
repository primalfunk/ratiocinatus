"""Deterministic Phase 4 utterance construction over Phase 2/3 views."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase2_contracts import ConfidenceMeasure, ConfidenceOrigin
from .diarization_normalization import validate_diarization_run
from .phase3_contracts import DiarizationRun
from .phase4_contracts import (
    Phase4IntegrityResult,
    SpeechSourceType,
    Utterance,
    UtteranceAttribution,
    UtteranceAttributionStatus,
    UtteranceAttributionTargetKind,
    UtteranceCompletenessClassification,
    UtteranceComponent,
    UtteranceCorpus,
    UtteranceCorpusReport,
    UtteranceCreationProcess,
    UtteranceInterruptionStatus,
    UtteranceNormalizationPolicy,
    UtteranceOverlapStatus,
    UtteranceQuotationStatus,
    UtteranceRepairStatus,
    UtteranceReviewStatus,
    UtteranceRun,
    UtteranceSegmentationPolicy,
    UtteranceTextKind,
    UtteranceTextView,
)
from .speaker_transcript_contracts import (
    SpeakerAttributionKind,
    SpeakerAttributionSpan,
    SpeakerLabeledTranscriptSegment,
    SpeakerLabeledTranscriptView,
)
from .transcript_assembly import validate_transcript_assembly
from .transcript_contracts import TranscriptAssembly, TranscriptWord


class UtteranceSegmentationIntegrityError(RuntimeError):
    """Phase 4 utterance evidence is incomplete, corrupt, or incompatible."""


@dataclass(frozen=True)
class _Atom:
    component: UtteranceComponent
    span: SpeakerAttributionSpan
    segment: SpeakerLabeledTranscriptSegment
    ambiguous_word_ids: tuple[str, ...]


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
        raise UtteranceSegmentationIntegrityError(
            f"{label} integrity is invalid"
        )


def _end(interval) -> int:
    return interval.start_microseconds + interval.duration_microseconds


def _intersection_duration(left, right) -> int:
    return max(
        0,
        min(_end(left), _end(right))
        - max(left.start_microseconds, right.start_microseconds),
    )


def _speaker_view_lineage(
    assembly: TranscriptAssembly,
    speaker_view: SpeakerLabeledTranscriptView,
    diarization: DiarizationRun,
) -> None:
    validate_transcript_assembly(assembly)
    validate_diarization_run(diarization)
    _verify_seal(speaker_view, "speaker-labeled transcript")
    if (
        speaker_view.source_assembly_id != assembly.assembly_id
        or speaker_view.source_transcript_version_id
        != assembly.version.version_id
        or speaker_view.corpus_id != assembly.version.corpus_id
        or speaker_view.diarization_run_id != diarization.run_id
        or diarization.corpus_id != assembly.version.corpus_id
        or diarization.source_id != assembly.source_id
    ):
        raise UtteranceSegmentationIntegrityError(
            "transcript and speaker-view lineage is incompatible"
        )


def _word_owners(
    assembly: TranscriptAssembly,
    speaker_view: SpeakerLabeledTranscriptView,
) -> tuple[dict[str, str], set[str]]:
    spans = tuple(
        span
        for segment in speaker_view.segments
        for span in segment.attribution_spans
    )
    owners: dict[str, str] = {}
    ambiguous: set[str] = set()
    words = {item.word_id: item for item in assembly.words}
    for word_id, word in words.items():
        candidates = tuple(
            span
            for span in spans
            if word_id in span.transcript_word_ids
            and _intersection_duration(
                word.normalized_audio_interval,
                span.normalized_audio_interval,
            )
            > 0
        )
        if not candidates:
            continue
        ranked = sorted(
            (
                (
                    _intersection_duration(
                        word.normalized_audio_interval,
                        span.normalized_audio_interval,
                    ),
                    -span.normalized_audio_interval.start_microseconds,
                    span.span_id,
                )
                for span in candidates
            ),
            reverse=True,
        )
        owners[word_id] = ranked[0][2]
        if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
            ambiguous.add(word_id)
    return owners, ambiguous


def _component(
    segment: SpeakerLabeledTranscriptSegment,
    span: SpeakerAttributionSpan,
    words: dict[str, TranscriptWord],
    owners: dict[str, str],
    ambiguous: set[str],
    turn_observations: dict[str, tuple[str, ...]],
) -> _Atom:
    owned = tuple(
        sorted(
            (
                words[word_id]
                for word_id in span.transcript_word_ids
                if word_id in words and owners.get(word_id) == span.span_id
            ),
            key=lambda item: (
                item.normalized_audio_interval.start_microseconds,
                item.sequence_position,
                item.word_id,
            ),
        )
    )
    word_ids = tuple(item.word_id for item in owned)
    uncertain = tuple(item for item in word_ids if item in ambiguous)
    text = " ".join(item.surface_text for item in owned)
    findings = []
    if uncertain:
        findings.append(
            "Equal temporal support crossed a speaker boundary; the stable "
            "earlier span owns the word pending review."
        )
    if not word_ids:
        findings.append(
            "Attribution span has no uniquely owned canonical transcript word."
        )
    payload = {
        "component_id": "utterancecomponent_" + "0" * 32,
        "sequence_position": 0,
        "source_interval": span.source_interval,
        "normalized_audio_interval": span.normalized_audio_interval,
        "transcript_segment_ids": span.transcript_segment_ids,
        "transcript_word_ids": word_ids,
        "speaker_turn_ids": span.speaker_turn_ids,
        "speaker_observation_ids": tuple(
            dict.fromkeys(
                observation_id
                for turn_id in span.speaker_turn_ids
                for observation_id in turn_observations.get(turn_id, ())
            )
        ),
        "verbatim_text": text,
        "uncertain_word_attribution": bool(uncertain),
        "processing_chunk_ids": (),
        "findings": tuple(findings),
    }
    provisional = _seal(UtteranceComponent, payload)
    payload["component_id"] = typed_id(
        "utterancecomponent",
        segment.segment_id,
        span.span_id,
        provisional.model_dump(
            mode="json", exclude={"component_id", "integrity_sha256"}
        ),
    )
    return _Atom(
        component=_seal(UtteranceComponent, payload),
        span=span,
        segment=segment,
        ambiguous_word_ids=uncertain,
    )


def _attribution_signature(span: SpeakerAttributionSpan) -> tuple:
    return (
        span.attribution_kind,
        span.identity_ids,
        span.reviewed_labels,
        span.original_machine_labels,
        span.identity_view_entry_ids,
    )


def _should_merge(
    left: _Atom,
    right: _Atom,
    policy: UtteranceSegmentationPolicy,
) -> bool:
    left_end = _end(left.component.normalized_audio_interval)
    right_start = right.component.normalized_audio_interval.start_microseconds
    gap = right_start - left_end
    if gap < 0:
        return False
    if gap > policy.maximum_gap_microseconds:
        return False
    if _attribution_signature(left.span) != _attribution_signature(right.span):
        return False
    if (
        left.span.overlap_disclosed
        or right.span.overlap_disclosed
        or left.component.uncertain_word_attribution
        or right.component.uncertain_word_attribution
    ):
        return False
    if (
        policy.punctuation_is_soft_indicator
        and left.component.verbatim_text.rstrip().endswith((".", "?", "!"))
    ):
        return False
    return True


def _groups(
    atoms: tuple[_Atom, ...],
    policy: UtteranceSegmentationPolicy,
) -> tuple[tuple[_Atom, ...], ...]:
    groups: list[list[_Atom]] = []
    for atom in atoms:
        if groups and _should_merge(groups[-1][-1], atom, policy):
            groups[-1].append(atom)
        else:
            groups.append([atom])
    return tuple(tuple(group) for group in groups)


def _confidence(basis: str) -> ConfidenceMeasure:
    return ConfidenceMeasure(
        origin=ConfidenceOrigin.UNAVAILABLE,
        basis=basis,
    )


def _attribution(
    group: tuple[_Atom, ...],
    speaker_view: SpeakerLabeledTranscriptView,
) -> UtteranceAttribution:
    spans = tuple(item.span for item in group)
    first = spans[0]
    identities = tuple(sorted({value for item in spans for value in item.identity_ids}))
    reviewed = tuple(
        sorted({value for item in spans for value in item.reviewed_labels})
    )
    machine = tuple(
        sorted({value for item in spans for value in item.original_machine_labels})
    )
    entries = tuple(
        sorted(
            {value for item in spans for value in item.identity_view_entry_ids}
        )
    )
    findings = tuple(
        sorted({value for item in spans for value in item.findings})
    )
    if first.attribution_kind == SpeakerAttributionKind.REVIEWED and len(identities) == 1:
        status = UtteranceAttributionStatus.MANUALLY_BOUND
        target_kind = UtteranceAttributionTargetKind.PARTICIPANT_IDENTITY
        target_id = identities[0]
        candidates = ()
    elif first.attribution_kind == SpeakerAttributionKind.MACHINE_CLUSTER and machine:
        status = UtteranceAttributionStatus.MACHINE_CLUSTERED
        target_kind = UtteranceAttributionTargetKind.SPEAKER_CLUSTER
        target_id = machine[0]
        candidates = ()
    elif first.attribution_kind in {
        SpeakerAttributionKind.MULTIPLE_CANDIDATES,
        SpeakerAttributionKind.CONFLICTED,
    }:
        candidates = tuple(
            dict.fromkeys((*identities, *entries, *reviewed, *machine))
        )
        if len(candidates) >= 2:
            status = UtteranceAttributionStatus.CONFLICTING
            target_kind = UtteranceAttributionTargetKind.MULTIPLE_CANDIDATES
            target_id = None
        else:
            status = UtteranceAttributionStatus.UNKNOWN
            target_kind = UtteranceAttributionTargetKind.UNKNOWN
            target_id = None
            candidates = ()
            findings = (
                *findings,
                "Conflict lacked two stable candidate targets and degraded "
                "conservatively to unknown.",
            )
    else:
        status = UtteranceAttributionStatus.UNKNOWN
        target_kind = UtteranceAttributionTargetKind.UNKNOWN
        target_id = None
        candidates = ()
    labels = reviewed or machine
    display = " + ".join(labels) if labels else "UNKNOWN"
    payload = {
        "attribution_id": "utteranceattr_" + "0" * 32,
        "status": status,
        "target_kind": target_kind,
        "target_id": target_id,
        "candidate_target_ids": candidates,
        "display_label": display,
        "confidence": _confidence(
            "Phase 4 preserves the Phase 3 attribution disposition without "
            "manufacturing a new probability."
        ),
        "phase3_identity_view_assembly_id": (
            speaker_view.identity_view_assembly_id
        ),
        "phase3_reviewed_identity_view_id": (
            speaker_view.reviewed_identity_view_id
        ),
        "speaker_turn_ids": tuple(
            sorted({value for item in spans for value in item.speaker_turn_ids})
        ),
        "speaker_observation_ids": (),
        "evidence_references": tuple(
            dict.fromkeys(
                (
                    speaker_view.view_id,
                    *(item.span_id for item in spans),
                    *entries,
                )
            )
        ),
        "findings": findings,
    }
    provisional = _seal(UtteranceAttribution, payload)
    payload["attribution_id"] = typed_id(
        "utteranceattr",
        speaker_view.view_id,
        provisional.model_dump(
            mode="json", exclude={"attribution_id", "integrity_sha256"}
        ),
    )
    return _seal(UtteranceAttribution, payload)


def _text_view(
    corpus_id: str,
    kind: UtteranceTextKind,
    text: str,
    group: tuple[_Atom, ...],
    derivation: str,
) -> UtteranceTextView:
    segment_ids = tuple(
        dict.fromkeys(
            value
            for atom in group
            for value in atom.component.transcript_segment_ids
        )
    )
    word_ids = tuple(
        value
        for atom in group
        for value in atom.component.transcript_word_ids
    )
    payload = {
        "view_id": typed_id(
            "utterancetext",
            corpus_id,
            kind.value,
            text,
            segment_ids,
            word_ids,
            derivation,
        ),
        "kind": kind,
        "text": text,
        "derivation_policy": derivation,
        "source_transcript_segment_ids": segment_ids,
        "source_transcript_word_ids": word_ids,
    }
    return _seal(UtteranceTextView, payload)


def _resequence(group: tuple[_Atom, ...]) -> tuple[UtteranceComponent, ...]:
    components = []
    for position, atom in enumerate(group):
        payload = atom.component.model_dump(
            exclude={"component_id", "integrity_sha256"}
        )
        payload["sequence_position"] = position
        payload["component_id"] = typed_id(
            "utterancecomponent",
            atom.component.component_id,
            position,
        )
        components.append(_seal(UtteranceComponent, payload))
    return tuple(components)


def _utterance(
    corpus_id: str,
    assembly: TranscriptAssembly,
    speaker_view: SpeakerLabeledTranscriptView,
    group: tuple[_Atom, ...],
    policy: UtteranceSegmentationPolicy,
    normalization_policy: UtteranceNormalizationPolicy,
    configuration_hash: str,
    created_at: datetime,
) -> Utterance:
    components = _resequence(group)
    attribution = _attribution(group, speaker_view)
    words = {
        item.word_id: item
        for item in assembly.words
        if any(
            item.word_id in component.transcript_word_ids
            for component in components
        )
    }
    ordered_words = tuple(
        sorted(
            words.values(),
            key=lambda item: (
                item.normalized_audio_interval.start_microseconds,
                item.sequence_position,
                item.word_id,
            ),
        )
    )
    raw_text = " ".join(item.surface_text for item in ordered_words)
    normalized_text = " ".join(item.normalized_form for item in ordered_words)
    raw = _text_view(
        corpus_id,
        UtteranceTextKind.RAW_MACHINE_TRANSCRIPT,
        raw_text,
        group,
        "Concatenate uniquely owned canonical Phase 2 word surfaces in time order.",
    )
    display = _text_view(
        corpus_id,
        UtteranceTextKind.DISPLAY,
        raw_text,
        group,
        "Initial display preserves canonical Phase 2 surface words.",
    )
    analysis = _text_view(
        corpus_id,
        UtteranceTextKind.MINIMALLY_NORMALIZED_ANALYSIS,
        normalized_text,
        group,
        "Concatenate canonical normalized word forms without adding content.",
    )
    duration = sum(
        item.normalized_audio_interval.duration_microseconds
        for item in components
    )
    ambiguous = tuple(
        value for atom in group for value in atom.ambiguous_word_ids
    )
    if not raw_text:
        completeness = UtteranceCompletenessClassification.NON_LEXICAL
        completeness_evidence = (
            "No canonical lexical word is uniquely owned by this interval.",
        )
    elif duration < policy.minimum_utterance_duration_microseconds:
        completeness = UtteranceCompletenessClassification.FRAGMENT
        completeness_evidence = (
            "Duration is below the configured minimum utterance duration.",
        )
    elif raw_text.rstrip().endswith((".", "?", "!")):
        completeness = UtteranceCompletenessClassification.COMPLETE
        completeness_evidence = (
            "Terminal punctuation and a bounded Phase 3 attribution span "
            "jointly support provisional completeness.",
        )
    else:
        completeness = UtteranceCompletenessClassification.UNKNOWN
        completeness_evidence = (
            "The initial deterministic evidence does not establish completeness.",
        )
    overlap = (
        UtteranceOverlapStatus.PRESERVED
        if any(item.span.overlap_disclosed for item in group)
        else UtteranceOverlapStatus.NONE
    )
    review = (
        UtteranceReviewStatus.REVIEW_REQUIRED
        if (
            completeness == UtteranceCompletenessClassification.UNKNOWN
            or attribution.status
            in {
                UtteranceAttributionStatus.UNKNOWN,
                UtteranceAttributionStatus.CONFLICTING,
            }
            or ambiguous
            or any(not item.transcript_word_ids for item in components)
        )
        else UtteranceReviewStatus.UNREVIEWED
    )
    source_intervals = tuple(item.source_interval for item in components)
    normalized_intervals = tuple(
        item.normalized_audio_interval for item in components
    )
    identity_payload = {
        "corpus_id": corpus_id,
        "component_ids": tuple(item.component_id for item in components),
        "attribution_id": attribution.attribution_id,
        "text_view_ids": (raw.view_id, display.view_id, analysis.view_id),
        "completeness": completeness.value,
        "overlap": overlap.value,
        "review": review.value,
        "configuration_hash": configuration_hash,
    }
    payload = {
        "utterance_id": typed_id("utterance", identity_payload),
        "utterance_corpus_id": corpus_id,
        "source_corpus_id": assembly.version.corpus_id,
        "source_id": assembly.source_id,
        "phase2_transcript_assembly_id": assembly.assembly_id,
        "phase2_transcript_version_id": assembly.version.version_id,
        "phase3_identity_view_assembly_id": (
            speaker_view.identity_view_assembly_id
        ),
        "phase3_reviewed_identity_view_id": (
            speaker_view.reviewed_identity_view_id
        ),
        "components": components,
        "source_intervals": source_intervals,
        "normalized_audio_intervals": normalized_intervals,
        "attribution": attribution,
        "text_views": (raw, display, analysis),
        "displayed_text_view_id": display.view_id,
        "completeness": completeness,
        "completeness_evidence_references": completeness_evidence,
        "interruption_status": UtteranceInterruptionStatus.NONE,
        "repair_status": UtteranceRepairStatus.NONE,
        "overlap_status": overlap,
        "quotation_status": UtteranceQuotationStatus.NONE,
        "speech_source_type": SpeechSourceType.PRIMARY_SOURCE_PARTICIPANT,
        "review_status": review,
        "creation_process": (
            UtteranceCreationProcess.DETERMINISTIC_SEGMENTATION
        ),
        "segmentation_policy_version": policy.policy_version,
        "normalization_policy_version": normalization_policy.policy_version,
        "configuration_hash": configuration_hash,
        "created_at": created_at,
    }
    return _seal(Utterance, payload)


def build_utterance_corpus(
    assembly: TranscriptAssembly,
    speaker_view: SpeakerLabeledTranscriptView,
    diarization: DiarizationRun,
    *,
    policy: UtteranceSegmentationPolicy | None = None,
    normalization_policy: UtteranceNormalizationPolicy | None = None,
    created_at: datetime | None = None,
) -> tuple[UtteranceRun, UtteranceCorpus]:
    _speaker_view_lineage(assembly, speaker_view, diarization)
    selected_policy = policy or UtteranceSegmentationPolicy()
    selected_normalization = (
        normalization_policy or UtteranceNormalizationPolicy()
    )
    timestamp = created_at or speaker_view.created_at
    configuration_hash = canonical_hash(
        {
            "operation": "utterance.initial_segmentation",
            "phase2_transcript_assembly_id": assembly.assembly_id,
            "phase2_transcript_version_id": assembly.version.version_id,
            "speaker_transcript_view_id": speaker_view.view_id,
            "diarization_run_id": diarization.run_id,
            "identity_view_assembly_id": (
                speaker_view.identity_view_assembly_id
            ),
            "reviewed_identity_view_id": (
                speaker_view.reviewed_identity_view_id
            ),
            "segmentation_policy": selected_policy.model_dump(mode="json"),
            "normalization_policy": selected_normalization.model_dump(
                mode="json"
            ),
        }
    )
    corpus_id = typed_id(
        "utterancecorpus",
        assembly.version.corpus_id,
        configuration_hash,
    )
    words = {item.word_id: item for item in assembly.words}
    owners, ambiguous = _word_owners(assembly, speaker_view)
    turn_observations = {
        item.turn_id: item.observation_ids for item in diarization.turns
    }
    atoms = tuple(
        sorted(
            (
                _component(
                    segment,
                    span,
                    words,
                    owners,
                    ambiguous,
                    turn_observations,
                )
                for segment in speaker_view.segments
                for span in segment.attribution_spans
            ),
            key=lambda item: (
                item.component.normalized_audio_interval.start_microseconds,
                item.component.component_id,
            ),
        )
    )
    owned_word_ids = {
        word_id
        for atom in atoms
        for word_id in atom.component.transcript_word_ids
    }
    canonical_word_ids = {item.word_id for item in assembly.words}
    if owned_word_ids != canonical_word_ids:
        missing = tuple(sorted(canonical_word_ids - owned_word_ids))
        raise UtteranceSegmentationIntegrityError(
            "canonical transcript words lack utterance ownership: "
            + ", ".join(missing)
        )
    utterances = tuple(
        _utterance(
            corpus_id,
            assembly,
            speaker_view,
            group,
            selected_policy,
            selected_normalization,
            configuration_hash,
            timestamp,
        )
        for group in _groups(atoms, selected_policy)
    )
    run_id = typed_id(
        "utterancerun",
        corpus_id,
        tuple(item.utterance_id for item in utterances),
        configuration_hash,
    )
    run = _seal(
        UtteranceRun,
        {
            "run_id": run_id,
            "utterance_corpus_id": corpus_id,
            "source_corpus_id": assembly.version.corpus_id,
            "phase2_transcript_assembly_id": assembly.assembly_id,
            "phase2_transcript_version_id": assembly.version.version_id,
            "phase3_diarization_run_id": speaker_view.diarization_run_id,
            "phase3_identity_view_assembly_id": (
                speaker_view.identity_view_assembly_id
            ),
            "phase3_reviewed_identity_view_id": (
                speaker_view.reviewed_identity_view_id
            ),
            "segmentation_policy": selected_policy,
            "normalization_policy": selected_normalization,
            "configuration_hash": configuration_hash,
            "utterance_ids": tuple(
                item.utterance_id for item in utterances
            ),
            "created_at": timestamp,
            "complete": True,
        },
    )
    corpus = _seal(
        UtteranceCorpus,
        {
            "corpus_id": corpus_id,
            "run_id": run_id,
            "source_corpus_id": assembly.version.corpus_id,
            "source_id": assembly.source_id,
            "phase2_transcript_assembly_id": assembly.assembly_id,
            "phase2_transcript_version_id": assembly.version.version_id,
            "phase3_identity_view_assembly_id": (
                speaker_view.identity_view_assembly_id
            ),
            "phase3_reviewed_identity_view_id": (
                speaker_view.reviewed_identity_view_id
            ),
            "utterances": utterances,
            "created_at": timestamp,
        },
    )
    validate_utterance_corpus(
        run, corpus, assembly, speaker_view, diarization
    )
    return run, corpus


def _report(run: UtteranceRun, corpus: UtteranceCorpus) -> UtteranceCorpusReport:
    complete = sum(
        item.completeness
        in {
            UtteranceCompletenessClassification.COMPLETE,
            UtteranceCompletenessClassification.GRAMMATICALLY_INCOMPLETE_DISCOURSE_COMPLETE,
        }
        for item in corpus.utterances
    )
    status = (
        "warning"
        if any(
            item.review_status == UtteranceReviewStatus.REVIEW_REQUIRED
            for item in corpus.utterances
        )
        else "complete"
    )
    return _seal(
        UtteranceCorpusReport,
        {
            "report_id": typed_id(
                "utterancereport",
                corpus.corpus_id,
                tuple(item.utterance_id for item in corpus.utterances),
            ),
            "utterance_corpus_id": corpus.corpus_id,
            "run_id": run.run_id,
            "generated_at": corpus.created_at,
            "utterance_count": len(corpus.utterances),
            "complete_count": complete,
            "incomplete_count": len(corpus.utterances) - complete,
            "unknown_attribution_count": sum(
                item.attribution.status
                == UtteranceAttributionStatus.UNKNOWN
                for item in corpus.utterances
            ),
            "conflicting_attribution_count": sum(
                item.attribution.status
                == UtteranceAttributionStatus.CONFLICTING
                for item in corpus.utterances
            ),
            "overlap_aware_count": sum(
                item.overlap_status != UtteranceOverlapStatus.NONE
                for item in corpus.utterances
            ),
            "review_required_count": sum(
                item.review_status == UtteranceReviewStatus.REVIEW_REQUIRED
                for item in corpus.utterances
            ),
            "findings": (
                "Initial segmentation preserves unknown attribution and "
                "uncertain word-boundary ownership.",
            ),
            "limitations": (
                "This deterministic foundation does not perform syntactic or "
                "semantic completion analysis.",
                "Interruption, continuation, repair, and quotation relations "
                "remain later Phase 4 stages.",
            ),
            "status": status,
        },
    )


def validate_utterance_corpus(
    run: UtteranceRun,
    corpus: UtteranceCorpus,
    assembly: TranscriptAssembly,
    speaker_view: SpeakerLabeledTranscriptView,
    diarization: DiarizationRun,
    *,
    report: UtteranceCorpusReport | None = None,
) -> Phase4IntegrityResult:
    _speaker_view_lineage(assembly, speaker_view, diarization)
    _verify_seal(run, "utterance run")
    _verify_seal(corpus, "utterance corpus")
    for utterance in corpus.utterances:
        _verify_seal(utterance, utterance.utterance_id)
        _verify_seal(utterance.attribution, utterance.attribution.attribution_id)
        for component in utterance.components:
            _verify_seal(component, component.component_id)
        for text_view in utterance.text_views:
            _verify_seal(text_view, text_view.view_id)
    if (
        corpus.run_id != run.run_id
        or corpus.corpus_id != run.utterance_corpus_id
        or run.utterance_ids
        != tuple(item.utterance_id for item in corpus.utterances)
        or corpus.phase2_transcript_assembly_id != assembly.assembly_id
        or corpus.phase2_transcript_version_id != assembly.version.version_id
        or corpus.phase3_identity_view_assembly_id
        != speaker_view.identity_view_assembly_id
        or corpus.phase3_reviewed_identity_view_id
        != speaker_view.reviewed_identity_view_id
        or run.phase3_diarization_run_id != diarization.run_id
    ):
        raise UtteranceSegmentationIntegrityError(
            "utterance run, corpus, and prior-phase lineage disagree"
        )
    owned_word_ids = [
        word_id
        for utterance in corpus.utterances
        for component in utterance.components
        for word_id in component.transcript_word_ids
    ]
    if (
        len(owned_word_ids) != len(set(owned_word_ids))
        or set(owned_word_ids) != {item.word_id for item in assembly.words}
    ):
        raise UtteranceSegmentationIntegrityError(
            "canonical transcript word ownership is incomplete or duplicated"
        )
    # Rebuilding is performed by persistence before cache comparison. Avoid
    # recursive validation here while still validating every sealed artifact.
    if report is not None:
        _verify_seal(report, "utterance corpus report")
        if report != _report(run, corpus):
            raise UtteranceSegmentationIntegrityError(
                "utterance corpus report projection is invalid"
            )
    result_payload = {
        "result_id": typed_id(
            "phase4integrity",
            corpus.corpus_id,
            run.integrity_sha256,
            corpus.integrity_sha256,
        ),
        "utterance_corpus_id": corpus.corpus_id,
        "checked_at": corpus.created_at,
        "findings": (),
        "valid": True,
    }
    return _seal(Phase4IntegrityResult, result_payload)


def utterance_report_markdown(report: UtteranceCorpusReport) -> str:
    return "\n".join(
        (
            "# Phase 4 initial utterance corpus report",
            "",
            f"- Corpus: `{report.utterance_corpus_id}`",
            f"- Utterances: {report.utterance_count}",
            f"- Complete: {report.complete_count}",
            f"- Incomplete or unresolved: {report.incomplete_count}",
            f"- Unknown attribution: {report.unknown_attribution_count}",
            f"- Conflicting attribution: {report.conflicting_attribution_count}",
            f"- Overlap-aware: {report.overlap_aware_count}",
            f"- Review required: {report.review_required_count}",
            f"- Status: {report.status}",
            "",
        )
    )


def persist_utterance_corpus(
    run: UtteranceRun,
    corpus: UtteranceCorpus,
    assembly: TranscriptAssembly,
    speaker_view: SpeakerLabeledTranscriptView,
    diarization: DiarizationRun,
    destination: Path,
) -> tuple[
    UtteranceRun,
    UtteranceCorpus,
    UtteranceCorpusReport,
    Path,
    bool,
]:
    destination = destination.expanduser().resolve()
    validate_utterance_corpus(
        run, corpus, assembly, speaker_view, diarization
    )
    expected_run, expected_corpus = build_utterance_corpus(
        assembly,
        speaker_view,
        diarization,
        policy=run.segmentation_policy,
        normalization_policy=run.normalization_policy,
        created_at=run.created_at,
    )
    if expected_run != run or expected_corpus != corpus:
        raise UtteranceSegmentationIntegrityError(
            "utterance corpus is not the deterministic source projection"
        )
    report = _report(run, corpus)
    root = destination / "utterance-corpora" / corpus.corpus_id
    paths = (
        root / "run.json",
        root / "corpus.json",
        root / "report.json",
        root / "report.md",
    )
    existing = tuple(path.exists() for path in paths)
    if any(existing) and not all(existing):
        raise UtteranceSegmentationIntegrityError(
            "cached utterance corpus is incomplete"
        )
    if all(existing):
        stored_run = load_contract(paths[0].read_bytes(), UtteranceRun)
        stored_corpus = load_contract(paths[1].read_bytes(), UtteranceCorpus)
        stored_report = load_contract(
            paths[2].read_bytes(), UtteranceCorpusReport
        )
        validate_utterance_corpus(
            stored_run,
            stored_corpus,
            assembly,
            speaker_view,
            diarization,
            report=stored_report,
        )
        if (
            stored_run != run
            or stored_corpus != corpus
            or stored_report != report
            or paths[3].read_text(encoding="utf-8")
            != utterance_report_markdown(report)
        ):
            raise UtteranceSegmentationIntegrityError(
                "cached utterance corpus is incompatible"
            )
        return stored_run, stored_corpus, stored_report, root, True
    _atomic(paths[0], canonical_bytes(run))
    _atomic(paths[1], canonical_bytes(corpus))
    _atomic(paths[2], canonical_bytes(report))
    _atomic(paths[3], utterance_report_markdown(report).encode("utf-8"))
    return run, corpus, report, root, False


def load_utterance_corpus(
    root: Path,
) -> tuple[UtteranceRun, UtteranceCorpus, UtteranceCorpusReport]:
    root = root.expanduser().resolve(strict=True)
    return (
        load_contract((root / "run.json").read_bytes(), UtteranceRun),
        load_contract((root / "corpus.json").read_bytes(), UtteranceCorpus),
        load_contract(
            (root / "report.json").read_bytes(), UtteranceCorpusReport
        ),
    )
