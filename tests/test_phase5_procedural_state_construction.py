import json
from pathlib import Path

import pytest

from ratiocinatus.cli import main
from ratiocinatus.discourse_consolidation import (
    build_discourse_consolidation,
)
from ratiocinatus.discourse_provider_analysis import seal_provider_response
from ratiocinatus.kernel import canonical_hash, typed_id
from ratiocinatus.phase5_contracts import (
    DiscourseActFamily,
    DiscourseActType,
    DiscourseEvidenceSpanRole,
    DiscourseTargetStatus,
)
from ratiocinatus.phase5_provider_analysis_contracts import (
    ProviderActProposal,
    ProviderAnalysisResponse,
    ProviderSpanProposal,
)
from ratiocinatus.procedural_state_construction import (
    ProceduralStateIntegrityError,
    build_procedural_state,
    load_procedural_state,
    persist_procedural_state,
    validate_procedural_state,
)

from test_phase5_candidate_consolidation import _evidence
from test_phase5_foundation import NOW
from test_phase5_provider_analysis import ControlledProvider


class ProceduralProvider(ControlledProvider):
    TYPES = {
        "I yield.": DiscourseActType.TURN_YIELD,
        "May I speak?": DiscourseActType.FLOOR_REQUEST,
        "Moderator intervention.": DiscourseActType.MODERATOR_INTERVENTION,
        "The connection was interrupted.": (
            DiscourseActType.TECHNICAL_INTERRUPTION_NOTICE
        ),
    }

    def analyze(self, request):
        target = next(item for item in request.context_items if item.is_target)
        act_type = self.TYPES.get(target.displayed_text)
        if act_type is None:
            return super().analyze(request)
        self.calls += 1
        text = target.displayed_text
        proposal = ProviderActProposal(
            provider_proposal_id=typed_id(
                "providerproposal", request.request_id, 1
            ),
            act_family=DiscourseActFamily.PROCEDURAL,
            act_type=act_type,
            spans=(
                ProviderSpanProposal(
                    proposal_span_id=typed_id(
                        "providerspan", request.request_id, 1
                    ),
                    start_text_offset=0,
                    end_text_offset=len(text),
                    exact_displayed_text=text,
                    role=DiscourseEvidenceSpanRole.PROCEDURAL_FORMULA,
                    confidence=0.86,
                ),
            ),
            classification_confidence=0.9,
            rank=1,
            evidence_for=("controlled procedural event",),
        )
        raw_hash = canonical_hash((proposal.model_dump(mode="json"),))
        return seal_provider_response(
            ProviderAnalysisResponse(
                response_id=typed_id(
                    "discourseresponse", request.request_id, raw_hash
                ),
                request_id=request.request_id,
                provider=self.capabilities.identity,
                proposals=(proposal,),
                raw_output_sha256=raw_hash,
                raw_output_retained=True,
                completed_at=NOW,
                integrity_sha256="0" * 64,
            )
        )


def _procedural(*texts, provider=None):
    inputs = _evidence(
        *texts, provider=provider or ControlledProvider()
    )
    _, corpus, _ = build_discourse_consolidation(
        *inputs[2:], inputs[0], inputs[1], created_at=NOW
    )
    return inputs[0], corpus


def test_events_are_source_ordered_and_every_event_has_a_snapshot():
    phase4, corpus = _procedural(
        "You have two minutes remaining.",
        "Let's move on.",
        "Time is up.",
    )
    run, report = build_procedural_state(
        corpus, phase4, created_at=NOW
    )
    assert report.event_count == 3
    assert len(run.events) == len(run.snapshots) == 3
    starts = [
        item.source_intervals[0].start_microseconds for item in run.events
    ]
    assert starts == sorted(starts)
    assert [item.sequence_position for item in run.snapshots] == [0, 1, 2]
    assert all(item.source_intervals for item in run.events)
    validate_procedural_state(run, report, corpus, phase4)


def test_floor_grant_opens_response_and_time_expiry_closes_it():
    phase4, corpus = _procedural(
        "You may respond.",
        "You have two minutes remaining.",
        "Time is up.",
    )
    run, report = build_procedural_state(
        corpus, phase4, created_at=NOW
    )
    assert run.snapshots[0].active_response
    assert run.snapshots[0].active_response_started_microseconds is not None
    assert run.snapshots[1].active_response
    assert not run.snapshots[2].active_response
    assert run.snapshots[2].time_expired
    assert report.final_time_expired
    assert not report.final_active_response
    assert report.timing_event_count == 2


def test_explicit_turn_yield_closes_active_response_interval():
    phase4, corpus = _procedural(
        "You may respond.",
        "I yield.",
        provider=ProceduralProvider(),
    )
    run, report = build_procedural_state(
        corpus, phase4, created_at=NOW
    )
    assert run.events[1].event_kind.value == "turn_yield"
    assert run.snapshots[0].active_response
    assert not run.snapshots[1].active_response
    assert report.floor_event_count == 2


def test_answer_request_retains_probable_pending_question():
    phase4, corpus = _procedural(
        "What time is the hearing?",
        "Please answer the question.",
    )
    run, report = build_procedural_state(
        corpus, phase4, created_at=NOW
    )
    request = next(
        item
        for item in run.events
        if item.procedural_act_type == DiscourseActType.REQUEST_TO_ANSWER
    )
    snapshot = next(
        item
        for item in run.snapshots
        if item.triggering_event_id == request.event_id
    )
    assert request.procedural_target_status == DiscourseTargetStatus.PROBABLE
    assert len(request.procedural_target_ids) == 1
    assert snapshot.pending_question_act_ids == (
        request.procedural_target_ids
    )
    assert report.pending_question_event_count == 1


def test_observed_speaker_is_distinct_and_no_enforcement_is_assigned():
    phase4, corpus = _procedural("You may respond.")
    run, report = build_procedural_state(
        corpus, phase4, created_at=NOW
    )
    event = run.events[0]
    utterance = phase4.utterances[0]
    assert event.observed_attribution_id == (
        utterance.attribution.attribution_id
    )
    assert event.observed_speaker_display_label == (
        utterance.attribution.display_label
    )
    assert run.snapshots[0].recognized_speaker_target_id is None
    assert not event.violation_assigned
    assert not event.fault_assigned
    assert not event.blame_assigned
    assert not event.sanction_assigned
    assert (
        report.violation_count,
        report.fault_count,
        report.blame_count,
        report.sanction_count,
    ) == (0, 0, 0, 0)


def test_procedural_state_persistence_cli_and_tamper_detection(
    tmp_path: Path, capsys
):
    phase4, corpus = _procedural(
        "You have two minutes remaining.",
        "Time is up.",
    )
    artifacts = build_procedural_state(
        corpus, phase4, created_at=NOW
    )
    root = tmp_path / "procedural"
    paths = persist_procedural_state(
        *artifacts, corpus, phase4, root
    )
    assert not paths[2]
    assert load_procedural_state(root) == artifacts
    assert persist_procedural_state(
        *artifacts, corpus, phase4, root
    )[2]
    assert main(
        ["--json", "discourse", "procedural-state-inspect", str(root)]
    ) == 0
    assert json.loads(capsys.readouterr().out)["report"][
        "timing_event_count"
    ] == 2
    assert main(
        ["--json", "discourse", "list-procedural-snapshots", str(root)]
    ) == 0
    assert len(json.loads(capsys.readouterr().out)) == 2
    tampered = artifacts[0].model_copy(
        update={"configuration_hash": "f" * 64}
    )
    with pytest.raises(ProceduralStateIntegrityError, match="integrity"):
        validate_procedural_state(
            tampered, artifacts[1], corpus, phase4
        )
