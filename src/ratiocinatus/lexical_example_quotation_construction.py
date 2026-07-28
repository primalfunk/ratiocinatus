"""Construct local definitions, bounded examples, and Phase 4 quotation uses."""

from __future__ import annotations

import os
import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from .context_window_contracts import ContextWindowBundle, ContextWindowKind
from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase2_contracts import ConfidenceMeasure, ConfidenceOrigin
from .phase5_contracts import (
    DiscourseActFamily,
    DiscourseActType,
    DiscourseCorpus,
    DiscourseReviewStatus,
    DiscourseTargetStatus,
)
from .phase5_foundation import validate_discourse_corpus_seal
from .phase5_lexical_example_quotation_contracts import (
    DefinitionRecord,
    DefinitionScope,
    ExampleRealityStatus,
    ExampleRecord,
    LexicalExampleQuotationPolicy,
    LexicalExampleQuotationReport,
    LexicalExampleQuotationRun,
    QuotationUseRecord,
)
from .quotation_contracts import QuotationEvidenceRun


class LexicalConstructionIntegrityError(RuntimeError):
    """Definition, example, or quotation-use artifacts are incompatible."""


_TEMPORAL_REFERENCE = re.compile(
    r"\b(?:(?:19|20)\d{2}|today|yesterday|tomorrow|"
    r"before|after|since|until|during)\b",
    re.IGNORECASE,
)


def _seal(model, payload):
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


def _verify_seal(item, label):
    expected = _seal(
        type(item),
        item.model_dump(mode="python", exclude={"integrity_sha256"}),
    )
    if expected != item:
        raise LexicalConstructionIntegrityError(
            f"{label} integrity is invalid"
        )


def _text(act):
    return tuple(
        dict.fromkeys(span.exact_displayed_text for span in act.evidence_spans)
    )


def _joined(act):
    return " ".join(_text(act)).strip()


def _window(bundle, utterance_id):
    return next(
        (
            item
            for item in bundle.windows
            if item.target_utterance_id == utterance_id
            and item.kind == ContextWindowKind.BOUNDED_TEMPORAL
        ),
        None,
    )


def _definition_parts(act):
    text = _joined(act)
    patterns = (
        re.compile(
            r"for (?:the )?purposes of (?P<context>.+?),\s*"
            r"(?P<term>.+?)\s+means\s+(?P<body>.+)",
            re.IGNORECASE,
        ),
        re.compile(
            r"by\s+(?P<term>.+?),\s*I mean\s+(?P<body>.+)",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?P<term>.+?)\s+is defined as\s+(?P<body>.+)",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?P<term>.+?)\s+means\s+(?P<body>.+)",
            re.IGNORECASE,
        ),
    )
    match = next((pattern.search(text) for pattern in patterns if pattern.search(text)), None)
    if match is None:
        return None, _text(act), (), DefinitionScope.SOURCE_UTTERANCE
    term = match.group("term").strip(" ,.;:")
    body = match.group("body").strip()
    context = (
        (match.groupdict().get("context") or "").strip()
        if "context" in match.groupdict()
        else ""
    )
    exclusions = tuple(
        item.strip(" ,.;:")
        for item in re.findall(
            r"(?:does not include|excluding|except for)\s+([^.;]+)",
            body,
            flags=re.IGNORECASE,
        )
        if item.strip(" ,.;:")
    )
    return (
        term or None,
        (body,) if body else _text(act),
        (context,) if context else (),
        (
            DefinitionScope.DECLARED_CONTEXT
            if context
            else DefinitionScope.SOURCE_UTTERANCE
        ),
        exclusions,
    )


def _nearest_prior(
    act,
    candidates,
    context,
):
    window = _window(context, act.utterance_id)
    if window is None:
        return (), None
    positions = {
        item.utterance_id: item.order_position for item in window.members
    }
    source_position = positions.get(act.utterance_id)
    available = [
        item
        for item in candidates
        if item.utterance_id in positions
        and source_position is not None
        and positions[item.utterance_id] < source_position
    ]
    if not available:
        return (), window.context_window_id
    nearest = max(positions[item.utterance_id] for item in available)
    return (
        tuple(
            item
            for item in available
            if positions[item.utterance_id] == nearest
        ),
        window.context_window_id,
    )


def _target_state(candidates):
    if len(candidates) == 1:
        return (
            DiscourseTargetStatus.PROBABLE,
            (candidates[0].act_id,),
            (),
        )
    if len(candidates) > 1:
        return (
            DiscourseTargetStatus.MULTIPLE_CANDIDATES,
            (),
            tuple(item.act_id for item in candidates),
        )
    return DiscourseTargetStatus.UNRESOLVED, (), ()


def _confidence(status):
    if status == DiscourseTargetStatus.PROBABLE:
        return ConfidenceMeasure(
            value=0.7,
            origin=ConfidenceOrigin.DERIVED,
            basis="uncalibrated nearest bounded generalization candidate",
            calibrated=False,
        )
    if status == DiscourseTargetStatus.MULTIPLE_CANDIDATES:
        return ConfidenceMeasure(
            value=0.5,
            origin=ConfidenceOrigin.DERIVED,
            basis="uncalibrated ambiguous bounded generalization set",
            calibrated=False,
        )
    return ConfidenceMeasure(
        value=None,
        origin=ConfidenceOrigin.UNAVAILABLE,
        basis="no generalization target is selected",
        calibrated=False,
    )


def _reality(act, quotation_utterances):
    if act.act_type == DiscourseActType.HYPOTHETICAL_EXAMPLE:
        return ExampleRealityStatus.HYPOTHETICAL
    if act.utterance_id in quotation_utterances:
        return ExampleRealityStatus.QUOTED
    if act.act_type in {
        DiscourseActType.CASE_CITATION,
        DiscourseActType.ANECDOTAL_EXAMPLE,
    }:
        return ExampleRealityStatus.REAL
    return ExampleRealityStatus.UNCERTAIN


def build_lexical_example_quotation(
    corpus: DiscourseCorpus,
    context: ContextWindowBundle,
    *,
    created_at: datetime,
    quotation_evidence: QuotationEvidenceRun | None = None,
    policy: LexicalExampleQuotationPolicy | None = None,
):
    validate_discourse_corpus_seal(corpus)
    if context.utterance_corpus_id != corpus.phase4_utterance_corpus_id:
        raise LexicalConstructionIntegrityError(
            "context bundle uses incompatible Phase 4 lineage"
        )
    if (
        quotation_evidence is not None
        and quotation_evidence.utterance_corpus_id
        != corpus.phase4_utterance_corpus_id
    ):
        raise LexicalConstructionIntegrityError(
            "quotation evidence uses incompatible Phase 4 lineage"
        )
    policy = policy or LexicalExampleQuotationPolicy()
    acts = corpus.selected_acts
    definition_acts = tuple(
        item
        for item in acts
        if item.act_family == DiscourseActFamily.DEFINITION
    )
    challenge_acts = tuple(
        item
        for item in acts
        if item.act_type
        in {
            DiscourseActType.DEFINITION_CHALLENGE,
            DiscourseActType.DEFINITION_CHALLENGE_ACT,
        }
    )
    definition_payloads = []
    definition_ids = {
        item.act_id: typed_id(
            "definition", corpus.corpus_id, item.act_id
        )
        for item in definition_acts
    }
    parsed = {item.act_id: _definition_parts(item) for item in definition_acts}
    for act in definition_acts:
        parts = parsed[act.act_id]
        term, body, applicable, scope = parts[:4]
        exclusions = parts[4] if len(parts) > 4 else ()
        peers = tuple(
            definition_ids[item.act_id]
            for item in definition_acts
            if item.act_id != act.act_id
            and term is not None
            and parsed[item.act_id][0] is not None
            and parsed[item.act_id][0].casefold() == term.casefold()
        )
        linked_challenges = []
        for challenge in challenge_acts:
            nearest, _ = _nearest_prior(
                challenge, definition_acts, context
            )
            if any(item.act_id == act.act_id for item in nearest):
                linked_challenges.append(challenge.act_id)
        window = _window(context, act.utterance_id)
        definition_payloads.append(
            {
                "definition_id": definition_ids[act.act_id],
                "discourse_corpus_id": corpus.corpus_id,
                "source_act_id": act.act_id,
                "utterance_id": act.utterance_id,
                "definition_type": act.act_type,
                "defined_expression": term,
                "defining_text": body,
                "scope": scope,
                "applicable_context_text": applicable,
                "context_window_id": (
                    window.context_window_id if window else None
                ),
                "explicit_exclusions": exclusions,
                "competing_definition_ids": peers,
                "definition_challenge_act_ids": tuple(linked_challenges),
                "evidence_span_ids": tuple(
                    item.span_id for item in act.evidence_spans
                ),
                "confidence": act.confidence.act_type,
                "review_status": (
                    DiscourseReviewStatus.REVIEW_REQUIRED
                    if term is None or peers
                    else act.review_status
                ),
                "created_at": created_at,
            }
        )
    definitions = tuple(
        _seal(DefinitionRecord, item) for item in definition_payloads
    )

    quotation_utterances = (
        {
            item.quoting_utterance_id
            for item in quotation_evidence.quotations
        }
        if quotation_evidence is not None
        else set()
    )
    generalizations = tuple(
        item
        for item in acts
        if item.act_family
        in {
            DiscourseActFamily.ASSERTIVE,
            DiscourseActFamily.DEFINITION,
        }
    )
    examples = []
    for act in acts:
        if act.act_family != DiscourseActFamily.EXAMPLE:
            continue
        targets, window_id = _nearest_prior(
            act, generalizations, context
        )
        status, target_ids, alternatives = _target_state(targets)
        text = _joined(act)
        examples.append(
            _seal(
                ExampleRecord,
                {
                    "example_id": typed_id(
                        "example", corpus.corpus_id, act.act_id
                    ),
                    "discourse_corpus_id": corpus.corpus_id,
                    "source_act_id": act.act_id,
                    "utterance_id": act.utterance_id,
                    "example_type": act.act_type,
                    "example_span_ids": tuple(
                        item.span_id for item in act.evidence_spans
                    ),
                    "example_text": _text(act),
                    "reality_status": _reality(
                        act, quotation_utterances
                    ),
                    "target_status": status,
                    "generalization_act_ids": target_ids,
                    "alternative_generalization_act_ids": alternatives,
                    "temporal_references": tuple(
                        dict.fromkeys(
                            match.group(0)
                            for match in _TEMPORAL_REFERENCE.finditer(text)
                        )
                    ),
                    "participant_references": (),
                    "context_window_id": window_id,
                    "confidence": _confidence(status),
                    "review_status": (
                        act.review_status
                        if status == DiscourseTargetStatus.IDENTIFIED
                        else DiscourseReviewStatus.REVIEW_REQUIRED
                    ),
                    "created_at": created_at,
                },
            )
        )

    phase4_by_utterance = defaultdict(list)
    embedded_by_utterance = defaultdict(list)
    if quotation_evidence is not None:
        for item in quotation_evidence.quotations:
            phase4_by_utterance[item.quoting_utterance_id].append(item)
        for item in quotation_evidence.embedded_sources:
            embedded_by_utterance[item.utterance_id].append(item)
    quotation_uses = []
    for act in acts:
        if act.act_family != DiscourseActFamily.QUOTATION:
            continue
        span_text = {
            item.exact_displayed_text for item in act.evidence_spans
        }
        matches = [
            item
            for item in phase4_by_utterance.get(act.utterance_id, ())
            if item.quoted_span.quoted_text in span_text
        ]
        phase4 = sorted(matches, key=lambda item: item.quotation_id)[0] if matches else None
        quotation_uses.append(
            _seal(
                QuotationUseRecord,
                {
                    "quotation_use_id": typed_id(
                        "quotationuse", corpus.corpus_id, act.act_id
                    ),
                    "discourse_corpus_id": corpus.corpus_id,
                    "source_act_id": act.act_id,
                    "utterance_id": act.utterance_id,
                    "quotation_use_type": act.act_type,
                    "phase4_quotation_id": (
                        phase4.quotation_id if phase4 else None
                    ),
                    "phase4_quotation_type": (
                        phase4.quotation_type if phase4 else None
                    ),
                    "quoted_span": (
                        phase4.quoted_span if phase4 else None
                    ),
                    "acoustic_attribution_id": (
                        phase4.acoustic_attribution_id if phase4 else None
                    ),
                    "acoustic_speaker_target_id": (
                        phase4.acoustic_speaker_target_id
                        if phase4
                        else None
                    ),
                    "quoting_speaker_target_id": (
                        phase4.acoustic_speaker_target_id
                        if phase4
                        else None
                    ),
                    "attributed_speaker_target_id": (
                        phase4.quoted_speaker_target_id
                        if phase4
                        else None
                    ),
                    "original_source_reference": (
                        phase4.external_source_match_reference
                        if phase4
                        else None
                    ),
                    "attribution_text": (
                        phase4.attribution_text if phase4 else None
                    ),
                    "embedded_source_ids": tuple(
                        item.embedded_source_id
                        for item in embedded_by_utterance.get(
                            act.utterance_id, ()
                        )
                    ),
                    "evidence_span_ids": tuple(
                        item.span_id for item in act.evidence_spans
                    ),
                    "confidence": (
                        act.confidence.quotation_use
                        or act.confidence.act_type
                    ),
                    "review_status": (
                        act.review_status
                        if phase4
                        else DiscourseReviewStatus.REVIEW_REQUIRED
                    ),
                    "created_at": created_at,
                },
            )
        )
    unresolved = tuple(
        (
            item.source_act_id
            for item in definitions
            if item.defined_expression is None
        )
    ) + tuple(
        item.source_act_id
        for item in examples
        if item.target_status
        in {
            DiscourseTargetStatus.MULTIPLE_CANDIDATES,
            DiscourseTargetStatus.UNRESOLVED,
        }
    ) + tuple(
        item.source_act_id
        for item in quotation_uses
        if item.phase4_quotation_id is None
    )
    configuration_hash = canonical_hash(
        {
            "operation": "discourse.lexical_example_quotation",
            "discourse_corpus_sha256": canonical_hash(corpus),
            "context_bundle_sha256": canonical_hash(context),
            "quotation_run_sha256": (
                canonical_hash(quotation_evidence)
                if quotation_evidence is not None
                else None
            ),
            "policy": policy.model_dump(mode="json"),
        }
    )
    run_id = typed_id(
        "lexicalconstruction", corpus.corpus_id, configuration_hash
    )
    run = _seal(
        LexicalExampleQuotationRun,
        {
            "construction_run_id": run_id,
            "discourse_corpus_id": corpus.corpus_id,
            "discourse_corpus_sha256": canonical_hash(corpus),
            "context_bundle_id": context.context_bundle_id,
            "context_bundle_sha256": canonical_hash(context),
            "phase4_quotation_run_id": (
                quotation_evidence.quotation_run_id
                if quotation_evidence is not None
                else None
            ),
            "phase4_quotation_run_sha256": (
                canonical_hash(quotation_evidence)
                if quotation_evidence is not None
                else None
            ),
            "policy": policy,
            "configuration_hash": configuration_hash,
            "definitions": definitions,
            "examples": tuple(examples),
            "quotation_uses": tuple(quotation_uses),
            "unresolved_source_act_ids": unresolved,
            "created_at": created_at,
            "complete": True,
        },
    )
    example_statuses = Counter(item.target_status for item in examples)
    report = _seal(
        LexicalExampleQuotationReport,
        {
            "report_id": typed_id(
                "lexicalconstructionreport", run_id
            ),
            "construction_run_id": run_id,
            "generated_at": created_at,
            "definition_count": len(definitions),
            "unresolved_definition_expression_count": sum(
                item.defined_expression is None for item in definitions
            ),
            "competing_definition_count": sum(
                bool(item.competing_definition_ids)
                for item in definitions
            ),
            "definition_challenge_link_count": sum(
                len(item.definition_challenge_act_ids)
                for item in definitions
            ),
            "example_count": len(examples),
            "probable_example_target_count": example_statuses[
                DiscourseTargetStatus.PROBABLE
            ],
            "ambiguous_example_target_count": example_statuses[
                DiscourseTargetStatus.MULTIPLE_CANDIDATES
            ],
            "unresolved_example_target_count": example_statuses[
                DiscourseTargetStatus.UNRESOLVED
            ],
            "quotation_use_count": len(quotation_uses),
            "phase4_matched_quotation_use_count": sum(
                item.phase4_quotation_id is not None
                for item in quotation_uses
            ),
            "unresolved_quotation_use_count": sum(
                item.phase4_quotation_id is None
                for item in quotation_uses
            ),
            "limitations": (
                "Definitions remain local to declared or source-utterance "
                "scope.",
                "Example targets are bounded candidates and do not establish "
                "representativeness or proof.",
                "Quotation use preserves Phase 4 acoustic attribution "
                "without mutation.",
                "No factual adjudication is performed.",
            ),
            "status": "warning" if unresolved else "complete",
        },
    )
    return run, report


def validate_lexical_example_quotation(
    run, report, corpus, context, *, quotation_evidence=None
):
    _verify_seal(run, "lexical construction run")
    _verify_seal(report, "lexical construction report")
    if (
        run.discourse_corpus_id != corpus.corpus_id
        or run.discourse_corpus_sha256 != canonical_hash(corpus)
        or run.context_bundle_id != context.context_bundle_id
        or run.context_bundle_sha256 != canonical_hash(context)
        or report.construction_run_id != run.construction_run_id
    ):
        raise LexicalConstructionIntegrityError(
            "lexical construction source lineage or report is stale"
        )
    expected = build_lexical_example_quotation(
        corpus,
        context,
        created_at=run.created_at,
        quotation_evidence=quotation_evidence,
        policy=run.policy,
    )
    if expected != (run, report):
        raise LexicalConstructionIntegrityError(
            "lexical construction does not replay"
        )


def persist_lexical_example_quotation(
    run,
    report,
    corpus,
    context,
    destination: Path,
    *,
    quotation_evidence=None,
):
    validate_lexical_example_quotation(
        run,
        report,
        corpus,
        context,
        quotation_evidence=quotation_evidence,
    )
    root = destination.expanduser().resolve()
    paths = (
        root / "lexical-construction-run.json",
        root / "lexical-construction-report.json",
    )
    root.mkdir(parents=True, exist_ok=True)
    existing = tuple(path.exists() for path in paths)
    if any(existing) and not all(existing):
        raise LexicalConstructionIntegrityError(
            "persisted lexical construction pair is incomplete"
        )
    if all(existing):
        stored = load_lexical_example_quotation(root)
        if stored != (run, report):
            raise LexicalConstructionIntegrityError(
                "persisted lexical construction artifacts conflict"
            )
        return (*paths, True)
    for path, item in zip(paths, (run, report)):
        temporary = path.with_name(
            f"{path.name}.partial-{uuid.uuid4().hex}"
        )
        temporary.write_bytes(canonical_bytes(item))
        os.replace(temporary, path)
    return (*paths, False)


def load_lexical_example_quotation(root: Path):
    resolved = root.expanduser().resolve(strict=True)
    run = load_contract(
        (resolved / "lexical-construction-run.json").read_bytes(),
        LexicalExampleQuotationRun,
    )
    report = load_contract(
        (resolved / "lexical-construction-report.json").read_bytes(),
        LexicalExampleQuotationReport,
    )
    _verify_seal(run, "lexical construction run")
    _verify_seal(report, "lexical construction report")
    return run, report
