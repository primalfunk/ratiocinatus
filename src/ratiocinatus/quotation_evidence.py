"""Conservative Phase 4 quotation and embedded-speech evidence."""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime
from pathlib import Path

from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase2_contracts import ConfidenceMeasure, ConfidenceOrigin
from .phase4_contracts import (
    SpeechSourceType,
    Utterance,
    UtteranceCorpus,
    UtteranceReviewStatus,
    UtteranceRun,
    UtteranceTextKind,
)
from .quotation_contracts import (
    EmbeddedSpeechKind,
    EmbeddedSpeechSource,
    QuotationDetectionPolicy,
    QuotationEvidenceReport,
    QuotationEvidenceRun,
    QuotedSpeakerAttributionSource,
    QuotedTextSpan,
    SpokenQuotation,
    SpokenQuotationType,
)
from .transcript_assembly import validate_transcript_assembly
from .transcript_contracts import TranscriptAssembly


class QuotationEvidenceIntegrityError(RuntimeError):
    """Quotation evidence is corrupt or incompatible."""


_QUOTED = re.compile(r"[\"“]([^\"”]+)[\"”]")


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
        raise QuotationEvidenceIntegrityError(
            f"{label} integrity is invalid"
        )


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


def _display(utterance: Utterance):
    return next(
        item
        for item in utterance.text_views
        if item.kind == UtteranceTextKind.DISPLAY
    )


def _word_ids(utterance: Utterance) -> tuple[str, ...]:
    return tuple(
        word_id
        for component in utterance.components
        for word_id in component.transcript_word_ids
    )


def _span(
    utterance: Utterance,
    start: int,
    end: int,
    text: str,
) -> QuotedTextSpan:
    view = _display(utterance)
    payload = {
        "span_id": typed_id(
            "quotedspan", utterance.utterance_id, view.view_id, start, end, text
        ),
        "utterance_id": utterance.utterance_id,
        "text_view_id": view.view_id,
        "character_start": start,
        "character_end": end,
        "quoted_text": text,
        "transcript_word_ids": _word_ids(utterance),
        "source_intervals": utterance.source_intervals,
        "normalized_audio_intervals": utterance.normalized_audio_intervals,
    }
    return _seal(QuotedTextSpan, payload)


def _quotation_type(prefix: str) -> SpokenQuotationType:
    normalized = prefix.casefold()
    if "[reading]" in normalized or "read aloud" in normalized:
        return SpokenQuotationType.READING_DOCUMENT
    if "[recitation]" in normalized:
        return SpokenQuotationType.RECITATION
    if "[imitating]" in normalized or "[impersonating]" in normalized:
        return SpokenQuotationType.IMITATION
    if re.search(r"\bif\b.*\b(said|says|asked)\b", normalized):
        return SpokenQuotationType.HYPOTHETICAL
    if re.search(r"\bi (said|say|wrote|asked)\b", normalized):
        return SpokenQuotationType.SELF_QUOTATION
    return SpokenQuotationType.DIRECT


def _quotation(
    corpus: UtteranceCorpus,
    utterance: Utterance,
    span: QuotedTextSpan,
    kind: SpokenQuotationType,
    attribution_text: str | None,
    confidence: ConfidenceMeasure,
    policy: QuotationDetectionPolicy,
) -> SpokenQuotation:
    quoted_target = (
        utterance.attribution.target_id
        if kind == SpokenQuotationType.SELF_QUOTATION
        else None
    )
    evidence = (
        utterance.utterance_id,
        span.span_id,
        span.text_view_id,
    )
    payload = {
        "quotation_id": typed_id(
            "quotation",
            corpus.corpus_id,
            utterance.utterance_id,
            span.span_id,
            kind.value,
        ),
        "utterance_corpus_id": corpus.corpus_id,
        "quoting_utterance_id": utterance.utterance_id,
        "quoted_span": span,
        "quotation_type": kind,
        "acoustic_attribution_id": utterance.attribution.attribution_id,
        "acoustic_speaker_target_id": utterance.attribution.target_id,
        "quoted_speaker_target_id": quoted_target,
        "attribution_text": attribution_text,
        "attribution_source": (
            QuotedSpeakerAttributionSource.EXPLICIT_UTTERANCE_WORDING
        ),
        "acoustically_present_only_through_current_speaker": True,
        "external_source_match_exists": False,
        "external_source_match_reference": None,
        "acoustic_attribution_preserved": True,
        "evidence_references": evidence,
        "confidence": confidence,
        "review_status": UtteranceReviewStatus.REVIEW_REQUIRED,
        "policy_version": policy.policy_version,
    }
    return _seal(SpokenQuotation, payload)


def _quotations(
    corpus: UtteranceCorpus,
    utterance: Utterance,
    policy: QuotationDetectionPolicy,
) -> tuple[SpokenQuotation, ...]:
    view = _display(utterance)
    text = view.text
    lowered = text.casefold()
    result: list[SpokenQuotation] = []
    for match in _QUOTED.finditer(text):
        prefix = text[max(0, match.start() - 120):match.start()]
        prefix_lower = prefix.casefold()
        cues = tuple(
            cue for cue in policy.attribution_cues if cue in prefix_lower
        )
        explicit_marker = any(
            marker in prefix_lower
            for marker in ("[reading]", "[recitation]", "[imitating]")
        )
        if not cues and not explicit_marker:
            continue
        content_start, content_end = match.span(1)
        quoted = _span(
            utterance,
            content_start,
            content_end,
            match.group(1),
        )
        kind = _quotation_type(prefix)
        result.append(
            _quotation(
                corpus,
                utterance,
                quoted,
                kind,
                prefix.strip() or None,
                _confidence(
                    0.80,
                    "bounded quotation marks plus explicit attribution cue",
                ),
                policy,
            )
        )
    if result:
        return tuple(result)
    for cue in policy.reported_speech_cues:
        start = lowered.find(cue)
        if start < 0:
            continue
        content_start = start + len(cue)
        while content_start < len(text) and text[content_start] in " ,:-":
            content_start += 1
        content_end = len(text.rstrip())
        if content_end <= content_start:
            continue
        quoted = _span(
            utterance,
            content_start,
            content_end,
            text[content_start:content_end],
        )
        result.append(
            _quotation(
                corpus,
                utterance,
                quoted,
                SpokenQuotationType.REPORTED_SPEECH,
                text[start:content_start].strip(),
                _confidence(
                    0.65,
                    "explicit reporting construction; semantics not inferred",
                ),
                policy,
            )
        )
        break
    return tuple(result)


_EMBEDDED_MARKERS = {
    "[video]": (
        SpeechSourceType.EMBEDDED_MEDIA,
        EmbeddedSpeechKind.VIDEO_CLIP,
    ),
    "[recording]": (
        SpeechSourceType.EMBEDDED_MEDIA,
        EmbeddedSpeechKind.ARCHIVAL_RECORDING,
    ),
    "[advertisement]": (
        SpeechSourceType.EMBEDDED_MEDIA,
        EmbeddedSpeechKind.ADVERTISEMENT,
    ),
    "[remote]": (
        SpeechSourceType.REMOTE_PARTICIPANT,
        EmbeddedSpeechKind.REMOTE_FEED,
    ),
    "[voicemail]": (
        SpeechSourceType.REPLAYED,
        EmbeddedSpeechKind.VOICEMAIL,
    ),
    "[translated playback]": (
        SpeechSourceType.REPLAYED,
        EmbeddedSpeechKind.TRANSLATED_PLAYBACK,
    ),
    "[public address]": (
        SpeechSourceType.REPLAYED,
        EmbeddedSpeechKind.PUBLIC_ADDRESS,
    ),
    "[synthetic voice]": (
        SpeechSourceType.SYNTHESIZED,
        EmbeddedSpeechKind.SYNTHESIZED_VOICE,
    ),
    "[replay]": (
        SpeechSourceType.REPLAYED,
        EmbeddedSpeechKind.REPLAYED_SPEECH,
    ),
}


def _embedded_sources(
    corpus: UtteranceCorpus,
    utterance: Utterance,
    policy: QuotationDetectionPolicy,
) -> tuple[EmbeddedSpeechSource, ...]:
    text = _display(utterance).text
    lowered = text.casefold()
    result: list[EmbeddedSpeechSource] = []
    for marker in policy.embedded_source_markers:
        if marker not in lowered:
            continue
        source_type, kind = _EMBEDDED_MARKERS[marker]
        evidence = (utterance.utterance_id, _display(utterance).view_id)
        payload = {
            "embedded_source_id": typed_id(
                "embeddedspeech",
                corpus.corpus_id,
                utterance.utterance_id,
                marker,
                kind.value,
            ),
            "utterance_corpus_id": corpus.corpus_id,
            "utterance_id": utterance.utterance_id,
            "acoustic_attribution_id": utterance.attribution.attribution_id,
            "acoustic_speaker_target_id": utterance.attribution.target_id,
            "source_type": source_type,
            "kind": kind,
            "marker_text": marker,
            "source_intervals": utterance.source_intervals,
            "normalized_audio_intervals": utterance.normalized_audio_intervals,
            "embedded_speaker_target_id": None,
            "external_media_reference": None,
            "acoustic_attribution_preserved": True,
            "evidence_references": evidence,
            "confidence": _confidence(
                0.85, "explicit embedded-source transcript marker"
            ),
            "review_status": UtteranceReviewStatus.REVIEW_REQUIRED,
        }
        result.append(_seal(EmbeddedSpeechSource, payload))
    return tuple(result)


def _lineage(
    utterance_run: UtteranceRun,
    corpus: UtteranceCorpus,
    assembly: TranscriptAssembly,
) -> None:
    validate_transcript_assembly(assembly)
    _verify_seal(utterance_run, "utterance run")
    _verify_seal(corpus, "utterance corpus")
    if (
        corpus.run_id != utterance_run.run_id
        or corpus.corpus_id != utterance_run.utterance_corpus_id
        or corpus.phase2_transcript_assembly_id != assembly.assembly_id
        or corpus.phase2_transcript_version_id != assembly.version.version_id
        or utterance_run.utterance_ids
        != tuple(item.utterance_id for item in corpus.utterances)
    ):
        raise QuotationEvidenceIntegrityError(
            "quotation input lineage is incompatible"
        )
    owned_words: set[str] = set()
    for utterance in corpus.utterances:
        _verify_seal(utterance, utterance.utterance_id)
        _verify_seal(
            utterance.attribution, utterance.attribution.attribution_id
        )
        for component in utterance.components:
            _verify_seal(component, component.component_id)
            owned_words.update(component.transcript_word_ids)
        for text_view in utterance.text_views:
            _verify_seal(text_view, text_view.view_id)
    if owned_words != {item.word_id for item in assembly.words}:
        raise QuotationEvidenceIntegrityError(
            "quotation input word ownership is incomplete"
        )


def build_quotation_evidence(
    utterance_run: UtteranceRun,
    corpus: UtteranceCorpus,
    assembly: TranscriptAssembly,
    *,
    policy: QuotationDetectionPolicy | None = None,
    created_at: datetime | None = None,
) -> QuotationEvidenceRun:
    """Build bounded candidates without changing acoustic attribution."""
    _lineage(utterance_run, corpus, assembly)
    policy = policy or QuotationDetectionPolicy()
    timestamp = created_at or corpus.created_at
    quotations = tuple(
        quotation
        for utterance in corpus.utterances
        for quotation in _quotations(corpus, utterance, policy)
    )
    embedded = tuple(
        source
        for utterance in corpus.utterances
        for source in _embedded_sources(corpus, utterance, policy)
    )
    configuration_hash = canonical_hash(
        {
            "utterance_run": utterance_run.integrity_sha256,
            "utterance_corpus": corpus.integrity_sha256,
            "transcript_assembly": assembly.integrity_sha256,
            "policy": policy.model_dump(mode="json"),
        }
    )
    run_id = typed_id(
        "quotationrun", corpus.corpus_id, configuration_hash
    )
    return _seal(
        QuotationEvidenceRun,
        {
            "quotation_run_id": run_id,
            "utterance_corpus_id": corpus.corpus_id,
            "utterance_run_id": utterance_run.run_id,
            "phase2_transcript_assembly_id": assembly.assembly_id,
            "policy": policy,
            "configuration_hash": configuration_hash,
            "quotations": quotations,
            "embedded_sources": embedded,
            "created_at": timestamp,
            "complete": True,
        },
    )


def _report(run: QuotationEvidenceRun) -> QuotationEvidenceReport:
    unresolved = sum(
        item.quotation_type == SpokenQuotationType.UNCERTAIN
        for item in run.quotations
    ) + sum(
        item.kind == EmbeddedSpeechKind.UNCERTAIN
        for item in run.embedded_sources
    )
    return _seal(
        QuotationEvidenceReport,
        {
            "report_id": typed_id(
                "quotationreport", run.quotation_run_id, run.integrity_sha256
            ),
            "quotation_run_id": run.quotation_run_id,
            "utterance_corpus_id": run.utterance_corpus_id,
            "generated_at": run.created_at,
            "quotation_count": len(run.quotations),
            "direct_count": sum(
                item.quotation_type == SpokenQuotationType.DIRECT
                for item in run.quotations
            ),
            "reported_speech_count": sum(
                item.quotation_type == SpokenQuotationType.REPORTED_SPEECH
                for item in run.quotations
            ),
            "self_quotation_count": sum(
                item.quotation_type == SpokenQuotationType.SELF_QUOTATION
                for item in run.quotations
            ),
            "embedded_source_count": len(run.embedded_sources),
            "remote_source_count": sum(
                item.source_type == SpeechSourceType.REMOTE_PARTICIPANT
                for item in run.embedded_sources
            ),
            "replayed_source_count": sum(
                item.source_type == SpeechSourceType.REPLAYED
                for item in run.embedded_sources
            ),
            "unresolved_count": unresolved,
            "review_required_count": (
                len(run.quotations) + len(run.embedded_sources)
            ),
            "limitations": (
                "Quotation marks alone do not create a quotation candidate.",
                "Quoted identities are not bound automatically.",
                "Embedded speech requires an explicit transcript marker.",
            ),
            "status": "warning" if unresolved else "complete",
        },
    )


def validate_quotation_evidence(
    run: QuotationEvidenceRun,
    utterance_run: UtteranceRun,
    corpus: UtteranceCorpus,
    assembly: TranscriptAssembly,
    *,
    report: QuotationEvidenceReport | None = None,
) -> None:
    _lineage(utterance_run, corpus, assembly)
    _verify_seal(run, "quotation evidence run")
    utterances = {item.utterance_id: item for item in corpus.utterances}
    for item in run.quotations:
        _verify_seal(item, item.quotation_id)
        _verify_seal(item.quoted_span, item.quoted_span.span_id)
        utterance = utterances.get(item.quoting_utterance_id)
        if utterance is None:
            raise QuotationEvidenceIntegrityError(
                "quotation references unknown utterance"
            )
        view = _display(utterance)
        span = item.quoted_span
        if (
            span.utterance_id != utterance.utterance_id
            or span.text_view_id != view.view_id
            or view.text[span.character_start:span.character_end]
            != span.quoted_text
            or item.acoustic_attribution_id
            != utterance.attribution.attribution_id
            or item.acoustic_speaker_target_id
            != utterance.attribution.target_id
        ):
            raise QuotationEvidenceIntegrityError(
                "quotation span or acoustic attribution is invalid"
            )
        if not set(span.transcript_word_ids).issubset(_word_ids(utterance)):
            raise QuotationEvidenceIntegrityError(
                "quotation word references cross utterance ownership"
            )
    for item in run.embedded_sources:
        _verify_seal(item, item.embedded_source_id)
        utterance = utterances.get(item.utterance_id)
        if utterance is None or (
            item.acoustic_attribution_id
            != utterance.attribution.attribution_id
            or item.acoustic_speaker_target_id
            != utterance.attribution.target_id
        ):
            raise QuotationEvidenceIntegrityError(
                "embedded source acoustic attribution is invalid"
            )
    if (
        run.utterance_corpus_id != corpus.corpus_id
        or run.utterance_run_id != utterance_run.run_id
        or run.phase2_transcript_assembly_id != assembly.assembly_id
    ):
        raise QuotationEvidenceIntegrityError(
            "quotation run and source lineage disagree"
        )
    expected = build_quotation_evidence(
        utterance_run,
        corpus,
        assembly,
        policy=run.policy,
        created_at=run.created_at,
    )
    if expected != run:
        raise QuotationEvidenceIntegrityError(
            "quotation evidence is not the deterministic source projection"
        )
    if report is not None:
        _verify_seal(report, "quotation evidence report")
        if report != _report(run):
            raise QuotationEvidenceIntegrityError(
                "quotation report projection is invalid"
            )


def quotation_evidence_report_markdown(
    report: QuotationEvidenceReport,
) -> str:
    return "\n".join(
        (
            "# Phase 4 quotation and embedded-speech report",
            "",
            f"- Quotation run: `{report.quotation_run_id}`",
            f"- Quotation candidates: {report.quotation_count}",
            f"- Direct: {report.direct_count}",
            f"- Reported speech: {report.reported_speech_count}",
            f"- Self-quotation: {report.self_quotation_count}",
            f"- Embedded sources: {report.embedded_source_count}",
            f"- Remote sources: {report.remote_source_count}",
            f"- Replayed sources: {report.replayed_source_count}",
            f"- Review required: {report.review_required_count}",
            f"- Status: {report.status}",
            "",
        )
    )


def persist_quotation_evidence(
    run: QuotationEvidenceRun,
    utterance_run: UtteranceRun,
    corpus: UtteranceCorpus,
    assembly: TranscriptAssembly,
    destination: Path,
) -> tuple[QuotationEvidenceRun, QuotationEvidenceReport, Path, bool]:
    destination = destination.expanduser().resolve()
    validate_quotation_evidence(run, utterance_run, corpus, assembly)
    report = _report(run)
    root = destination / "quotation-evidence" / run.quotation_run_id
    paths = (
        root / "run.json",
        root / "report.json",
        root / "report.md",
    )
    existing = tuple(path.exists() for path in paths)
    if any(existing) and not all(existing):
        raise QuotationEvidenceIntegrityError(
            "cached quotation evidence is incomplete"
        )
    if all(existing):
        stored = load_contract(paths[0].read_bytes(), QuotationEvidenceRun)
        stored_report = load_contract(
            paths[1].read_bytes(), QuotationEvidenceReport
        )
        validate_quotation_evidence(
            stored,
            utterance_run,
            corpus,
            assembly,
            report=stored_report,
        )
        if (
            stored != run
            or stored_report != report
            or paths[2].read_text(encoding="utf-8")
            != quotation_evidence_report_markdown(report)
        ):
            raise QuotationEvidenceIntegrityError(
                "cached quotation evidence is incompatible"
            )
        return stored, stored_report, root, True
    _atomic(paths[0], canonical_bytes(run))
    _atomic(paths[1], canonical_bytes(report))
    _atomic(
        paths[2],
        quotation_evidence_report_markdown(report).encode("utf-8"),
    )
    return run, report, root, False


def load_quotation_evidence(
    root: Path,
) -> tuple[QuotationEvidenceRun, QuotationEvidenceReport]:
    root = root.expanduser().resolve(strict=True)
    return (
        load_contract((root / "run.json").read_bytes(), QuotationEvidenceRun),
        load_contract(
            (root / "report.json").read_bytes(), QuotationEvidenceReport
        ),
    )
