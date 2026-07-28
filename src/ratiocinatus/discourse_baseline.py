"""High-precision deterministic Phase 5 discourse-act observations."""

from __future__ import annotations

import os
import re
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .addressing_contracts import MediaInterval, TimeDomain
from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase2_contracts import ConfidenceMeasure, ConfidenceOrigin
from .phase4_contracts import Utterance, UtteranceCorpus, UtteranceTextKind
from .phase5_baseline_contracts import (
    DeterministicDiscoursePolicy,
    DeterministicDiscourseReport,
    DeterministicDiscourseRun,
)
from .phase5_contracts import (
    DiscourseActFamily,
    DiscourseActObservation,
    DiscourseActType,
    DiscourseAnalysisMethod,
    DiscourseConfidence,
    DiscourseEvidenceSpan,
    DiscourseEvidenceSpanRole,
    DiscourseReviewStatus,
)
from .quotation_contracts import (
    QuotationEvidenceRun,
    SpokenQuotation,
    SpokenQuotationType,
)


class DeterministicDiscourseIntegrityError(RuntimeError):
    """Deterministic discourse evidence is corrupt or incompatible."""


@dataclass(frozen=True)
class _Rule:
    rule_id: str
    family: DiscourseActFamily
    act_type: DiscourseActType
    pattern: re.Pattern[str]
    role: DiscourseEvidenceSpanRole
    confidence: float


def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


RULES: tuple[_Rule, ...] = (
    _Rule("assertive.denial", DiscourseActFamily.ASSERTIVE,
          DiscourseActType.DENIAL, _compile(r"\bI (?:deny|reject) that\b"),
          DiscourseEvidenceSpanRole.ACT_TRIGGER, 0.94),
    _Rule("assertive.affirmation", DiscourseActFamily.ASSERTIVE,
          DiscourseActType.AFFIRMATION, _compile(r"\bI affirm that\b"),
          DiscourseEvidenceSpanRole.ACT_TRIGGER, 0.96),
    _Rule("assertive.uncertainty", DiscourseActFamily.ASSERTIVE,
          DiscourseActType.UNCERTAINTY_STATEMENT,
          _compile(r"\b(?:I am not sure|I am uncertain|we do not know)\b"),
          DiscourseEvidenceSpanRole.ACT_TRIGGER, 0.96),
    _Rule("assertive.report", DiscourseActFamily.ASSERTIVE,
          DiscourseActType.REPORT,
          _compile(r"\b(?:the report|the record|the data) (?:says|shows)\b"),
          DiscourseEvidenceSpanRole.ACT_TRIGGER, 0.92),
    _Rule("question.clarification", DiscourseActFamily.QUESTION,
          DiscourseActType.CLARIFICATION_QUESTION,
          _compile(r"\b(?:what do you mean|could you clarify|please clarify)\b"),
          DiscourseEvidenceSpanRole.ACT_TRIGGER, 0.96),
    _Rule("question.procedural", DiscourseActFamily.QUESTION,
          DiscourseActType.PROCEDURAL_QUESTION,
          _compile(r"\b(?:can|could|shall) we (?:move on|continue|proceed)\b"),
          DiscourseEvidenceSpanRole.PROCEDURAL_FORMULA, 0.95),
    _Rule("question.information", DiscourseActFamily.QUESTION,
          DiscourseActType.INFORMATION_QUESTION,
          _compile(r"^\s*(?:who|what|when|where|why|how)\b[^?]*\?"),
          DiscourseEvidenceSpanRole.ACT_CONTENT, 0.91),
    _Rule("question.yes_no", DiscourseActFamily.QUESTION,
          DiscourseActType.YES_NO_QUESTION,
          _compile(
              r"^\s*(?:do|does|did|is|are|was|were|can|could|would|will|"
              r"should|have|has)\b[^?]*\?"
          ), DiscourseEvidenceSpanRole.ACT_CONTENT, 0.90),
    _Rule("procedural.time_warning", DiscourseActFamily.PROCEDURAL,
          DiscourseActType.TIME_WARNING,
          _compile(r"\b(?:you have|there (?:is|are)) \w+ "
                   r"(?:seconds?|minutes?) (?:left|remaining)\b"),
          DiscourseEvidenceSpanRole.PROCEDURAL_FORMULA, 0.97),
    _Rule("procedural.time_expired", DiscourseActFamily.PROCEDURAL,
          DiscourseActType.TIME_EXPIRED_NOTICE,
          _compile(r"\b(?:time is up|time has expired|your time is up)\b"),
          DiscourseEvidenceSpanRole.PROCEDURAL_FORMULA, 0.98),
    _Rule("procedural.request_answer", DiscourseActFamily.PROCEDURAL,
          DiscourseActType.REQUEST_TO_ANSWER,
          _compile(r"\b(?:please|kindly) answer (?:the question|that)\b"),
          DiscourseEvidenceSpanRole.PROCEDURAL_FORMULA, 0.97),
    _Rule("procedural.floor_grant", DiscourseActFamily.PROCEDURAL,
          DiscourseActType.FLOOR_GRANT,
          _compile(r"\b(?:you may respond|go ahead|the floor is yours)\b"),
          DiscourseEvidenceSpanRole.PROCEDURAL_FORMULA, 0.98),
    _Rule("procedural.topic_transition", DiscourseActFamily.PROCEDURAL,
          DiscourseActType.TOPIC_TRANSITION,
          _compile(r"\b(?:let us|let's|we will) move (?:on|to)\b"),
          DiscourseEvidenceSpanRole.PROCEDURAL_FORMULA, 0.95),
    _Rule("procedural.request_stop", DiscourseActFamily.PROCEDURAL,
          DiscourseActType.REQUEST_TO_STOP,
          _compile(r"\bplease stop\b"),
          DiscourseEvidenceSpanRole.PROCEDURAL_FORMULA, 0.97),
    _Rule("concession.partial", DiscourseActFamily.CONCESSION,
          DiscourseActType.PARTIAL_CONCESSION,
          _compile(r"^\s*(?:yes|true|agreed|granted)\s*,?\s+but\b"),
          DiscourseEvidenceSpanRole.CONCESSION_MARKER, 0.93),
    _Rule("concession.full", DiscourseActFamily.CONCESSION,
          DiscourseActType.FULL_CONCESSION,
          _compile(r"\bI (?:fully )?(?:agree|concede) that\b"),
          DiscourseEvidenceSpanRole.CONCESSION_MARKER, 0.91),
    _Rule("qualification.conditional", DiscourseActFamily.QUALIFICATION,
          DiscourseActType.CONDITIONAL_QUALIFICATION,
          _compile(r"\b(?:if|unless|provided that|on condition that)\b"),
          DiscourseEvidenceSpanRole.QUALIFICATION_MARKER, 0.84),
    _Rule("qualification.temporal", DiscourseActFamily.QUALIFICATION,
          DiscourseActType.TEMPORAL_QUALIFICATION,
          _compile(
              r"\b(?:before|after|since|until|during|in)\s+"
              r"(?:the \w+|today|yesterday|tomorrow|(?:19|20)\d{2})\b"
          ), DiscourseEvidenceSpanRole.QUALIFICATION_MARKER, 0.88),
    _Rule("qualification.exception", DiscourseActFamily.QUALIFICATION,
          DiscourseActType.EXCEPTION,
          _compile(r"\b(?:except for|with the exception of)\b"),
          DiscourseEvidenceSpanRole.QUALIFICATION_MARKER, 0.95),
    _Rule("qualification.probabilistic", DiscourseActFamily.QUALIFICATION,
          DiscourseActType.PROBABILISTIC_QUALIFICATION,
          _compile(r"\b(?:probably|possibly|perhaps|more likely than not)\b"),
          DiscourseEvidenceSpanRole.QUALIFICATION_MARKER, 0.86),
    _Rule("qualification.scope", DiscourseActFamily.QUALIFICATION,
          DiscourseActType.SCOPE_QUALIFICATION,
          _compile(r"\b(?:only|solely|specifically|insofar as)\b"),
          DiscourseEvidenceSpanRole.QUALIFICATION_MARKER, 0.82),
    _Rule("definition.operational", DiscourseActFamily.DEFINITION,
          DiscourseActType.OPERATIONAL_DEFINITION,
          _compile(r"\bfor (?:the )?purposes of .{0,80}?\bmeans\b.*"),
          DiscourseEvidenceSpanRole.ACT_CONTENT, 0.96),
    _Rule("definition.explicit", DiscourseActFamily.DEFINITION,
          DiscourseActType.EXPLICIT_DEFINITION,
          _compile(r"\b(?:by .{1,60}, I mean|.{1,60} is defined as)\b.*"),
          DiscourseEvidenceSpanRole.ACT_CONTENT, 0.92),
    _Rule("definition.lexical", DiscourseActFamily.DEFINITION,
          DiscourseActType.LEXICAL_DEFINITION,
          _compile(r"^\s*[A-Za-z][\w -]{0,50}\s+means\s+\S.*"),
          DiscourseEvidenceSpanRole.ACT_CONTENT, 0.88),
    _Rule("example.counterexample", DiscourseActFamily.EXAMPLE,
          DiscourseActType.COUNTEREXAMPLE,
          _compile(r"\b(?:as a counterexample|consider the counterexample)\b.*"),
          DiscourseEvidenceSpanRole.ACT_TRIGGER, 0.97),
    _Rule("example.hypothetical", DiscourseActFamily.EXAMPLE,
          DiscourseActType.HYPOTHETICAL_EXAMPLE,
          _compile(r"\b(?:suppose|imagine|assume for example)\b.*"),
          DiscourseEvidenceSpanRole.ACT_TRIGGER, 0.90),
    _Rule("example.explicit", DiscourseActFamily.EXAMPLE,
          DiscourseActType.EXAMPLE,
          _compile(r"\b(?:for example|for instance|as an example)\b.*"),
          DiscourseEvidenceSpanRole.ACT_TRIGGER, 0.97),
)


def _seal(model, payload: dict):
    provisional = model(**payload, integrity_sha256="0" * 64)
    return provisional.model_copy(
        update={
            "integrity_sha256": canonical_hash(
                provisional.model_copy(
                    update={"integrity_sha256": "0" * 64}
                )
            )
        }
    )


def _verify_seal(item, label: str) -> None:
    expected = _seal(
        type(item),
        item.model_dump(mode="python", exclude={"integrity_sha256"}),
    )
    if expected != item:
        raise DeterministicDiscourseIntegrityError(
            f"{label} integrity is invalid"
        )


def _display(utterance: Utterance):
    return next(
        item
        for item in utterance.text_views
        if item.kind == UtteranceTextKind.DISPLAY
    )


def _source_interval(utterance: Utterance) -> MediaInterval:
    return utterance.source_intervals[0]


def _measure(value: float, basis: str) -> ConfidenceMeasure:
    return ConfidenceMeasure(
        value=value,
        origin=ConfidenceOrigin.DERIVED,
        basis=basis,
        calibrated=False,
    )


def _confidence(value: float, rule_id: str) -> DiscourseConfidence:
    measure = _measure(
        value, f"uncalibrated deterministic rule strength: {rule_id}"
    )
    unavailable = ConfidenceMeasure(
        value=None,
        origin=ConfidenceOrigin.UNAVAILABLE,
        basis="No relation target is constructed by Stage 2.",
    )
    return DiscourseConfidence(
        act_type=measure,
        evidence_span=measure,
        target_relation=unavailable,
        selection=unavailable,
        derivation_method="versioned deterministic lexical/structural rule",
        source_features=(rule_id,),
        limitations=(
            "Rule strength is not calibrated probability.",
            "The observation is a proposal, not an authoritative selection.",
        ),
    )


def _span(
    utterance: Utterance,
    *,
    start: int,
    end: int,
    role: DiscourseEvidenceSpanRole,
    confidence: float,
    rule_id: str,
    word_ids: tuple[str, ...] = (),
) -> DiscourseEvidenceSpan:
    view = _display(utterance)
    text = view.text[start:end]
    return _seal(
        DiscourseEvidenceSpan,
        {
            "span_id": typed_id(
                "discoursespan",
                utterance.utterance_id,
                view.view_id,
                start,
                end,
                role.value,
                rule_id,
            ),
            "utterance_id": utterance.utterance_id,
            "utterance_text_view_id": view.view_id,
            "text_view_version": "phase4-display-1.0.0",
            "start_text_offset": start,
            "end_text_offset": end,
            "transcript_word_ids": word_ids,
            "source_interval": _source_interval(utterance),
            "exact_displayed_text": text,
            "role": role,
            "confidence": _measure(
                confidence,
                f"exact text offsets from deterministic rule: {rule_id}",
            ),
        },
    )


def _observation(
    *,
    discourse_run_id: str,
    corpus: UtteranceCorpus,
    utterance: Utterance,
    family: DiscourseActFamily,
    act_type: DiscourseActType,
    span: DiscourseEvidenceSpan,
    confidence: float,
    rule_id: str,
) -> DiscourseActObservation:
    return _seal(
        DiscourseActObservation,
        {
            "observation_id": typed_id(
                "discourseobs",
                discourse_run_id,
                utterance.utterance_id,
                family.value,
                act_type.value,
                span.span_id,
                rule_id,
            ),
            "discourse_run_id": discourse_run_id,
            "phase4_utterance_corpus_id": corpus.corpus_id,
            "utterance_id": utterance.utterance_id,
            "evidence_spans": (span,),
            "act_family": family,
            "act_type": act_type,
            "act_modifiers": (f"rule:{rule_id}",),
            "proposed_targets": (),
            "confidence": _confidence(confidence, rule_id),
            "analysis_method": DiscourseAnalysisMethod.DETERMINISTIC_RULE,
            "provider": None,
            "raw_evidence_sha256": None,
            "alternative_observation_ids": (),
            "contrary_evidence": (),
            "context_window_id": None,
            "review_status": DiscourseReviewStatus.UNREVIEWED,
            "created_at": utterance.created_at,
        },
    )


_QUOTATION_TYPES = {
    SpokenQuotationType.DIRECT: DiscourseActType.DIRECT_QUOTATION,
    SpokenQuotationType.PARTIAL: DiscourseActType.PARTIAL_QUOTATION,
    SpokenQuotationType.PARAPHRASE: DiscourseActType.PARAPHRASE,
    SpokenQuotationType.ATTRIBUTED_PROPOSITION: (
        DiscourseActType.ATTRIBUTED_POSITION
    ),
    SpokenQuotationType.REPORTED_SPEECH: DiscourseActType.REPORTED_SPEECH,
    SpokenQuotationType.SELF_QUOTATION: DiscourseActType.SELF_QUOTATION,
}


def _quotation_observation(
    discourse_run_id: str,
    corpus: UtteranceCorpus,
    utterance: Utterance,
    quotation: SpokenQuotation,
) -> DiscourseActObservation:
    quoted = quotation.quoted_span
    act_type = _QUOTATION_TYPES.get(
        quotation.quotation_type, DiscourseActType.UNCERTAIN_ATTRIBUTION
    )
    span = _span(
        utterance,
        start=quoted.character_start,
        end=quoted.character_end,
        role=DiscourseEvidenceSpanRole.QUOTATION,
        confidence=quotation.confidence.value or 0.5,
        rule_id=f"phase4.quotation.{quotation.quotation_type.value}",
        word_ids=quoted.transcript_word_ids,
    )
    return _observation(
        discourse_run_id=discourse_run_id,
        corpus=corpus,
        utterance=utterance,
        family=DiscourseActFamily.QUOTATION,
        act_type=act_type,
        span=span,
        confidence=quotation.confidence.value or 0.5,
        rule_id=f"phase4.quotation.{quotation.quotation_type.value}",
    )


def build_deterministic_discourse(
    corpus: UtteranceCorpus,
    *,
    created_at: datetime,
    quotation_evidence: QuotationEvidenceRun | None = None,
    policy: DeterministicDiscoursePolicy | None = None,
) -> tuple[DeterministicDiscourseRun, DeterministicDiscourseReport]:
    """Build conservative proposals without provider or semantic inference."""
    policy = policy or DeterministicDiscoursePolicy()
    if (
        quotation_evidence is not None
        and quotation_evidence.utterance_corpus_id != corpus.corpus_id
    ):
        raise DeterministicDiscourseIntegrityError(
            "quotation evidence belongs to another utterance corpus"
        )
    configuration_hash = canonical_hash(
        {
            "operation": "discourse.deterministic_baseline",
            "phase4_utterance_corpus_sha256": canonical_hash(corpus),
            "quotation_run_id": (
                quotation_evidence.quotation_run_id
                if quotation_evidence is not None
                else None
            ),
            "policy": policy.model_dump(mode="json"),
        }
    )
    discourse_run_id = typed_id(
        "discourserun", corpus.corpus_id, configuration_hash
    )
    observations: list[DiscourseActObservation] = []
    matched_rules: list[str] = []
    quotation_by_utterance: dict[str, list[SpokenQuotation]] = {}
    if quotation_evidence is not None:
        for quotation in quotation_evidence.quotations:
            quotation_by_utterance.setdefault(
                quotation.quoting_utterance_id, []
            ).append(quotation)

    for utterance in corpus.utterances:
        view = _display(utterance)
        seen: set[tuple[DiscourseActType, int, int]] = set()
        utterance_observation_count = 0
        for rule in RULES:
            if (
                utterance_observation_count
                >= policy.maximum_observations_per_utterance
            ):
                break
            for match in rule.pattern.finditer(view.text):
                key = (rule.act_type, match.start(), match.end())
                if key in seen:
                    continue
                seen.add(key)
                span = _span(
                    utterance,
                    start=match.start(),
                    end=match.end(),
                    role=rule.role,
                    confidence=rule.confidence,
                    rule_id=rule.rule_id,
                )
                observations.append(
                    _observation(
                        discourse_run_id=discourse_run_id,
                        corpus=corpus,
                        utterance=utterance,
                        family=rule.family,
                        act_type=rule.act_type,
                        span=span,
                        confidence=rule.confidence,
                        rule_id=rule.rule_id,
                    )
                )
                matched_rules.append(rule.rule_id)
                utterance_observation_count += 1
                if (
                    utterance_observation_count
                    >= policy.maximum_observations_per_utterance
                ):
                    break
        for quotation in quotation_by_utterance.get(
            utterance.utterance_id, ()
        ):
            if (
                utterance_observation_count
                >= policy.maximum_observations_per_utterance
            ):
                break
            observations.append(
                _quotation_observation(
                    discourse_run_id, corpus, utterance, quotation
                )
            )
            matched_rules.append(
                f"phase4.quotation.{quotation.quotation_type.value}"
            )
            utterance_observation_count += 1

    classified = {item.utterance_id for item in observations}
    unclassified = tuple(
        item.utterance_id
        for item in corpus.utterances
        if item.utterance_id not in classified
    )
    run = _seal(
        DeterministicDiscourseRun,
        {
            "baseline_run_id": typed_id(
                "discoursebaseline",
                discourse_run_id,
                tuple(item.observation_id for item in observations),
            ),
            "discourse_run_id": discourse_run_id,
            "phase4_utterance_corpus_id": corpus.corpus_id,
            "phase4_utterance_corpus_sha256": canonical_hash(corpus),
            "phase4_quotation_run_id": (
                quotation_evidence.quotation_run_id
                if quotation_evidence is not None
                else None
            ),
            "policy": policy,
            "configuration_hash": configuration_hash,
            "observations": tuple(observations),
            "unclassified_utterance_ids": unclassified,
            "matched_rule_ids": tuple(sorted(set(matched_rules))),
            "created_at": created_at,
            "complete": True,
        },
    )
    counts = Counter(item.act_family for item in observations)
    utterance_counts = Counter(item.utterance_id for item in observations)
    report = _seal(
        DeterministicDiscourseReport,
        {
            "report_id": typed_id(
                "discoursebaselinereport", run.baseline_run_id
            ),
            "baseline_run_id": run.baseline_run_id,
            "phase4_utterance_corpus_id": corpus.corpus_id,
            "generated_at": created_at,
            "utterance_count": len(corpus.utterances),
            "observation_count": len(observations),
            "multi_label_utterance_count": sum(
                value > 1 for value in utterance_counts.values()
            ),
            "unclassified_utterance_count": len(unclassified),
            "assertive_count": counts[DiscourseActFamily.ASSERTIVE],
            "question_count": counts[DiscourseActFamily.QUESTION],
            "concession_count": counts[DiscourseActFamily.CONCESSION],
            "qualification_count": counts[DiscourseActFamily.QUALIFICATION],
            "definition_count": counts[DiscourseActFamily.DEFINITION],
            "example_count": counts[DiscourseActFamily.EXAMPLE],
            "quotation_count": counts[DiscourseActFamily.QUOTATION],
            "procedural_count": counts[DiscourseActFamily.PROCEDURAL],
            "limitations": (
                "Rules qualify explicit lexical and structural mechanics, "
                "not general discourse-act accuracy.",
                "Punctuation alone never creates a question observation.",
                "Unmatched utterances remain explicitly unclassified.",
                "Partial-span media timing remains at utterance interval "
                "resolution when word-to-character alignment is unavailable.",
            ),
            "status": "complete",
        },
    )
    return run, report


def validate_deterministic_discourse(
    run: DeterministicDiscourseRun,
    corpus: UtteranceCorpus,
    *,
    quotation_evidence: QuotationEvidenceRun | None = None,
    report: DeterministicDiscourseReport | None = None,
) -> None:
    _verify_seal(run, "deterministic discourse run")
    if report is not None:
        _verify_seal(report, "deterministic discourse report")
        if (
            report.baseline_run_id != run.baseline_run_id
            or report.observation_count != len(run.observations)
            or report.unclassified_utterance_count
            != len(run.unclassified_utterance_ids)
        ):
            raise DeterministicDiscourseIntegrityError(
                "deterministic discourse report is stale"
            )
    expected = build_deterministic_discourse(
        corpus,
        created_at=run.created_at,
        quotation_evidence=quotation_evidence,
        policy=run.policy,
    )
    if expected[0] != run:
        raise DeterministicDiscourseIntegrityError(
            "deterministic discourse evidence does not replay"
        )
    if report is not None and expected[1] != report:
        raise DeterministicDiscourseIntegrityError(
            "deterministic discourse report does not replay"
        )


def persist_deterministic_discourse(
    run: DeterministicDiscourseRun,
    report: DeterministicDiscourseReport,
    corpus: UtteranceCorpus,
    destination: Path,
    *,
    quotation_evidence: QuotationEvidenceRun | None = None,
) -> tuple[Path, Path, bool]:
    validate_deterministic_discourse(
        run,
        corpus,
        quotation_evidence=quotation_evidence,
        report=report,
    )
    root = destination.expanduser().resolve()
    run_path = root / "deterministic-discourse-run.json"
    report_path = root / "deterministic-discourse-report.json"
    root.mkdir(parents=True, exist_ok=True)
    existing = (run_path.exists(), report_path.exists())
    if any(existing) and not all(existing):
        raise DeterministicDiscourseIntegrityError(
            "persisted deterministic discourse pair is incomplete"
        )
    if all(existing):
        stored = load_deterministic_discourse(root)
        if stored != (run, report):
            raise DeterministicDiscourseIntegrityError(
                "persisted deterministic discourse conflicts"
            )
        return run_path, report_path, True
    for path, item in ((run_path, run), (report_path, report)):
        temporary = path.with_name(
            f"{path.name}.partial-{uuid.uuid4().hex}"
        )
        temporary.write_bytes(canonical_bytes(item))
        os.replace(temporary, path)
    return run_path, report_path, False


def load_deterministic_discourse(
    root: Path,
) -> tuple[DeterministicDiscourseRun, DeterministicDiscourseReport]:
    resolved = root.expanduser().resolve(strict=True)
    run = load_contract(
        (resolved / "deterministic-discourse-run.json").read_bytes(),
        DeterministicDiscourseRun,
    )
    report = load_contract(
        (resolved / "deterministic-discourse-report.json").read_bytes(),
        DeterministicDiscourseReport,
    )
    _verify_seal(run, "deterministic discourse run")
    _verify_seal(report, "deterministic discourse report")
    return run, report
