import json
from pathlib import Path

import pytest

from ratiocinatus.cli import main
from ratiocinatus.discourse_baseline import build_deterministic_discourse
from ratiocinatus.discourse_consolidation import (
    DiscourseConsolidationIntegrityError,
    build_discourse_consolidation,
    load_discourse_consolidation,
    persist_discourse_consolidation,
    validate_discourse_consolidation,
)
from ratiocinatus.discourse_provider_analysis import (
    run_provider_analysis,
    seal_provider_response,
)
from ratiocinatus.discourse_providers import UnconfiguredDiscourseProvider
from ratiocinatus.kernel import canonical_hash, typed_id
from ratiocinatus.phase5_contracts import (
    CandidateDisposition,
    DiscourseActFamily,
    DiscourseActType,
)

from test_phase5_deterministic_baseline import _with_texts
from test_phase5_foundation import NOW
from test_phase5_provider_analysis import ControlledProvider, _context_bundle


def _evidence(*texts, provider=None):
    corpus = _with_texts(*texts)
    context = _context_bundle(corpus)
    baseline, baseline_report = build_deterministic_discourse(
        corpus, created_at=NOW
    )
    provider_run, provider_report = run_provider_analysis(
        corpus,
        context,
        provider or ControlledProvider(),
        created_at=NOW,
    )
    return (
        corpus,
        context,
        baseline,
        baseline_report,
        provider_run,
        provider_report,
    )


class ConflictingQuestionProvider(ControlledProvider):
    def analyze(self, request):
        response = super().analyze(request)
        proposal = response.proposals[0].model_copy(
            update={
                "act_family": DiscourseActFamily.QUESTION,
                "act_type": DiscourseActType.ALTERNATIVE_QUESTION,
                "classification_confidence": 0.85,
            }
        )
        proposals = (proposal,)
        raw_hash = canonical_hash(
            tuple(item.model_dump(mode="json") for item in proposals)
        )
        return seal_provider_response(
            response.model_copy(
                update={
                    "response_id": typed_id(
                        "discourseresponse", request.request_id, raw_hash
                    ),
                    "proposals": proposals,
                    "raw_output_sha256": raw_hash,
                    "integrity_sha256": "0" * 64,
                }
            )
        )


def test_consolidation_merges_corroboration_and_selects_compatible_labels():
    inputs = _evidence(
        "What time is the hearing?",
        "Yes, but only after 2022.",
    )
    run, corpus, report = build_discourse_consolidation(
        *inputs[2:], inputs[0], inputs[1], created_at=NOW
    )
    assert report.corroborated_candidate_count == 2
    assert report.provider_only_candidate_count == 1
    assert report.multi_label_utterance_count == 1
    assert report.canonical_act_count == len(corpus.selected_acts) == 5
    question = next(
        item
        for item in run.evidence_summaries
        if item.disposition.value == "corroborated"
        and len(item.observation_ids) == 2
    )
    assert question.selection_score >= 0.9
    assert all(
        candidate.disposition == CandidateDisposition.SELECTED
        for item in run.candidate_sets
        for candidate in item.candidates
    )
    validate_discourse_consolidation(
        run, corpus, report, *inputs[2:], inputs[0], inputs[1]
    )


def test_close_mutually_exclusive_candidates_remain_unresolved():
    inputs = _evidence(
        "What time is the hearing?",
        provider=ConflictingQuestionProvider(),
    )
    run, corpus, report = build_discourse_consolidation(
        *inputs[2:], inputs[0], inputs[1], created_at=NOW
    )
    assert report.unresolved_candidate_set_count == 1
    assert report.canonical_act_count == 0
    assert corpus.unclassified_utterance_ids == (
        inputs[0].utterances[0].utterance_id,
    )
    dispositions = {
        item.disposition for item in run.candidate_sets[0].candidates
    }
    assert dispositions == {CandidateDisposition.UNRESOLVED}
    assert len(run.candidate_sets[0].candidates) == 2


def test_provider_unavailability_does_not_erase_deterministic_evidence():
    inputs = _evidence(
        "What time is the hearing?",
        provider=UnconfiguredDiscourseProvider(),
    )
    run, corpus, report = build_discourse_consolidation(
        *inputs[2:], inputs[0], inputs[1], created_at=NOW
    )
    assert report.provider_failure_count == 1
    assert report.deterministic_only_candidate_count == 1
    assert report.provider_only_candidate_count == 0
    assert len(corpus.selected_acts) == 1
    assert run.evidence_summaries[0].disposition.value == "deterministic_only"


def test_consolidation_persistence_replays_and_rejects_tampering(
    tmp_path: Path,
):
    inputs = _evidence("What time is the hearing?")
    artifacts = build_discourse_consolidation(
        *inputs[2:], inputs[0], inputs[1], created_at=NOW
    )
    paths = persist_discourse_consolidation(
        *artifacts, *inputs[2:], inputs[0], inputs[1], tmp_path / "merged"
    )
    assert not paths[3]
    assert load_discourse_consolidation(tmp_path / "merged") == artifacts
    assert persist_discourse_consolidation(
        *artifacts, *inputs[2:], inputs[0], inputs[1], tmp_path / "merged"
    )[3]
    tampered = artifacts[0].model_copy(
        update={"configuration_hash": "f" * 64}
    )
    with pytest.raises(
        DiscourseConsolidationIntegrityError, match="integrity"
    ):
        validate_discourse_consolidation(
            tampered,
            artifacts[1],
            artifacts[2],
            *inputs[2:],
            inputs[0],
            inputs[1],
        )


def test_consolidation_cli_inspects_candidates_acts_and_ambiguity(
    tmp_path: Path, capsys
):
    inputs = _evidence("What time is the hearing?")
    artifacts = build_discourse_consolidation(
        *inputs[2:], inputs[0], inputs[1], created_at=NOW
    )
    root = tmp_path / "merged"
    persist_discourse_consolidation(
        *artifacts, *inputs[2:], inputs[0], inputs[1], root
    )
    assert main(
        ["--json", "discourse", "consolidate-inspect", str(root)]
    ) == 0
    assert json.loads(capsys.readouterr().out)["report"][
        "canonical_act_count"
    ] == 1
    assert main(
        ["--json", "discourse", "list-candidates", str(root)]
    ) == 0
    assert len(json.loads(capsys.readouterr().out)) == 1
    assert main(
        ["--json", "discourse", "list-canonical-acts", str(root)]
    ) == 0
    assert len(json.loads(capsys.readouterr().out)) == 1
    assert main(
        ["--json", "discourse", "list-ambiguous", str(root)]
    ) == 0
    assert json.loads(capsys.readouterr().out) == []
