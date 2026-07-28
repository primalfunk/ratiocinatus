from pathlib import Path

import pytest

from ratiocinatus.addressing_contracts import MediaInterval, TimeDomain
from ratiocinatus.cli import main
from ratiocinatus.discourse_baseline import (
    DeterministicDiscourseIntegrityError,
    build_deterministic_discourse,
    load_deterministic_discourse,
    persist_deterministic_discourse,
    validate_deterministic_discourse,
)
from ratiocinatus.kernel import canonical_hash
from ratiocinatus.phase2_contracts import ConfidenceMeasure, ConfidenceOrigin
from ratiocinatus.phase4_contracts import UtteranceTextKind
from ratiocinatus.phase5_baseline_contracts import (
    DeterministicDiscoursePolicy,
)
from ratiocinatus.phase5_contracts import (
    DiscourseActFamily,
    DiscourseActType,
)
from ratiocinatus.quotation_contracts import (
    QuotationDetectionPolicy,
    QuotationEvidenceRun,
    QuotedSpeakerAttributionSource,
    QuotedTextSpan,
    SpokenQuotation,
    SpokenQuotationType,
)

from test_phase5_foundation import HASH, NOW, _phase4


def _with_texts(*texts: str):
    base = _phase4()
    utterances = []
    for index, text in enumerate(texts, start=1):
        source = base.utterances[0]
        suffix = f"{index:032x}"
        interval = MediaInterval(
            domain=TimeDomain.SOURCE_MEDIA,
            start_microseconds=index * 2_000_000,
            duration_microseconds=1_000_000,
        )
        normalized = MediaInterval(
            domain=TimeDomain.NORMALIZED_CORPUS,
            start_microseconds=index * 2_000_000,
            duration_microseconds=1_000_000,
        )
        word_id = "txword_" + suffix
        component = source.components[0].model_copy(
            update={
                "component_id": "utterancecomponent_" + suffix,
                "source_interval": interval,
                "normalized_audio_interval": normalized,
                "transcript_word_ids": (word_id,),
                "verbatim_text": text,
            }
        )
        views = []
        for position, view in enumerate(source.text_views, start=1):
            view_suffix = f"{index * 10 + position:032x}"
            views.append(
                view.model_copy(
                    update={
                        "view_id": "utterancetext_" + view_suffix,
                        "text": text,
                        "source_transcript_word_ids": (word_id,),
                    }
                )
            )
        display = next(
            item for item in views if item.kind == UtteranceTextKind.DISPLAY
        )
        utterances.append(
            source.model_copy(
                update={
                    "utterance_id": "utterance_" + suffix,
                    "components": (component,),
                    "source_intervals": (interval,),
                    "normalized_audio_intervals": (normalized,),
                    "text_views": tuple(views),
                    "displayed_text_view_id": display.view_id,
                }
            )
        )
    return base.model_copy(
        update={
            "utterances": tuple(utterances),
            "integrity_sha256": canonical_hash(tuple(texts)),
        }
    )


def _quotation(corpus) -> QuotationEvidenceRun:
    utterance = corpus.utterances[0]
    view = next(
        item
        for item in utterance.text_views
        if item.kind == UtteranceTextKind.DISPLAY
    )
    start = view.text.index('"') + 1
    end = view.text.rindex('"')
    quoted_span = QuotedTextSpan(
        span_id="quotedspan_" + "1" * 32,
        utterance_id=utterance.utterance_id,
        text_view_id=view.view_id,
        character_start=start,
        character_end=end,
        quoted_text=view.text[start:end],
        source_intervals=utterance.source_intervals,
        normalized_audio_intervals=utterance.normalized_audio_intervals,
        integrity_sha256=HASH,
    )
    confidence = ConfidenceMeasure(
        value=0.9,
        origin=ConfidenceOrigin.DERIVED,
        basis="controlled explicit quotation fixture",
    )
    quotation = SpokenQuotation(
        quotation_id="quotation_" + "2" * 32,
        utterance_corpus_id=corpus.corpus_id,
        quoting_utterance_id=utterance.utterance_id,
        quoted_span=quoted_span,
        quotation_type=SpokenQuotationType.DIRECT,
        acoustic_attribution_id=utterance.attribution.attribution_id,
        acoustic_speaker_target_id=None,
        quoted_speaker_target_id=None,
        attribution_text="Alice said",
        attribution_source=(
            QuotedSpeakerAttributionSource.EXPLICIT_UTTERANCE_WORDING
        ),
        acoustically_present_only_through_current_speaker=True,
        external_source_match_exists=False,
        evidence_references=(quoted_span.span_id,),
        confidence=confidence,
        review_status=utterance.review_status,
        integrity_sha256=HASH,
    )
    return QuotationEvidenceRun(
        quotation_run_id="quotationrun_" + "3" * 32,
        utterance_corpus_id=corpus.corpus_id,
        utterance_run_id=corpus.run_id,
        phase2_transcript_assembly_id=corpus.phase2_transcript_assembly_id,
        policy=QuotationDetectionPolicy(),
        configuration_hash=HASH,
        quotations=(quotation,),
        embedded_sources=(),
        created_at=NOW,
        complete=True,
        integrity_sha256=HASH,
    )


def test_baseline_detects_clear_multi_label_rules_and_preserves_unknown():
    corpus = _with_texts(
        "What time is the hearing?",
        "Can we move on?",
        "You have two minutes remaining.",
        "Yes, but only after 2022.",
        "For purposes of this rule, resident means a person living here.",
        "For example, consider the north district.",
        "Really?",
        "I am not sure.",
    )
    before = corpus.model_dump_json()
    run, report = build_deterministic_discourse(corpus, created_at=NOW)
    repeated = build_deterministic_discourse(corpus, created_at=NOW)
    assert repeated == (run, report)
    assert corpus.model_dump_json() == before
    assert report.question_count >= 2
    assert report.procedural_count >= 1
    assert report.concession_count == 1
    assert report.qualification_count >= 2
    assert report.definition_count >= 1
    assert report.example_count == 1
    assert report.assertive_count == 1
    assert report.multi_label_utterance_count >= 2
    assert "utterance_" + f"{7:032x}" in run.unclassified_utterance_ids
    types = {item.act_type for item in run.observations}
    assert DiscourseActType.INFORMATION_QUESTION in types
    assert DiscourseActType.PROCEDURAL_QUESTION in types
    assert DiscourseActType.PARTIAL_CONCESSION in types
    assert DiscourseActType.TEMPORAL_QUALIFICATION in types
    assert all(
        item.analysis_method.value == "deterministic_rule"
        and item.provider is None
        for item in run.observations
    )
    validate_deterministic_discourse(run, corpus, report=report)
    limited, _ = build_deterministic_discourse(
        corpus,
        created_at=NOW,
        policy=DeterministicDiscoursePolicy(
            maximum_observations_per_utterance=1
        ),
    )
    assert all(
        sum(
            item.utterance_id == utterance.utterance_id
            for item in limited.observations
        ) <= 1
        for utterance in corpus.utterances
    )


def test_punctuation_alone_never_forces_question_classification():
    corpus = _with_texts("Really?", "This happened.")
    run, report = build_deterministic_discourse(corpus, created_at=NOW)
    assert run.observations == ()
    assert len(run.unclassified_utterance_ids) == 2
    assert report.question_count == 0


def test_baseline_consumes_phase4_quotation_without_changing_attribution():
    corpus = _with_texts('Alice said "hello there".')
    evidence = _quotation(corpus)
    before = corpus.utterances[0].attribution.model_dump_json()
    run, report = build_deterministic_discourse(
        corpus, created_at=NOW, quotation_evidence=evidence
    )
    assert report.quotation_count == 1
    observation = next(
        item
        for item in run.observations
        if item.act_family == DiscourseActFamily.QUOTATION
    )
    assert observation.act_type == DiscourseActType.DIRECT_QUOTATION
    assert observation.evidence_spans[0].exact_displayed_text == "hello there"
    assert corpus.utterances[0].attribution.model_dump_json() == before


def test_baseline_persistence_replays_and_rejects_tampering(tmp_path: Path):
    corpus = _with_texts("Please answer the question.")
    run, report = build_deterministic_discourse(corpus, created_at=NOW)
    paths = persist_deterministic_discourse(
        run, report, corpus, tmp_path / "baseline"
    )
    assert not paths[2]
    assert load_deterministic_discourse(tmp_path / "baseline") == (run, report)
    assert persist_deterministic_discourse(
        run, report, corpus, tmp_path / "baseline"
    )[2]

    tampered = run.model_copy(update={"configuration_hash": "f" * 64})
    with pytest.raises(
        DeterministicDiscourseIntegrityError, match="integrity"
    ):
        validate_deterministic_discourse(
            tampered, corpus, report=report
        )


def test_quotation_lineage_mismatch_is_refused():
    corpus = _with_texts('Alice said "hello".')
    evidence = _quotation(corpus).model_copy(
        update={"utterance_corpus_id": "utterancecorpus_" + "0" * 32}
    )
    with pytest.raises(
        DeterministicDiscourseIntegrityError, match="another"
    ):
        build_deterministic_discourse(
            corpus, created_at=NOW, quotation_evidence=evidence
        )


def test_baseline_cli_inspects_and_lists(tmp_path: Path, capsys):
    import json

    corpus = _with_texts("Please answer the question.", "Really?")
    run, report = build_deterministic_discourse(corpus, created_at=NOW)
    root = tmp_path / "baseline"
    persist_deterministic_discourse(run, report, corpus, root)
    assert main(["--json", "discourse", "baseline-inspect", str(root)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["report"]["observation_count"] == 1
    assert main(["--json", "discourse", "list-unclassified", str(root)]) == 0
    unclassified = json.loads(capsys.readouterr().out)
    assert unclassified == ["utterance_" + f"{2:032x}"]