"""Phase 5 lineage, evidence-span, selection, and persistence validation."""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path

from .contracts import Severity
from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase4_contracts import Utterance, UtteranceCorpus
from .phase5_contracts import (
    CandidateDisposition,
    DiscourseCorpus,
    DiscourseEvidenceSpan,
    DiscourseTargetStatus,
    DiscourseTargetType,
    Phase5IntegrityFinding,
    Phase5IntegrityResult,
)


class Phase5IntegrityError(RuntimeError):
    """Phase 5 evidence is corrupt, incompatible, or unsafe to reuse."""


def _finding(
    code: str,
    message: str,
    *artifact_ids: str,
    severity: Severity = Severity.ERROR,
) -> Phase5IntegrityFinding:
    return Phase5IntegrityFinding(
        finding_id=typed_id(
            "phase5finding", code, message, artifact_ids, severity.value
        ),
        code=code,
        severity=severity,
        message=message,
        artifact_ids=artifact_ids,
    )


def _source_span_is_contained(
    span: DiscourseEvidenceSpan, utterance: Utterance
) -> bool:
    start = span.source_interval.start_microseconds
    end = start + span.source_interval.duration_microseconds
    return any(
        start >= item.start_microseconds
        and end <= item.start_microseconds + item.duration_microseconds
        for item in utterance.source_intervals
    )


def _validate_span(
    span: DiscourseEvidenceSpan,
    utterance: Utterance,
) -> tuple[Phase5IntegrityFinding, ...]:
    findings = []
    views = {
        item.view_id: item
        for item in utterance.text_views
    }
    view = views.get(span.utterance_text_view_id)
    if view is None:
        findings.append(
            _finding(
                "phase5.span.unknown_text_view",
                "Evidence span references an unknown Phase 4 text view.",
                span.span_id,
                utterance.utterance_id,
            )
        )
    elif (
        span.end_text_offset > len(view.text)
        or view.text[span.start_text_offset:span.end_text_offset]
        != span.exact_displayed_text
    ):
        findings.append(
            _finding(
                "phase5.span.text_mismatch",
                "Evidence offsets do not reproduce the declared exact text.",
                span.span_id,
                utterance.utterance_id,
            )
        )
    known_words = {
        word_id
        for component in utterance.components
        for word_id in component.transcript_word_ids
    }
    if not set(span.transcript_word_ids).issubset(known_words):
        findings.append(
            _finding(
                "phase5.span.invalid_words",
                "Evidence span references words outside its utterance.",
                span.span_id,
                utterance.utterance_id,
            )
        )
    if not _source_span_is_contained(span, utterance):
        findings.append(
            _finding(
                "phase5.span.source_interval_mismatch",
                "Evidence source interval lies outside its utterance.",
                span.span_id,
                utterance.utterance_id,
            )
        )
    return tuple(findings)


def validate_discourse_corpus(
    corpus: DiscourseCorpus,
    phase4_corpus: UtteranceCorpus,
    *,
    checked_at: datetime,
) -> Phase5IntegrityResult:
    """Validate Phase 5 against the exact immutable Phase 4 input."""
    findings: list[Phase5IntegrityFinding] = []
    phase4_hash = canonical_hash(phase4_corpus)
    if (
        corpus.phase4_utterance_corpus_id != phase4_corpus.corpus_id
        or corpus.source_corpus_id != phase4_corpus.source_corpus_id
        or corpus.source_id != phase4_corpus.source_id
    ):
        findings.append(
            _finding(
                "phase5.lineage.incompatible",
                "Discourse corpus lineage does not match its Phase 4 input.",
                corpus.corpus_id,
                phase4_corpus.corpus_id,
            )
        )
    if corpus.phase4_utterance_corpus_sha256 != phase4_hash:
        findings.append(
            _finding(
                "phase5.lineage.source_hash_mismatch",
                "Declared Phase 4 corpus digest does not match the input.",
                corpus.corpus_id,
                phase4_corpus.corpus_id,
            )
        )

    utterances = {
        item.utterance_id: item for item in phase4_corpus.utterances
    }
    observations = {
        item.observation_id: item for item in corpus.observations
    }
    candidate_sets = {
        item.candidate_set_id: item for item in corpus.candidate_sets
    }
    acts = {item.act_id: item for item in corpus.selected_acts}

    for observation in corpus.observations:
        utterance = utterances.get(observation.utterance_id)
        if utterance is None:
            findings.append(
                _finding(
                    "phase5.observation.unknown_utterance",
                    "Discourse observation targets an unknown utterance.",
                    observation.observation_id,
                    observation.utterance_id,
                )
            )
            continue
        for span in observation.evidence_spans:
            findings.extend(_validate_span(span, utterance))
        for proposal in observation.proposed_targets:
            if proposal.target_status not in {
                DiscourseTargetStatus.IDENTIFIED,
                DiscourseTargetStatus.PROBABLE,
            }:
                continue
            known = (
                proposal.target_id in utterances
                if proposal.target_type == DiscourseTargetType.UTTERANCE
                else (
                    proposal.target_id in acts
                    if proposal.target_type == DiscourseTargetType.DISCOURSE_ACT
                    else True
                )
            )
            if not known:
                findings.append(
                    _finding(
                        "phase5.relation.unknown_target",
                        "Relation proposal targets an unknown artifact.",
                        proposal.proposal_id,
                        proposal.target_id or "unresolved",
                    )
                )

    for candidate_set in corpus.candidate_sets:
        if candidate_set.utterance_id not in utterances:
            findings.append(
                _finding(
                    "phase5.candidates.unknown_utterance",
                    "Candidate set targets an unknown utterance.",
                    candidate_set.candidate_set_id,
                    candidate_set.utterance_id,
                )
            )
        for candidate in candidate_set.candidates:
            if not set(candidate.observation_ids).issubset(observations):
                findings.append(
                    _finding(
                        "phase5.candidates.unknown_observation",
                        "Candidate references an unknown observation.",
                        candidate.candidate_id,
                    )
                )

    for act in corpus.selected_acts:
        candidate_set = candidate_sets.get(act.candidate_set_id)
        candidate = (
            next(
                (
                    item
                    for item in candidate_set.candidates
                    if item.candidate_id == act.selected_candidate_id
                ),
                None,
            )
            if candidate_set is not None
            else None
        )
        if (
            candidate is None
            or candidate.disposition != CandidateDisposition.SELECTED
            or candidate.act_family != act.act_family
            or candidate.act_type != act.act_type
        ):
            findings.append(
                _finding(
                    "phase5.act.invalid_selection",
                    "Canonical act does not match a selected candidate.",
                    act.act_id,
                )
            )
        utterance = utterances.get(act.utterance_id)
        if utterance is not None:
            for span in act.evidence_spans:
                findings.extend(_validate_span(span, utterance))

    covered = (
        {item.utterance_id for item in corpus.selected_acts}
        | set(corpus.unclassified_utterance_ids)
    )
    if covered != set(utterances):
        findings.append(
            _finding(
                "phase5.corpus.incomplete_coverage",
                "Every Phase 4 utterance must be classified or explicitly "
                "unclassified.",
                corpus.corpus_id,
            )
        )

    valid = not any(
        item.severity in {Severity.ERROR, Severity.FATAL}
        for item in findings
    )
    provisional = Phase5IntegrityResult(
        result_id=typed_id(
            "phase5integrity",
            corpus.corpus_id,
            phase4_corpus.corpus_id,
            tuple(item.model_dump(mode="json") for item in findings),
        ),
        discourse_corpus_id=corpus.corpus_id,
        phase4_utterance_corpus_id=phase4_corpus.corpus_id,
        checked_at=checked_at,
        findings=tuple(findings),
        valid=valid,
        integrity_sha256="0" * 64,
    )
    return provisional.model_copy(
        update={
            "integrity_sha256": canonical_hash(
                provisional.model_copy(
                    update={"integrity_sha256": "0" * 64}
                )
            )
        }
    )


def seal_discourse_corpus(corpus: DiscourseCorpus) -> DiscourseCorpus:
    empty = corpus.model_copy(update={"integrity_sha256": "0" * 64})
    return corpus.model_copy(
        update={"integrity_sha256": canonical_hash(empty)}
    )


def validate_discourse_corpus_seal(corpus: DiscourseCorpus) -> None:
    if seal_discourse_corpus(
        corpus.model_copy(update={"integrity_sha256": "0" * 64})
    ) != corpus:
        raise Phase5IntegrityError("discourse corpus integrity is invalid")


def persist_discourse_corpus(
    corpus: DiscourseCorpus,
    phase4_corpus: UtteranceCorpus,
    destination: Path,
    *,
    checked_at: datetime,
) -> Path:
    validate_discourse_corpus_seal(corpus)
    result = validate_discourse_corpus(
        corpus, phase4_corpus, checked_at=checked_at
    )
    if not result.valid:
        raise Phase5IntegrityError(
            "discourse corpus failed Phase 4 lineage or evidence validation"
        )
    path = destination.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        stored = load_contract(path.read_bytes(), DiscourseCorpus)
        if stored != corpus:
            raise Phase5IntegrityError(
                "persisted discourse corpus conflicts"
            )
        return path
    temporary = path.with_name(f"{path.name}.partial-{uuid.uuid4().hex}")
    temporary.write_bytes(canonical_bytes(corpus))
    os.replace(temporary, path)
    return path


def load_discourse_corpus(
    path: Path,
    phase4_corpus: UtteranceCorpus,
    *,
    checked_at: datetime,
) -> DiscourseCorpus:
    corpus = load_contract(
        path.expanduser().resolve(strict=True).read_bytes(), DiscourseCorpus
    )
    validate_discourse_corpus_seal(corpus)
    result = validate_discourse_corpus(
        corpus, phase4_corpus, checked_at=checked_at
    )
    if not result.valid:
        raise Phase5IntegrityError(
            "loaded discourse corpus failed source validation"
        )
    return corpus
