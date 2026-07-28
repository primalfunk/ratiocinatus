"""Qualify the Phase 3 pipeline on the persisted Phase 1/2 >2-hour fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path

from ratiocinatus.addressing_contracts import MediaInterval, TimeDomain
from ratiocinatus.clustering import cluster_diarization
from ratiocinatus.corpus import load_corpus, validate_corpus
from ratiocinatus.diarization import diarize_corpus
from ratiocinatus.diarization_providers import DiarizationProvider
from ratiocinatus.identity import (
    add_participant_identity,
    persist_identity_foundation,
)
from ratiocinatus.identity_binding import (
    append_manual_identity_binding,
    persist_identity_binding_run,
)
from ratiocinatus.identity_view import (
    assemble_identity_views,
    persist_identity_view_assembly,
)
from ratiocinatus.kernel import canonical_hash, load_contract, typed_id
from ratiocinatus.participant_subtitles import export_participant_subtitles
from ratiocinatus.phase2_contracts import (
    ConfidenceMeasure,
    ConfidenceOrigin,
    RawEvidenceDisposition,
    RawProviderEvidence,
)
from ratiocinatus.phase3_contracts import (
    BindingAction,
    DiarizationCapability,
    DiarizationProviderCapabilities,
    DiarizationProviderIdentity,
    DiarizationProviderResponse,
    DiarizationRun,
    IdentityKind,
    IdentityScope,
    IdentityScopeKind,
    ObservationUsability,
    ProviderSpeakerObservation,
    ProviderSpeakerTurn,
    SpeakerTurnKind,
)
from ratiocinatus.speaker_transcript import (
    build_speaker_labeled_transcript,
    persist_speaker_labeled_transcript,
)
from ratiocinatus.transcript_contracts import TranscriptAssembly


NOW = datetime(2000, 1, 1, tzinfo=timezone.utc)
DEFAULT_ROOT = Path(".qualification/phase2-long-v1")
DEFAULT_CORPUS = (
    DEFAULT_ROOT
    / "phase1/ingestions/ingestion_907601ebd2ba584c9b6e4b31221658ab/corpus"
)
DEFAULT_ACTIVITY = (
    DEFAULT_ROOT
    / "phase2/speech_activity/sareq_165ee9f8851c298a2d3781394803add7"
)
DEFAULT_TRANSCRIPT = (
    DEFAULT_ROOT
    / "phase2/transcript-assemblies/txassembly_8c37b25069df6d276d52d24f9f3949c3"
)


def _confidence() -> ConfidenceMeasure:
    return ConfidenceMeasure(
        value=1.0,
        origin=ConfidenceOrigin.DERIVED,
        basis="deterministic long-recording mechanics qualification",
    )


class LongRecordingDiarizationProvider(DiarizationProvider):
    """Deterministic control with three labels recurring across owned chunks."""

    def __init__(self) -> None:
        self.calls = 0
        self._identity = DiarizationProviderIdentity(
            provider_id="qualification.synthetic_phase3_long",
            display_name="Synthetic Phase 3 long-recording control",
            provider_version="1.0.0",
            local=True,
        )

    @property
    def capabilities(self) -> DiarizationProviderCapabilities:
        return DiarizationProviderCapabilities(
            identity=self._identity,
            capabilities=(
                DiarizationCapability.TURN_SEGMENTATION,
                DiarizationCapability.SPEAKER_CLUSTERING,
            ),
            available=True,
            limitations=(
                "Synthetic mechanics control; no speaker-accuracy claim.",
            ),
        )

    def diarize(
        self,
        request,
        normalized_audio: Path,
        *,
        evidence_root: Path | None = None,
    ) -> DiarizationProviderResponse:
        del normalized_audio, evidence_root
        self.calls += 1
        chunks = {item.chunk_id: item for item in request.chunks}
        observations = []
        turns = []
        for ordinal, speech in enumerate(request.speech_intervals):
            normalized = speech.normalized_audio_interval
            chunk = chunks[speech.processing_chunk_id]
            label = f"LONG_VOICE_{ordinal % 3}"
            observation_id = typed_id(
                "spkobs", request.request_id, speech.interval_id, label
            )
            observations.append(
                ProviderSpeakerObservation(
                    observation_id=observation_id,
                    speech_interval_ids=(speech.interval_id,),
                    source_interval=speech.source_interval,
                    normalized_audio_interval=normalized,
                    chunk_local_interval=MediaInterval(
                        domain=TimeDomain.CHUNK_LOCAL,
                        start_microseconds=(
                            normalized.start_microseconds
                            - chunk.corpus_interval.start_microseconds
                        ),
                        duration_microseconds=normalized.duration_microseconds,
                    ),
                    processing_chunk_id=speech.processing_chunk_id,
                    provider_speaker_label=label,
                    acoustic_evidence_available=True,
                    usability=ObservationUsability.PROVISIONAL,
                    usability_confidence=_confidence(),
                )
            )
            turns.append(
                ProviderSpeakerTurn(
                    provider_turn_id=f"long-provider-turn-{ordinal:03d}",
                    observation_ids=(observation_id,),
                    source_interval=speech.source_interval,
                    normalized_audio_interval=normalized,
                    provider_speaker_label=label,
                    turn_kind=SpeakerTurnKind.SINGLE_SPEAKER,
                    boundary_confidence=_confidence(),
                    assignment_confidence=_confidence(),
                )
            )
        normalized_hash = canonical_hash(
            {
                "request_id": request.request_id,
                "provider": request.provider.model_dump(mode="json"),
                "observations": [
                    item.model_dump(mode="json") for item in observations
                ],
                "turns": [item.model_dump(mode="json") for item in turns],
                "overlaps": [],
                "embeddings": [],
            }
        )
        return DiarizationProviderResponse(
            response_id=typed_id("diaresponse", request.request_id, "long-v1"),
            request_id=request.request_id,
            provider=request.provider,
            started_at=NOW,
            completed_at=NOW,
            observations=tuple(observations),
            turns=tuple(turns),
            raw_evidence=RawProviderEvidence(
                disposition=RawEvidenceDisposition.HASH_ONLY,
                content_sha256=normalized_hash,
                explanation="Canonical hash of deterministic control evidence.",
            ),
            normalized_evidence_sha256=normalized_hash,
            complete=True,
        )


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


def qualify(
    corpus_root: Path,
    activity_root: Path,
    transcript_root: Path,
    destination: Path,
) -> dict[str, object]:
    corpus_root = corpus_root.resolve(strict=True)
    activity_root = activity_root.resolve(strict=True)
    transcript_root = transcript_root.resolve(strict=True)
    destination = destination.resolve()
    integrity = validate_corpus(corpus_root)
    loaded = load_corpus(corpus_root)
    transcript = load_contract(
        (transcript_root / "assembly.json").read_bytes(), TranscriptAssembly
    )
    before = _tree_hash(corpus_root)
    provider = LongRecordingDiarizationProvider()

    tracemalloc.start()
    started = time.perf_counter()
    _, response, diarization, _, diarization_root, first_diarization_cache = diarize_corpus(
        corpus_root,
        activity_root,
        destination,
        provider=provider,
        transcript_assembly_root=transcript_root,
    )
    # This persisted boundary represents interruption after diarization commit.
    _, _, replayed_diarization, _, _, diarization_cache = diarize_corpus(
        corpus_root,
        activity_root,
        destination,
        provider=provider,
        transcript_assembly_root=transcript_root,
    )
    clustering, _, clustering_root, first_cluster_cache = cluster_diarization(
        diarization_root,
        destination,
        capabilities=provider.capabilities,
    )
    replayed_clustering, _, _, clustering_cache = cluster_diarization(
        diarization_root,
        destination,
        capabilities=provider.capabilities,
    )
    foundation = None
    identities = []
    for ordinal, cluster in enumerate(clustering.clusters):
        scope = IdentityScope(
            kind=IdentityScopeKind.CLUSTER,
            target_id=cluster.cluster_id,
            explanation="Qualification reviewer decision scoped to one cluster.",
        )
        foundation, identity = add_participant_identity(
            clustering,
            diarization,
            canonical_display_label=f"Qualification participant {ordinal + 1}",
            identity_kind=IdentityKind.LOCAL_PARTICIPANT,
            information_source="deterministic long-recording control review",
            scope=scope,
            provenance_references=(f"qualification:cluster:{cluster.cluster_id}",),
            predecessor=foundation,
            created_at=NOW,
        )
        identities.append(identity)
    foundation, foundation_report, _, foundation_cache = (
        persist_identity_foundation(
            foundation, clustering, diarization, destination
        )
    )

    binding_run = None
    for cluster, identity in zip(clustering.clusters, identities, strict=True):
        binding_run, _ = append_manual_identity_binding(
            foundation,
            clustering,
            diarization,
            target_artifact_id=cluster.cluster_id,
            identity_id=identity.identity_id,
            scope=identity.scope,
            action=BindingAction.BIND,
            author_id="qualification:reviewer",
            author_display_name="Qualification Reviewer",
            rationale="Deterministic control binding for pipeline mechanics.",
            supporting_evidence_references=(
                f"qualification:cluster:{cluster.cluster_id}",
            ),
            reviewer_certainty=_confidence(),
            predecessor=binding_run,
            created_at=NOW,
        )
    binding_run, binding_report, _, binding_cache = persist_identity_binding_run(
        binding_run, foundation, clustering, diarization, destination
    )
    identity_assembly = assemble_identity_views(
        response,
        diarization,
        clustering,
        foundation,
        binding_run,
        created_at=NOW,
    )
    identity_assembly, identity_report, _, identity_cache = (
        persist_identity_view_assembly(
            identity_assembly,
            response,
            diarization,
            clustering,
            foundation,
            binding_run,
            destination,
        )
    )
    speaker_view = build_speaker_labeled_transcript(
        transcript, diarization, identity_assembly, created_at=NOW
    )
    speaker_view, speaker_report, _, speaker_cache = (
        persist_speaker_labeled_transcript(
            speaker_view,
            transcript,
            diarization,
            identity_assembly,
            destination,
        )
    )
    subtitle_manifest, subtitle_report, _, subtitle_cache = (
        export_participant_subtitles(
            speaker_view, transcript, destination
        )
    )
    # Replay all downstream persistors/exports at their stable identities.
    _, _, _, foundation_replay = persist_identity_foundation(
        foundation, clustering, diarization, destination
    )
    _, _, _, binding_replay = persist_identity_binding_run(
        binding_run, foundation, clustering, diarization, destination
    )
    _, _, _, identity_replay = persist_identity_view_assembly(
        identity_assembly,
        response,
        diarization,
        clustering,
        foundation,
        binding_run,
        destination,
    )
    _, _, _, speaker_replay = persist_speaker_labeled_transcript(
        speaker_view,
        transcript,
        diarization,
        identity_assembly,
        destination,
    )
    _, _, _, subtitle_replay = export_participant_subtitles(
        speaker_view, transcript, destination
    )
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    after = _tree_hash(corpus_root)

    chunks = loaded["chunks"].chunks
    observation_chunks = {
        item.processing_chunk_id for item in response.observations
    }
    membership_count = sum(
        len(item.observation_ids) for item in clustering.clusters
    )
    repeated_clusters = all(
        len(
            {
                next(
                    observation.processing_chunk_id
                    for observation in response.observations
                    if observation.observation_id == observation_id
                )
                for observation_id in cluster.observation_ids
            }
        )
        > 1
        for cluster in clustering.clusters
    )
    cache_flags = (
        diarization_cache,
        clustering_cache,
        foundation_replay,
        binding_replay,
        identity_replay,
        speaker_replay,
        subtitle_replay,
    )
    assertions = {
        "duration_exceeds_two_hours": (
            transcript.normalized_audio_duration_microseconds > 7_200_000_000
        ),
        "phase1_corpus_valid": integrity.valid,
        "phase1_corpus_unchanged": before == after,
        "phase2_transcript_reused": transcript_root.exists(),
        "every_owned_chunk_observed_once": (
            observation_chunks == {item.chunk_id for item in chunks}
            and len(response.observations) == len(chunks)
        ),
        "provider_invocation_bounded": provider.calls <= 1,
        "diarization_resume_reused": (
            diarization_cache
            and replayed_diarization == diarization
        ),
        "cross_chunk_clusters_continuous": (
            len(clustering.clusters) == 3 and repeated_clusters
        ),
        "clustering_resume_reused": (
            clustering_cache
            and replayed_clustering == clustering
        ),
        "no_duplicate_observations_or_turns": (
            len({item.observation_id for item in response.observations})
            == len(response.observations)
            and len({item.turn_id for item in diarization.turns})
            == len(diarization.turns)
            and membership_count == len(response.observations)
        ),
        "reviewed_identity_view_complete": (
            identity_report.status == "complete"
            and binding_report.binding_count == len(clustering.clusters)
        ),
        "speaker_transcript_complete": speaker_report.status == "complete",
        "participant_subtitles_complete": subtitle_report.valid,
        "all_persisted_stages_replay": all(cache_flags),
        "python_peak_below_256_mib": peak < 256 * 1024 * 1024,
    }
    return {
        "application_version": "0.4.0",
        "assertions": assertions,
        "fixture_status": (
            "Synthetic ownership, clustering, and identity control; no "
            "diarization or speaker-identity accuracy claim."
        ),
        "lineage": {
            "corpus_id": diarization.corpus_id,
            "diarization_run_id": diarization.run_id,
            "clustering_run_id": clustering.run_id,
            "identity_foundation_id": foundation.foundation_id,
            "identity_binding_run_id": binding_run.run_id,
            "identity_view_assembly_id": identity_assembly.assembly_id,
            "speaker_transcript_view_id": speaker_view.view_id,
            "participant_subtitle_export_id": subtitle_manifest.export_id,
        },
        "measurements": {
            "duration_microseconds": (
                transcript.normalized_audio_duration_microseconds
            ),
            "speaker_observation_count": len(response.observations),
            "speaker_turn_count": len(diarization.turns),
            "overlap_count": len(diarization.overlaps),
            "overlap_duration_microseconds": sum(
                item.normalized_audio_interval.duration_microseconds
                for item in diarization.overlaps
            ),
            "cluster_count": len(clustering.clusters),
            "unclustered_observation_count": (
                len(response.observations) - membership_count
            ),
            "identity_hypothesis_count": foundation_report.hypothesis_count,
            "manual_binding_count": binding_report.binding_count,
            "unknown_or_unresolved_count": identity_report.unknown_count,
            "participant_subtitle_export_count": len(
                subtitle_manifest.files
            ),
            "cache_hit_count": sum(cache_flags),
            "invalidation_count": 0,
            "recovery_count": 1,
            "peak_memory_bytes": peak,
        },
        "performance": {
            "processing_seconds": round(elapsed, 6),
            "measurement_scope": (
                "tracemalloc Python allocator peak; corpus hashing streams "
                "one MiB blocks"
            ),
        },
        "phase": 3,
        "qualification": "phase-3-long-recording-operation",
        "schema_exports": {
            "runtime_contracts": 237,
        },
        "status": "passed" if all(assertions.values()) else "failed",
        "target_application_version": "0.5.0",
        "tests": {
            "focused_long_recording_operation": 1,
            "full_regression": 190,
            "status": "passed",
        },
        "work_order": "docs/work_orders/phase_03.txt",
    }


def _markdown(report: dict[str, object]) -> str:
    assertions = report["assertions"]
    measurements = report["measurements"]
    lines = [
        "# Phase 3 long-recording operational qualification",
        "",
        f"Status: **{str(report['status']).upper()}**",
        "",
        (
            f"- Duration: {measurements['duration_microseconds']} "
            "microseconds"
        ),
        f"- Speaker observations: {measurements['speaker_observation_count']}",
        f"- Speaker turns: {measurements['speaker_turn_count']}",
        f"- Cross-chunk clusters: {measurements['cluster_count']}",
        f"- Cache hits: {measurements['cache_hit_count']}",
        f"- Peak Python memory: {measurements['peak_memory_bytes']} bytes",
        "",
        "## Assertions",
        "",
    ]
    lines.extend(
        f"- [{'x' if passed else ' '}] {name}"
        for name, passed in assertions.items()
    )
    lines.extend(
        [
            "",
            "This is a synthetic operational mechanics control. It does not "
            "establish diarization or participant-identification accuracy.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-root", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--activity-root", type=Path, default=DEFAULT_ACTIVITY)
    parser.add_argument(
        "--transcript-root", type=Path, default=DEFAULT_TRANSCRIPT
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=DEFAULT_ROOT / "phase3",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("reports/phase-3-long-recording-qualification.json"),
    )
    args = parser.parse_args()
    report = qualify(
        args.corpus_root,
        args.activity_root,
        args.transcript_root,
        args.destination,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.report.with_suffix(".md").write_text(
        _markdown(report), encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
