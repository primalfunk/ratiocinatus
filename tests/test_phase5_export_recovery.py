import json
from pathlib import Path

import pytest

from ratiocinatus.argument_relation_construction import (
    build_argument_relations,
)
from ratiocinatus.discourse_consolidation import build_discourse_consolidation
from ratiocinatus.discourse_review import (
    build_discourse_propagation,
    build_discourse_review_queue,
    create_discourse_review_ledger,
)
from ratiocinatus.lexical_example_quotation_construction import (
    build_lexical_example_quotation,
)
from ratiocinatus.phase5_evaluation import evaluate_phase5
from ratiocinatus.phase5_export import (
    Phase5ExportIntegrityError,
    Phase5PortableArtifactSet,
    export_phase5_corpus,
    load_phase5_export,
    reload_phase5_export,
    validate_phase5_export,
    validate_phase5_portable_artifacts,
)
from ratiocinatus.phase5_foundation import validate_discourse_corpus
from ratiocinatus.phase5_recovery import (
    Phase5RecoveryTask,
    downstream_stages,
    run_phase5_recovery,
)
from ratiocinatus.phase5_recovery_contracts import (
    Phase5NegativeProof,
    Phase5NegativeProofKind,
    Phase5RecoveryAction,
    Phase5RecoveryStage,
)
from ratiocinatus.procedural_state_construction import build_procedural_state
from ratiocinatus.question_answer_construction import build_question_answers

from test_phase5_candidate_consolidation import _evidence
from test_phase5_evaluation import _reference
from test_phase5_foundation import NOW
from test_phase5_review_propagation import _change_display_text


def _portable():
    inputs = _evidence(
        "What time is the hearing?",
        "Yes, but only after 2022.",
    )
    consolidation, corpus, consolidation_report = (
        build_discourse_consolidation(
            *inputs[2:], inputs[0], inputs[1], created_at=NOW
        )
    )
    question, question_report = build_question_answers(
        corpus, inputs[1], created_at=NOW
    )
    argument, argument_report = build_argument_relations(
        corpus, inputs[1], created_at=NOW
    )
    lexical, lexical_report = build_lexical_example_quotation(
        corpus, inputs[1], created_at=NOW
    )
    procedural, procedural_report = build_procedural_state(
        corpus, inputs[0], created_at=NOW
    )
    ledger = create_discourse_review_ledger(corpus, created_at=NOW)
    successor = _change_display_text(
        inputs[0],
        inputs[0].utterances[0].utterance_id,
        "When is the hearing?",
    )
    propagation, propagation_report = build_discourse_propagation(
        inputs[0], successor, corpus, created_at=NOW
    )
    queue = build_discourse_review_queue(
        corpus,
        inputs[0],
        ledger,
        propagation=propagation,
        generated_at=NOW,
    )
    reference = _reference(corpus)
    evaluation, evaluation_report = evaluate_phase5(
        corpus, inputs[0], reference, generated_at=NOW
    )
    integrity = validate_discourse_corpus(
        corpus, inputs[0], checked_at=NOW
    )
    return inputs[0], Phase5PortableArtifactSet(
        consolidation=consolidation,
        corpus=corpus,
        consolidation_report=consolidation_report,
        question_answers=question,
        question_answer_report=question_report,
        argument_relations=argument,
        argument_relation_report=argument_report,
        lexical_structures=lexical,
        lexical_structure_report=lexical_report,
        procedural_state=procedural,
        procedural_state_report=procedural_report,
        review_ledger=ledger,
        review_queue=queue,
        propagation=propagation,
        propagation_report=propagation_report,
        controlled_reference=reference,
        evaluation=evaluation,
        evaluation_report=evaluation_report,
        integrity_result=integrity,
    )


def test_portable_export_reloads_every_view_without_provider_execution(
    tmp_path: Path,
):
    _, artifacts = _portable()
    first = export_phase5_corpus(
        artifacts, tmp_path / "export", Path("schemas"), created_at=NOW
    )
    replay = export_phase5_corpus(
        artifacts, tmp_path / "export", Path("schemas"), created_at=NOW
    )
    assert not first[3] and replay[3]
    manifest, report = load_phase5_export(first[2])
    assert (manifest, report) == first[:2]
    assert report.status == "valid"
    assert not report.provider_execution_used
    assert len(manifest.included_views) == 11
    assert report.artifact_count == 19
    assert report.schema_count > 0
    reloaded = reload_phase5_export(first[2])
    assert len(reloaded) == 19
    assert any(value == artifacts.corpus for value in reloaded.values())


def test_portable_export_detects_digest_corruption(tmp_path: Path):
    _, artifacts = _portable()
    manifest, _, root, _ = export_phase5_corpus(
        artifacts, tmp_path / "export", Path("schemas"), created_at=NOW
    )
    target_entry = next(
        item for item in manifest.entries if item.artifact_kind == "phase5_artifact"
    )
    target = root / target_entry.relative_path
    target.write_bytes(target.read_bytes() + b"corrupt")
    report = validate_phase5_export(root)
    assert report.status == "invalid"
    assert target_entry.relative_path in report.digest_mismatch_paths
    with pytest.raises(Phase5ExportIntegrityError, match="stale"):
        load_phase5_export(root)


def test_mixed_discourse_version_export_is_refused():
    _, artifacts = _portable()
    mixed = artifacts.question_answers.model_copy(
        update={"discourse_corpus_id": "discoursecorpus_" + "0" * 32}
    )
    artifacts = Phase5PortableArtifactSet(
        **{
            **artifacts.__dict__,
            "question_answers": mixed,
        }
    )
    with pytest.raises(Phase5ExportIntegrityError, match="integrity|mixed"):
        validate_phase5_portable_artifacts(artifacts)


def _proofs():
    return tuple(
        Phase5NegativeProof(
            kind=kind,
            passed=True,
            failure_type="ControlledTypedRefusal",
            message=(
                "Controlled negative fixture produced typed refusal or "
                "conservative degradation without source mutation."
            ),
            typed_refusal=True,
            conservative_degradation=False,
            source_evidence_preserved=True,
            evidence_references=(f"negative:{kind.value}",),
        )
        for kind in Phase5NegativeProofKind
    )


def test_recovery_quarantines_corruption_resumes_and_reuses(tmp_path: Path):
    root = tmp_path / "recovery"
    root.mkdir()
    protected = tmp_path / "phase4.json"
    protected.write_text('{"immutable":true}', encoding="utf-8")
    tasks = []
    for stage in Phase5RecoveryStage:
        artifact = root / stage.value
        if stage != Phase5RecoveryStage.CORPUS_EXPORT:
            artifact.mkdir()
            (artifact / "value.json").write_text(
                json.dumps({"stage": stage.value}), encoding="utf-8"
            )
        if stage == Phase5RecoveryStage.DEFINITION_EXAMPLE:
            (artifact / "value.json").write_text("{broken", encoding="utf-8")

        def validate(path: Path, expected=stage.value):
            payload = json.loads((path / "value.json").read_text("utf-8"))
            if payload["stage"] != expected:
                raise ValueError("stage payload mismatch")

        def rebuild(path=artifact, expected=stage.value):
            path.mkdir(parents=True, exist_ok=True)
            (path / "value.json").write_text(
                json.dumps({"stage": expected}), encoding="utf-8"
            )
            return path

        tasks.append(
            Phase5RecoveryTask(
                stage=stage,
                artifact_root=artifact,
                artifact_id=f"artifact:{stage.value}",
                validate=validate,
                rebuild=rebuild,
                provider_invoked_on_rebuild=(
                    stage == Phase5RecoveryStage.PROVIDER_ANALYSIS
                ),
            )
        )
    report = run_phase5_recovery(
        tuple(tasks),
        root,
        protected_paths=(("phase4", protected),),
        negative_proofs=_proofs(),
        generated_at=NOW,
    )
    actions = {item.stage: item.action for item in report.records}
    assert actions[Phase5RecoveryStage.DEFINITION_EXAMPLE] == (
        Phase5RecoveryAction.QUARANTINED_AND_REBUILT
    )
    assert actions[Phase5RecoveryStage.CORPUS_EXPORT] == (
        Phase5RecoveryAction.RESUMED_MISSING
    )
    assert actions[Phase5RecoveryStage.DETERMINISTIC_CLASSIFICATION] == (
        Phase5RecoveryAction.REUSED_VALID
    )
    assert report.protected_before == report.protected_after
    assert report.status == "passed"


def test_recovery_invalidation_is_transitive_and_keeps_provider_cache():
    affected = downstream_stages(
        (Phase5RecoveryStage.DETERMINISTIC_CLASSIFICATION,)
    )
    assert Phase5RecoveryStage.EVIDENCE_SPAN_NORMALIZATION in affected
    assert Phase5RecoveryStage.CANDIDATE_CONSOLIDATION in affected
    assert Phase5RecoveryStage.CORPUS_EXPORT in affected
    assert Phase5RecoveryStage.PROVIDER_ANALYSIS not in affected


def test_recovery_requires_complete_negative_inventory(tmp_path: Path):
    with pytest.raises(ValueError, match="every negative proof"):
        from ratiocinatus.phase5_recovery_contracts import (
            Phase5RecoveryPolicy,
            Phase5RecoveryRecord,
            Phase5RecoveryReport,
        )

        Phase5RecoveryReport(
            report_id="phase5recovery_" + "0" * 32,
            generated_at=NOW,
            policy=Phase5RecoveryPolicy(),
            records=tuple(
                Phase5RecoveryRecord(
                    stage=stage,
                    artifact_id=stage.value,
                    action=Phase5RecoveryAction.REUSED_VALID,
                    provider_invoked=False,
                )
                for stage in Phase5RecoveryStage
            ),
            protected_before=(),
            protected_after=(),
            interruption_boundaries=tuple(Phase5RecoveryStage),
            negative_proofs=_proofs()[:-1],
            findings=(),
            status="failed",
            integrity_sha256="0" * 64,
        )


def test_cli_exposes_export_reload_and_recovery_inspection():
    from ratiocinatus.cli import build_parser

    parser = build_parser()
    reload_args = parser.parse_args(
        ["discourse", "export-reload", "portable-export"]
    )
    recovery_args = parser.parse_args(
        ["discourse", "recovery-inspect", "recovery-report.json"]
    )
    assert reload_args.action == "export-reload"
    assert recovery_args.action == "recovery-inspect"
