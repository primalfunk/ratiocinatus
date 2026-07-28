from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from ratiocinatus.addressing_contracts import MediaInterval, TimeDomain
from ratiocinatus.cli import main
from ratiocinatus.discourse_providers import (
    DiscourseProviderRegistry,
    DiscourseProviderUnavailable,
)
from ratiocinatus.kernel import canonical_hash
from ratiocinatus.phase2_contracts import ConfidenceMeasure, ConfidenceOrigin
from ratiocinatus.phase4_contracts import (
    SpeechSourceType,
    Utterance,
    UtteranceAttribution,
    UtteranceAttributionStatus,
    UtteranceAttributionTargetKind,
    UtteranceCompletenessClassification,
    UtteranceComponent,
    UtteranceCorpus,
    UtteranceCreationProcess,
    UtteranceInterruptionStatus,
    UtteranceOverlapStatus,
    UtteranceQuotationStatus,
    UtteranceRepairStatus,
    UtteranceReviewStatus,
    UtteranceTextKind,
    UtteranceTextView,
)
from ratiocinatus.phase5_contracts import (
    FAMILY_TYPES,
    PHASE5_CONTRACT_MODELS,
    CandidateDisposition,
    DiscourseAct,
    DiscourseActCandidate,
    DiscourseActCandidateSet,
    DiscourseActFamily,
    DiscourseActObservation,
    DiscourseActType,
    DiscourseAnalysisMethod,
    DiscourseAnalysisPolicy,
    DiscourseConfidence,
    DiscourseCorpus,
    DiscourseEvidenceSpan,
    DiscourseEvidenceSpanRole,
    DiscourseReviewStatus,
    DiscourseVocabularyPolicy,
)
from ratiocinatus.phase5_foundation import (
    Phase5IntegrityError,
    load_discourse_corpus,
    persist_discourse_corpus,
    seal_discourse_corpus,
    validate_discourse_corpus,
)
from ratiocinatus.phase5_provider_contracts import (
    PHASE5_PROVIDER_CONTRACT_MODELS,
)


NOW = datetime(2026, 7, 27, tzinfo=timezone.utc)
HASH = "1" * 64
TEXT = "Yes, but only after 2022."


def _confidence(value: float = 0.8) -> ConfidenceMeasure:
    return ConfidenceMeasure(
        value=value,
        origin=ConfidenceOrigin.DERIVED,
        basis="controlled Phase 5 foundation fixture",
    )


def _multi_confidence() -> DiscourseConfidence:
    value = _confidence()
    return DiscourseConfidence(
        act_type=value,
        evidence_span=value,
        target_relation=value,
        selection=value,
        derivation_method="controlled deterministic fixture",
        source_features=("explicit lexical marker",),
        limitations=("Mechanics evidence is not an accuracy claim.",),
    )


def _view(kind: UtteranceTextKind, suffix: str) -> UtteranceTextView:
    return UtteranceTextView(
        view_id="utterancetext_" + suffix * 32,
        kind=kind,
        text=TEXT,
        derivation_policy="controlled fixture",
        source_transcript_segment_ids=("txsegment_" + "2" * 32,),
        source_transcript_word_ids=(
            "txword_" + "3" * 32,
            "txword_" + "4" * 32,
        ),
        integrity_sha256=HASH,
    )


def _utterance() -> Utterance:
    interval = MediaInterval(
        domain=TimeDomain.SOURCE_MEDIA,
        start_microseconds=1_000_000,
        duration_microseconds=1_000_000,
    )
    normalized = MediaInterval(
        domain=TimeDomain.NORMALIZED_CORPUS,
        start_microseconds=1_000_000,
        duration_microseconds=1_000_000,
    )
    component = UtteranceComponent(
        component_id="utterancecomponent_" + "5" * 32,
        sequence_position=0,
        source_interval=interval,
        normalized_audio_interval=normalized,
        transcript_segment_ids=("txsegment_" + "2" * 32,),
        transcript_word_ids=(
            "txword_" + "3" * 32,
            "txword_" + "4" * 32,
        ),
        verbatim_text=TEXT,
        integrity_sha256=HASH,
    )
    raw = _view(UtteranceTextKind.RAW_MACHINE_TRANSCRIPT, "6")
    display = _view(UtteranceTextKind.DISPLAY, "7")
    analysis = _view(
        UtteranceTextKind.MINIMALLY_NORMALIZED_ANALYSIS, "8"
    )
    attribution = UtteranceAttribution(
        attribution_id="utteranceattr_" + "9" * 32,
        status=UtteranceAttributionStatus.UNKNOWN,
        target_kind=UtteranceAttributionTargetKind.UNKNOWN,
        display_label="UNKNOWN",
        confidence=_confidence(),
        phase3_identity_view_assembly_id=(
            "identityviewassembly_" + "a" * 32
        ),
        phase3_reviewed_identity_view_id="identityview_" + "b" * 32,
        evidence_references=("fixture:unknown-speaker",),
        integrity_sha256=HASH,
    )
    return Utterance(
        utterance_id="utterance_" + "c" * 32,
        utterance_corpus_id="utterancecorpus_" + "d" * 32,
        source_corpus_id="corpus_" + "e" * 32,
        source_id="src_" + "f" * 32,
        phase2_transcript_assembly_id="txassembly_" + "1" * 32,
        phase2_transcript_version_id="txversion_" + "2" * 32,
        phase3_identity_view_assembly_id=(
            "identityviewassembly_" + "a" * 32
        ),
        phase3_reviewed_identity_view_id="identityview_" + "b" * 32,
        components=(component,),
        source_intervals=(interval,),
        normalized_audio_intervals=(normalized,),
        attribution=attribution,
        text_views=(raw, display, analysis),
        displayed_text_view_id=display.view_id,
        completeness=UtteranceCompletenessClassification.COMPLETE,
        completeness_evidence_references=("fixture:complete",),
        interruption_status=UtteranceInterruptionStatus.NONE,
        repair_status=UtteranceRepairStatus.NONE,
        overlap_status=UtteranceOverlapStatus.NONE,
        quotation_status=UtteranceQuotationStatus.NONE,
        speech_source_type=SpeechSourceType.PRIMARY_SOURCE_PARTICIPANT,
        review_status=UtteranceReviewStatus.UNREVIEWED,
        creation_process=UtteranceCreationProcess.DETERMINISTIC_SEGMENTATION,
        configuration_hash=HASH,
        created_at=NOW,
        integrity_sha256=HASH,
    )


def _phase4() -> UtteranceCorpus:
    utterance = _utterance()
    return UtteranceCorpus(
        corpus_id="utterancecorpus_" + "d" * 32,
        run_id="utterancerun_" + "1" * 32,
        source_corpus_id="corpus_" + "e" * 32,
        source_id="src_" + "f" * 32,
        phase2_transcript_assembly_id="txassembly_" + "1" * 32,
        phase2_transcript_version_id="txversion_" + "2" * 32,
        phase3_identity_view_assembly_id=(
            "identityviewassembly_" + "a" * 32
        ),
        phase3_reviewed_identity_view_id="identityview_" + "b" * 32,
        utterances=(utterance,),
        created_at=NOW,
        integrity_sha256=HASH,
    )


def _span(suffix: str = "1") -> DiscourseEvidenceSpan:
    return DiscourseEvidenceSpan(
        span_id="discoursespan_" + suffix * 32,
        utterance_id="utterance_" + "c" * 32,
        utterance_text_view_id="utterancetext_" + "7" * 32,
        text_view_version="phase4-display-1.0.0",
        start_text_offset=0,
        end_text_offset=3,
        transcript_word_ids=("txword_" + "3" * 32,),
        source_interval=MediaInterval(
            domain=TimeDomain.SOURCE_MEDIA,
            start_microseconds=1_000_000,
            duration_microseconds=150_000,
        ),
        exact_displayed_text="Yes",
        role=DiscourseEvidenceSpanRole.ACT_TRIGGER,
        confidence=_confidence(),
        integrity_sha256=HASH,
    )


def _observation(
    family=DiscourseActFamily.ANSWER,
    act_type=DiscourseActType.AFFIRMATIVE_ANSWER,
) -> DiscourseActObservation:
    return DiscourseActObservation(
        observation_id="discourseobs_" + "2" * 32,
        discourse_run_id="discourserun_" + "3" * 32,
        phase4_utterance_corpus_id="utterancecorpus_" + "d" * 32,
        utterance_id="utterance_" + "c" * 32,
        evidence_spans=(_span(),),
        act_family=family,
        act_type=act_type,
        confidence=_multi_confidence(),
        analysis_method=DiscourseAnalysisMethod.DETERMINISTIC_RULE,
        review_status=DiscourseReviewStatus.UNREVIEWED,
        created_at=NOW,
        integrity_sha256=HASH,
    )


def _candidate(
    suffix: str,
    family: DiscourseActFamily,
    act_type: DiscourseActType,
    disposition: CandidateDisposition,
    compatible=(),
    excludes=(),
) -> DiscourseActCandidate:
    return DiscourseActCandidate(
        candidate_id="discoursecandidate_" + suffix * 32,
        observation_ids=("discourseobs_" + "2" * 32,),
        act_family=family,
        act_type=act_type,
        evidence_span_ids=("discoursespan_" + "1" * 32,),
        compatible_candidate_ids=compatible,
        excludes_candidate_ids=excludes,
        disposition=disposition,
        selection_confidence=_confidence(),
        selection_rationale=("Compatible explicit marker evidence.",),
    )


def _corpus() -> DiscourseCorpus:
    phase4 = _phase4()
    observation = _observation()
    candidate = _candidate(
        "4",
        DiscourseActFamily.ANSWER,
        DiscourseActType.AFFIRMATIVE_ANSWER,
        CandidateDisposition.SELECTED,
    )
    candidate_set = DiscourseActCandidateSet(
        candidate_set_id="discoursecandidates_" + "5" * 32,
        utterance_id=observation.utterance_id,
        candidates=(candidate,),
        selection_policy_version="1.0.0",
        unresolved=False,
        integrity_sha256=HASH,
    )
    act = DiscourseAct(
        act_id="discourseact_" + "6" * 32,
        discourse_corpus_id="discoursecorpus_" + "7" * 32,
        candidate_set_id=candidate_set.candidate_set_id,
        selected_candidate_id=candidate.candidate_id,
        source_observation_ids=(observation.observation_id,),
        utterance_id=observation.utterance_id,
        act_family=candidate.act_family,
        act_type=candidate.act_type,
        evidence_spans=observation.evidence_spans,
        confidence=_multi_confidence(),
        review_status=DiscourseReviewStatus.UNREVIEWED,
        created_at=NOW,
        integrity_sha256=HASH,
    )
    provisional = DiscourseCorpus(
        corpus_id="discoursecorpus_" + "7" * 32,
        run_id="discourserun_" + "3" * 32,
        source_corpus_id=phase4.source_corpus_id,
        source_id=phase4.source_id,
        phase4_utterance_corpus_id=phase4.corpus_id,
        phase4_utterance_corpus_sha256=canonical_hash(phase4),
        observations=(observation,),
        candidate_sets=(candidate_set,),
        selected_acts=(act,),
        unclassified_utterance_ids=(),
        created_at=NOW,
        integrity_sha256="0" * 64,
    )
    return seal_discourse_corpus(provisional)


def test_vocabulary_is_closed_complete_and_boundary_safe():
    assert len(PHASE5_CONTRACT_MODELS) == 16
    assert len(PHASE5_PROVIDER_CONTRACT_MODELS) == 2
    assert set(DiscourseActType) == set().union(*FAMILY_TYPES.values())
    assert sum(len(values) for values in FAMILY_TYPES.values()) == 145
    policy = DiscourseVocabularyPolicy()
    assert policy.multi_label_required
    assert not policy.assertion_implies_truth
    assert not policy.answer_implies_adequacy
    assert not policy.rebuttal_implies_success
    with pytest.raises(ValidationError):
        DiscourseAnalysisPolicy(maximum_candidates_per_span=0)
    with pytest.raises(ValidationError):
        DiscourseVocabularyPolicy(vocabulary_version="2.0.0")


def test_observation_requires_family_type_and_provider_coherence():
    with pytest.raises(ValidationError, match="declared family"):
        _observation(
            DiscourseActFamily.QUESTION,
            DiscourseActType.AFFIRMATIVE_ANSWER,
        )
    provider_observation = _observation().model_dump()
    provider_observation["analysis_method"] = (
        DiscourseAnalysisMethod.PROVIDER_PROPOSAL
    )
    with pytest.raises(ValidationError, match="provider provenance"):
        DiscourseActObservation(**provider_observation)


def test_candidate_sets_allow_multi_label_and_reject_exclusions():
    answer_id = "discoursecandidate_" + "4" * 32
    qualification_id = "discoursecandidate_" + "8" * 32
    answer = _candidate(
        "4",
        DiscourseActFamily.ANSWER,
        DiscourseActType.AFFIRMATIVE_ANSWER,
        CandidateDisposition.SELECTED,
        compatible=(qualification_id,),
    )
    qualification = _candidate(
        "8",
        DiscourseActFamily.QUALIFICATION,
        DiscourseActType.TEMPORAL_QUALIFICATION,
        CandidateDisposition.SELECTED,
        compatible=(answer_id,),
    )
    result = DiscourseActCandidateSet(
        candidate_set_id="discoursecandidates_" + "5" * 32,
        utterance_id="utterance_" + "c" * 32,
        candidates=(answer, qualification),
        selection_policy_version="1.0.0",
        unresolved=False,
        integrity_sha256=HASH,
    )
    assert len(result.candidates) == 2

    incompatible = qualification.model_copy(
        update={
            "compatible_candidate_ids": (),
            "excludes_candidate_ids": (answer_id,),
        }
    )
    with pytest.raises(ValidationError, match="incompatible"):
        DiscourseActCandidateSet(
            candidate_set_id="discoursecandidates_" + "5" * 32,
            utterance_id="utterance_" + "c" * 32,
            candidates=(answer, incompatible),
            selection_policy_version="1.0.0",
            unresolved=False,
            integrity_sha256=HASH,
        )


def test_source_validation_and_persistence_are_phase4_immutable(tmp_path):
    phase4 = _phase4()
    corpus = _corpus()
    result = validate_discourse_corpus(corpus, phase4, checked_at=NOW)
    assert result.valid
    assert result.findings == ()

    path = persist_discourse_corpus(
        corpus, phase4, tmp_path / "discourse-corpus.json", checked_at=NOW
    )
    assert load_discourse_corpus(path, phase4, checked_at=NOW) == corpus

    bad_observation = corpus.observations[0].model_copy(
        update={
            "evidence_spans": (
                corpus.observations[0].evidence_spans[0].model_copy(
                    update={"exact_displayed_text": "No"}
                ),
            )
        }
    )
    bad = seal_discourse_corpus(
        corpus.model_copy(update={"observations": (bad_observation,)})
    )
    invalid = validate_discourse_corpus(bad, phase4, checked_at=NOW)
    assert not invalid.valid
    assert invalid.findings[0].code == "phase5.span.text_mismatch"
    with pytest.raises(Phase5IntegrityError):
        persist_discourse_corpus(
            bad, phase4, tmp_path / "bad.json", checked_at=NOW
        )


def test_unconfigured_provider_is_visible_and_refuses_execution():
    registry = DiscourseProviderRegistry.with_boundaries()
    capabilities = registry.list()
    assert len(capabilities) == 1
    assert not capabilities[0].available
    with pytest.raises(DiscourseProviderUnavailable):
        registry.get("missing.discourse")


def test_discourse_provider_cli_is_structured_and_conservative(capsys):
    assert main(["--json", "discourse-provider", "list"]) == 0
    import json

    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["identity"]["provider_id"] == "unconfigured.discourse"
    assert payload[0]["available"] is False
    assert main([
        "--json", "discourse-provider", "inspect", "missing.discourse"
    ]) == 4