from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from ratiocinatus.addressing_contracts import MediaInterval, TimeDomain
from ratiocinatus.kernel import canonical_hash
from ratiocinatus.phase2_contracts import ConfidenceMeasure, ConfidenceOrigin
from ratiocinatus.phase4_contracts import (
    PHASE4_CONTRACT_MODELS,
    Phase4IntegrityFinding,
    Phase4IntegrityResult,
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
    UtteranceNormalizationPolicy,
    UtteranceOverlapStatus,
    UtteranceQuotationStatus,
    UtteranceRepairStatus,
    UtteranceReviewStatus,
    UtteranceSegmentationPolicy,
    UtteranceTextKind,
    UtteranceTextView,
)
from ratiocinatus.contracts import Severity


NOW = datetime(2000, 1, 1, tzinfo=timezone.utc)
HASH = "1" * 64


def _confidence() -> ConfidenceMeasure:
    return ConfidenceMeasure(
        value=0.8,
        origin=ConfidenceOrigin.DERIVED,
        basis="controlled Phase 4 foundation fixture",
    )


def _text(kind: UtteranceTextKind, suffix: str) -> UtteranceTextView:
    return UtteranceTextView(
        view_id="utterancetext_" + suffix * 32,
        kind=kind,
        text="Well, I agree.",
        derivation_policy="controlled fixture retains audible surface text",
        source_transcript_segment_ids=("txsegment_" + "2" * 32,),
        source_transcript_word_ids=("txword_" + "3" * 32,),
        integrity_sha256=HASH,
    )


def _attribution(
    *,
    status: UtteranceAttributionStatus = (
        UtteranceAttributionStatus.MANUALLY_BOUND
    ),
    target_kind: UtteranceAttributionTargetKind = (
        UtteranceAttributionTargetKind.PARTICIPANT_IDENTITY
    ),
    target_id: str | None = "identity_" + "4" * 32,
    candidates: tuple[str, ...] = (),
) -> UtteranceAttribution:
    return UtteranceAttribution(
        attribution_id="utteranceattr_" + "5" * 32,
        status=status,
        target_kind=target_kind,
        target_id=target_id,
        candidate_target_ids=candidates,
        display_label="REVIEWED: Participant A",
        confidence=_confidence(),
        phase3_identity_view_assembly_id=(
            "identityviewassembly_" + "6" * 32
        ),
        phase3_reviewed_identity_view_id="identityview_" + "7" * 32,
        speaker_turn_ids=("speakerturn_" + "8" * 32,),
        speaker_observation_ids=("spkobs_" + "9" * 32,),
        evidence_references=("fixture:reviewed-attribution",),
        integrity_sha256=HASH,
    )


def _component(word: str = "3") -> UtteranceComponent:
    return UtteranceComponent(
        component_id="utterancecomponent_" + word * 32,
        sequence_position=0,
        source_interval=MediaInterval(
            domain=TimeDomain.SOURCE_MEDIA,
            start_microseconds=1_000_000,
            duration_microseconds=750_000,
        ),
        normalized_audio_interval=MediaInterval(
            domain=TimeDomain.NORMALIZED_CORPUS,
            start_microseconds=1_000_000,
            duration_microseconds=750_000,
        ),
        transcript_segment_ids=("txsegment_" + "2" * 32,),
        transcript_word_ids=("txword_" + word * 32,),
        speaker_turn_ids=("speakerturn_" + "8" * 32,),
        speaker_observation_ids=("spkobs_" + "9" * 32,),
        verbatim_text="Well, I agree.",
        processing_chunk_ids=("chunk_" + "a" * 32,),
        integrity_sha256=HASH,
    )


def _utterance(
    *,
    suffix: str = "a",
    component: UtteranceComponent | None = None,
    completeness: UtteranceCompletenessClassification = (
        UtteranceCompletenessClassification.COMPLETE
    ),
    interruption: UtteranceInterruptionStatus = (
        UtteranceInterruptionStatus.NONE
    ),
) -> Utterance:
    raw = _text(UtteranceTextKind.RAW_MACHINE_TRANSCRIPT, "b")
    display = _text(UtteranceTextKind.DISPLAY, "c")
    analysis = _text(
        UtteranceTextKind.MINIMALLY_NORMALIZED_ANALYSIS, "d"
    )
    item = component or _component()
    return Utterance(
        utterance_id="utterance_" + suffix * 32,
        utterance_corpus_id="utterancecorpus_" + "e" * 32,
        source_corpus_id="corpus_" + "f" * 32,
        source_id="src_" + "0" * 32,
        phase2_transcript_assembly_id="txassembly_" + "1" * 32,
        phase2_transcript_version_id="txversion_" + "2" * 32,
        phase3_identity_view_assembly_id=(
            "identityviewassembly_" + "6" * 32
        ),
        phase3_reviewed_identity_view_id="identityview_" + "7" * 32,
        components=(item,),
        source_intervals=(item.source_interval,),
        normalized_audio_intervals=(item.normalized_audio_interval,),
        attribution=_attribution(),
        text_views=(raw, display, analysis),
        displayed_text_view_id=display.view_id,
        completeness=completeness,
        completeness_evidence_references=("fixture:punctuation-and-pause",),
        interruption_status=interruption,
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


def _corpus(*utterances: Utterance) -> UtteranceCorpus:
    return UtteranceCorpus(
        corpus_id="utterancecorpus_" + "e" * 32,
        run_id="utterancerun_" + "3" * 32,
        source_corpus_id="corpus_" + "f" * 32,
        source_id="src_" + "0" * 32,
        phase2_transcript_assembly_id="txassembly_" + "1" * 32,
        phase2_transcript_version_id="txversion_" + "2" * 32,
        phase3_identity_view_assembly_id=(
            "identityviewassembly_" + "6" * 32
        ),
        phase3_reviewed_identity_view_id="identityview_" + "7" * 32,
        utterances=utterances,
        created_at=NOW,
        integrity_sha256=HASH,
    )


def test_phase4_contract_inventory_and_policy_are_strict() -> None:
    assert len(PHASE4_CONTRACT_MODELS) == 17
    assert len({model.__name__ for model in PHASE4_CONTRACT_MODELS}) == 17
    policy = UtteranceSegmentationPolicy()
    assert policy.speaker_change_is_hard_boundary
    assert not policy.semantic_continuity_enabled
    assert UtteranceNormalizationPolicy().retain_meaningful_repetitions

    with pytest.raises(ValidationError, match="minimum utterance duration"):
        UtteranceSegmentationPolicy(
            minimum_utterance_duration_microseconds=2_000_000,
            maximum_utterance_duration_microseconds=1_000_000,
        )
    with pytest.raises(ValidationError):
        UtteranceSegmentationPolicy(policy_version="2.0.0")
    with pytest.raises(ValidationError):
        UtteranceNormalizationPolicy(invent_missing_words=True)


def test_attribution_preserves_unknown_and_conflicting_states() -> None:
    unknown = _attribution(
        status=UtteranceAttributionStatus.UNKNOWN,
        target_kind=UtteranceAttributionTargetKind.UNKNOWN,
        target_id=None,
    )
    assert unknown.target_id is None

    with pytest.raises(ValidationError, match="cannot force a target"):
        _attribution(
            status=UtteranceAttributionStatus.UNKNOWN,
            target_kind=UtteranceAttributionTargetKind.UNKNOWN,
        )
    with pytest.raises(ValidationError, match="multiple candidates"):
        _attribution(
            status=UtteranceAttributionStatus.CONFLICTING,
            target_kind=(
                UtteranceAttributionTargetKind.MULTIPLE_CANDIDATES
            ),
            target_id=None,
            candidates=("identity_" + "4" * 32,),
        )


def test_utterance_requires_text_views_and_coherent_interruption() -> None:
    utterance = _utterance()
    assert utterance.text_views[1].kind == UtteranceTextKind.DISPLAY

    with pytest.raises(ValidationError, match="interruption state"):
        _utterance(
            completeness=UtteranceCompletenessClassification.INTERRUPTED
        )
    interrupted = _utterance(
        completeness=UtteranceCompletenessClassification.INTERRUPTED,
        interruption=UtteranceInterruptionStatus.INTERRUPTED,
    )
    assert interrupted.completeness.value == "interrupted"

    missing_analysis = utterance.model_dump()
    missing_analysis["text_views"] = missing_analysis["text_views"][:2]
    with pytest.raises(ValidationError, match="minimally_normalized_analysis"):
        Utterance(**missing_analysis)


def test_corpus_has_stable_hash_and_refuses_duplicate_word_ownership() -> None:
    first = _utterance(suffix="a")
    corpus = _corpus(first)
    reloaded = UtteranceCorpus.model_validate(
        corpus.model_dump(mode="json"), strict=False
    )
    assert reloaded == corpus
    assert canonical_hash(reloaded) == canonical_hash(corpus)

    second_component = _component()
    second = _utterance(suffix="b", component=second_component)
    with pytest.raises(ValidationError, match="duplicate ownership"):
        _corpus(first, second)


def test_integrity_result_validity_tracks_blocking_findings() -> None:
    warning = Phase4IntegrityFinding(
        finding_id="phase4finding_" + "1" * 32,
        code="phase4.fixture.warning",
        severity=Severity.WARNING,
        message="Controlled non-blocking warning.",
    )
    valid = Phase4IntegrityResult(
        result_id="phase4integrity_" + "2" * 32,
        utterance_corpus_id="utterancecorpus_" + "e" * 32,
        checked_at=NOW,
        findings=(warning,),
        valid=True,
        integrity_sha256=HASH,
    )
    assert valid.valid

    with pytest.raises(ValidationError, match="disagrees"):
        Phase4IntegrityResult(
            result_id="phase4integrity_" + "3" * 32,
            utterance_corpus_id="utterancecorpus_" + "e" * 32,
            checked_at=NOW,
            findings=(warning,),
            valid=False,
            integrity_sha256=HASH,
        )
