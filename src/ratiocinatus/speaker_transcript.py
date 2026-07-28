"""Speaker-labeled transcript views derived without rewriting Phase 2."""

from __future__ import annotations

import os
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .addressing_contracts import MediaInterval, TimeDomain
from .correction_contracts import (
    TranscriptRevision,
    TranscriptSegmentState,
    TranscriptViewKind,
)
from .corrections import validate_transcript_revision
from .identity_view import reviewed_identity_view
from .identity_view_contracts import (
    IdentityViewAssembly,
    IdentityViewDisposition,
)
from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .phase3_contracts import DiarizationRun, SpeakerTurn
from .speaker_transcript_contracts import (
    SpeakerAttributionKind,
    SpeakerAttributionSpan,
    SpeakerLabeledTranscriptPolicy,
    SpeakerLabeledTranscriptReport,
    SpeakerLabeledTranscriptSegment,
    SpeakerLabeledTranscriptView,
)
from .transcript_assembly import validate_transcript_assembly
from .transcript_contracts import TranscriptAssembly


class SpeakerTranscriptIntegrityError(RuntimeError):
    """Speaker-labeled transcript lineage or derived content is invalid."""


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


def _integrity_payload(item) -> dict:
    payload = item.model_dump(mode="json")
    payload.pop("integrity_sha256", None)
    return payload


def _end(interval: MediaInterval) -> int:
    return interval.start_microseconds + interval.duration_microseconds


def _intersects(interval: MediaInterval, start: int, end: int) -> bool:
    return interval.start_microseconds < end and start < _end(interval)


def _original_states(
    assembly: TranscriptAssembly,
) -> tuple[TranscriptSegmentState, ...]:
    words: dict[str, list[str]] = {}
    for word in assembly.words:
        words.setdefault(word.segment_id, []).append(word.word_id)
    return tuple(
        TranscriptSegmentState(
            artifact_id=item.segment_id,
            source_interval=item.source_interval,
            normalized_audio_interval=item.normalized_audio_interval,
            text=item.proposed_text,
            normalized_text=item.normalized_text,
            language_claim=item.language_claim,
            origin_segment_ids=(item.segment_id,),
            retained_word_ids=tuple(words.get(item.segment_id, ())),
        )
        for item in assembly.segments
    )


def _source_view(
    assembly: TranscriptAssembly,
    policy: SpeakerLabeledTranscriptPolicy,
    revision: TranscriptRevision | None,
) -> tuple[
    str,
    str | None,
    tuple[TranscriptSegmentState, ...],
]:
    validate_transcript_assembly(assembly)
    if policy.transcript_view_kind == TranscriptViewKind.ORIGINAL_MACHINE:
        if revision is not None:
            validate_transcript_revision(revision, assembly=assembly)
        return assembly.version.version_id, None, _original_states(assembly)
    if revision is None:
        raise SpeakerTranscriptIntegrityError(
            "corrected speaker transcript requires a transcript revision"
        )
    validate_transcript_revision(revision, assembly=assembly)
    return (
        revision.version.version_id,
        revision.revision_id,
        revision.current_corrected_view.segments,
    )


def _active_turns(
    turns: tuple[SpeakerTurn, ...],
    start: int,
    end: int,
) -> tuple[SpeakerTurn, ...]:
    return tuple(
        item
        for item in turns
        if _intersects(item.normalized_audio_interval, start, end)
    )


def _attribution(
    turns: tuple[SpeakerTurn, ...],
    reviewed_entries: dict[str, object],
    policy: SpeakerLabeledTranscriptPolicy,
) -> tuple[
    SpeakerAttributionKind,
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
]:
    if not turns:
        return (
            SpeakerAttributionKind.UNATTRIBUTED,
            (),
            (),
            (),
            (),
            ("No canonical speaker turn covers this interval.",),
        )
    entries = tuple(reviewed_entries[item.turn_id] for item in turns)
    dispositions = {item.disposition for item in entries}
    machine_labels = tuple(
        sorted(
            {
                policy.machine_label_prefix + item.original_machine_label
                for item in entries
                if item.original_machine_label
                and item.original_machine_label != "MACHINE: UNRESOLVED"
            }
        )
    )
    reviewed_labels = tuple(
        sorted(
            {
                item.reviewed_label
                for item in entries
                if item.reviewed_label is not None
            }
        )
    )
    identity_ids = tuple(
        sorted({identity for item in entries for identity in item.identity_ids})
    )
    entry_ids = tuple(sorted(item.entry_id for item in entries))
    if IdentityViewDisposition.CONFLICTED in dispositions:
        kind = SpeakerAttributionKind.CONFLICTED
        findings = ("Conflicting reviewed identity assignments apply.",)
    elif len(identity_ids) > 1 or len(reviewed_labels) > 1:
        kind = SpeakerAttributionKind.MULTIPLE_CANDIDATES
        findings = (
            "Multiple candidate speakers are retained for this interval.",
        )
    elif IdentityViewDisposition.REVIEWED_IDENTITY in dispositions:
        kind = SpeakerAttributionKind.REVIEWED
        findings = ()
    elif dispositions & {
        IdentityViewDisposition.UNKNOWN,
        IdentityViewDisposition.REJECTED,
    }:
        kind = SpeakerAttributionKind.UNKNOWN
        findings = ("Speaker identity remains explicitly unknown.",)
    elif machine_labels:
        kind = SpeakerAttributionKind.MACHINE_CLUSTER
        findings = ("Only a machine cluster label is available.",)
    else:
        kind = SpeakerAttributionKind.UNKNOWN
        findings = ("No participant identity or usable cluster label is available.",)
    return (
        kind,
        machine_labels,
        reviewed_labels,
        identity_ids,
        entry_ids,
        findings,
    )


def _span_label(
    kind: SpeakerAttributionKind,
    machine_labels: tuple[str, ...],
    reviewed_labels: tuple[str, ...],
    policy: SpeakerLabeledTranscriptPolicy,
) -> str:
    if kind == SpeakerAttributionKind.UNATTRIBUTED:
        return policy.unattributed_label
    if reviewed_labels:
        return policy.multiple_candidate_separator.join(reviewed_labels)
    if machine_labels:
        return policy.multiple_candidate_separator.join(machine_labels)
    return "REVIEWED: UNKNOWN"


def _build_segments(
    source_segments: tuple[TranscriptSegmentState, ...],
    assembly: TranscriptAssembly,
    diarization: DiarizationRun,
    identity_assembly: IdentityViewAssembly,
    policy: SpeakerLabeledTranscriptPolicy,
) -> tuple[
    tuple[SpeakerLabeledTranscriptSegment, ...],
    tuple[str, ...],
]:
    reviewed = reviewed_identity_view(identity_assembly)
    reviewed_entries = {
        item.target_artifact_id: item for item in reviewed.entries
    }
    if set(reviewed_entries) != {
        item.turn_id for item in diarization.turns
    }:
        raise SpeakerTranscriptIntegrityError(
            "reviewed identity view does not cover canonical speaker turns"
        )
    words = {item.word_id: item for item in assembly.words}
    segments: list[SpeakerLabeledTranscriptSegment] = []
    blocking = list(reviewed.blocking_findings)
    for segment in source_segments:
        normalized = segment.normalized_audio_interval
        segment_start = normalized.start_microseconds
        segment_end = _end(normalized)
        relevant_turns = tuple(
            item
            for item in diarization.turns
            if _intersects(item.normalized_audio_interval, segment_start, segment_end)
        )
        boundaries = {segment_start, segment_end}
        for turn in relevant_turns:
            boundaries.add(max(segment_start, turn.normalized_audio_interval.start_microseconds))
            boundaries.add(min(segment_end, _end(turn.normalized_audio_interval)))
        ordered = sorted(boundaries)
        spans: list[SpeakerAttributionSpan] = []
        labels: list[str] = []
        source_offset = (
            segment.source_interval.start_microseconds - segment_start
        )
        for start, end in zip(ordered, ordered[1:]):
            active = _active_turns(relevant_turns, start, end)
            (
                kind,
                machine_labels,
                reviewed_labels,
                identity_ids,
                entry_ids,
                findings,
            ) = _attribution(active, reviewed_entries, policy)
            overlap_disclosed = len(active) > 1
            if kind == SpeakerAttributionKind.CONFLICTED:
                blocking.append(
                    f"Transcript segment {segment.artifact_id} contains "
                    "conflicting participant attribution."
                )
            word_ids = tuple(
                word_id
                for word_id in segment.retained_word_ids
                if word_id in words
                and _intersects(
                    words[word_id].normalized_audio_interval,
                    start,
                    end,
                )
            )
            label = _span_label(
                kind, machine_labels, reviewed_labels, policy
            )
            if overlap_disclosed:
                label = "OVERLAP: " + label
            labels.append(label)
            span_payload = {
                "source_interval": MediaInterval(
                    domain=TimeDomain.SOURCE_MEDIA,
                    start_microseconds=start + source_offset,
                    duration_microseconds=end - start,
                ),
                "normalized_audio_interval": MediaInterval(
                    domain=TimeDomain.NORMALIZED_CORPUS,
                    start_microseconds=start,
                    duration_microseconds=end - start,
                ),
                "speaker_turn_ids": tuple(item.turn_id for item in active),
                "transcript_segment_ids": (
                    segment.origin_segment_ids
                    or (segment.artifact_id,)
                ),
                "transcript_word_ids": word_ids,
                "attribution_kind": kind,
                "original_machine_labels": machine_labels,
                "reviewed_labels": reviewed_labels,
                "identity_ids": identity_ids,
                "identity_view_entry_ids": entry_ids,
                "overlap_disclosed": overlap_disclosed,
                "findings": findings,
            }
            provisional_span = SpeakerAttributionSpan(
                span_id="speakerattrspan_" + "0" * 32,
                **span_payload,
            )
            spans.append(
                provisional_span.model_copy(
                    update={
                        "span_id": typed_id(
                        "speakerattrspan",
                        identity_assembly.assembly_id,
                        segment.artifact_id,
                            provisional_span.model_dump(
                                mode="json", exclude={"span_id"}
                            ),
                        )
                    }
                )
            )
        rendered_labels = " | ".join(
            dict.fromkeys(f"[{item}]" for item in labels)
        )
        segments.append(
            SpeakerLabeledTranscriptSegment(
                segment_id=segment.artifact_id,
                source_interval=segment.source_interval,
                normalized_audio_interval=normalized,
                source_text=segment.text,
                normalized_text=segment.normalized_text,
                attribution_spans=tuple(spans),
                rendered_text=f"{rendered_labels} {segment.text}".strip(),
            )
        )
    return tuple(segments), tuple(sorted(set(blocking)))


def build_speaker_labeled_transcript(
    assembly: TranscriptAssembly,
    diarization: DiarizationRun,
    identity_assembly: IdentityViewAssembly,
    *,
    revision: TranscriptRevision | None = None,
    policy: SpeakerLabeledTranscriptPolicy | None = None,
    created_at: datetime | None = None,
) -> SpeakerLabeledTranscriptView:
    selected_policy = policy or SpeakerLabeledTranscriptPolicy()
    version_id, revision_id, source_segments = _source_view(
        assembly, selected_policy, revision
    )
    if (
        assembly.version.corpus_id != diarization.corpus_id
        or identity_assembly.corpus_id != diarization.corpus_id
        or identity_assembly.diarization_run_id != diarization.run_id
    ):
        raise SpeakerTranscriptIntegrityError(
            "transcript, diarization, and identity-view lineage disagree"
        )
    if canonical_hash(_integrity_payload(identity_assembly)) != (
        identity_assembly.integrity_sha256
    ):
        raise SpeakerTranscriptIntegrityError(
            "identity-view assembly integrity is invalid"
        )
    segments, blocking = _build_segments(
        source_segments,
        assembly,
        diarization,
        identity_assembly,
        selected_policy,
    )
    timestamp = created_at or datetime.now(timezone.utc)
    configuration_hash = canonical_hash(
        {
            "operation": "participant.speaker_labeled_transcript",
            "source_assembly_id": assembly.assembly_id,
            "source_version_id": version_id,
            "source_revision_id": revision_id,
            "identity_view_assembly_id": identity_assembly.assembly_id,
            "reviewed_identity_view_id": reviewed_identity_view(
                identity_assembly
            ).view_id,
            "diarization_run_id": diarization.run_id,
            "policy": selected_policy.model_dump(mode="json"),
        }
    )
    payload = {
        "view_id": typed_id(
            "speakertranscript",
            configuration_hash,
            [item.model_dump(mode="json") for item in segments],
        ),
        "source_assembly_id": assembly.assembly_id,
        "source_transcript_version_id": version_id,
        "source_transcript_view_kind": selected_policy.transcript_view_kind,
        "source_revision_id": revision_id,
        "identity_view_assembly_id": identity_assembly.assembly_id,
        "reviewed_identity_view_id": reviewed_identity_view(
            identity_assembly
        ).view_id,
        "diarization_run_id": diarization.run_id,
        "corpus_id": diarization.corpus_id,
        "policy": selected_policy,
        "configuration_hash": configuration_hash,
        "segments": segments,
        "rendered_text": "\n".join(item.rendered_text for item in segments),
        "trusted_for_participant_rendering": not blocking,
        "blocking_findings": blocking,
        "created_at": timestamp,
    }
    view = _seal(SpeakerLabeledTranscriptView, payload)
    validate_speaker_labeled_transcript(
        view,
        assembly,
        diarization,
        identity_assembly,
        revision=revision,
    )
    return view


def _report(view: SpeakerLabeledTranscriptView) -> SpeakerLabeledTranscriptReport:
    spans = tuple(
        span for segment in view.segments for span in segment.attribution_spans
    )
    counts = Counter(item.attribution_kind for item in spans)
    status = (
        "blocked"
        if view.blocking_findings
        else "warning"
        if counts[SpeakerAttributionKind.UNKNOWN]
        or counts[SpeakerAttributionKind.UNATTRIBUTED]
        or counts[SpeakerAttributionKind.MULTIPLE_CANDIDATES]
        else "complete"
    )
    return _seal(
        SpeakerLabeledTranscriptReport,
        {
            "report_id": typed_id("speakertranscriptreport", view.view_id),
            "view_id": view.view_id,
            "generated_at": view.created_at,
            "segment_count": len(view.segments),
            "attribution_span_count": len(spans),
            "reviewed_span_count": counts[SpeakerAttributionKind.REVIEWED],
            "machine_span_count": counts[
                SpeakerAttributionKind.MACHINE_CLUSTER
            ],
            "unknown_span_count": counts[SpeakerAttributionKind.UNKNOWN],
            "unattributed_span_count": counts[
                SpeakerAttributionKind.UNATTRIBUTED
            ],
            "multiple_candidate_span_count": counts[
                SpeakerAttributionKind.MULTIPLE_CANDIDATES
            ],
            "conflict_span_count": counts[
                SpeakerAttributionKind.CONFLICTED
            ],
            "overlap_disclosure_count": sum(
                item.overlap_disclosed for item in spans
            ),
            "findings": (
                "Speaker attribution is a presentation view over immutable transcript text.",
                "Transcript segments are preserved with temporal attribution spans.",
            ),
            "limitations": (
                "Attribution boundaries use normalized-time intersection.",
                "Participant subtitles are separate loss-declared derivatives.",
            ),
            "status": status,
        },
    )


def validate_speaker_labeled_transcript(
    view: SpeakerLabeledTranscriptView,
    assembly: TranscriptAssembly,
    diarization: DiarizationRun,
    identity_assembly: IdentityViewAssembly,
    *,
    revision: TranscriptRevision | None = None,
    report: SpeakerLabeledTranscriptReport | None = None,
) -> None:
    if canonical_hash(_integrity_payload(view)) != view.integrity_sha256:
        raise SpeakerTranscriptIntegrityError(
            "speaker-labeled transcript integrity is invalid"
        )
    version_id, revision_id, source_segments = _source_view(
        assembly, view.policy, revision
    )
    reviewed = reviewed_identity_view(identity_assembly)
    if (
        view.source_assembly_id != assembly.assembly_id
        or view.source_transcript_version_id != version_id
        or view.source_revision_id != revision_id
        or view.identity_view_assembly_id != identity_assembly.assembly_id
        or view.reviewed_identity_view_id != reviewed.view_id
        or view.diarization_run_id != diarization.run_id
        or view.corpus_id != diarization.corpus_id
        or assembly.version.corpus_id != diarization.corpus_id
        or identity_assembly.diarization_run_id != diarization.run_id
    ):
        raise SpeakerTranscriptIntegrityError(
            "speaker-labeled transcript lineage is incompatible"
        )
    if canonical_hash(_integrity_payload(identity_assembly)) != (
        identity_assembly.integrity_sha256
    ):
        raise SpeakerTranscriptIntegrityError(
            "identity-view assembly integrity is invalid"
        )
    expected_segments, expected_blocking = _build_segments(
        source_segments,
        assembly,
        diarization,
        identity_assembly,
        view.policy,
    )
    if (
        view.segments != expected_segments
        or view.rendered_text
        != "\n".join(item.rendered_text for item in expected_segments)
        or view.blocking_findings != expected_blocking
        or view.trusted_for_participant_rendering != (not expected_blocking)
    ):
        raise SpeakerTranscriptIntegrityError(
            "speaker-labeled transcript is not the derived source view"
        )
    if report is not None and (
        canonical_hash(_integrity_payload(report)) != report.integrity_sha256
        or report != _report(view)
    ):
        raise SpeakerTranscriptIntegrityError(
            "speaker transcript report integrity or projection is invalid"
        )


def speaker_transcript_report_markdown(
    report: SpeakerLabeledTranscriptReport,
) -> str:
    return (
        "# Phase 3 speaker-labeled transcript report\n\n"
        f"- View: `{report.view_id}`\n"
        f"- Segments: {report.segment_count}\n"
        f"- Attribution spans: {report.attribution_span_count}\n"
        f"- Reviewed spans: {report.reviewed_span_count}\n"
        f"- Unknown spans: {report.unknown_span_count}\n"
        f"- Conflicts: {report.conflict_span_count}\n"
        f"- Status: {report.status}\n"
    )


def persist_speaker_labeled_transcript(
    view: SpeakerLabeledTranscriptView,
    assembly: TranscriptAssembly,
    diarization: DiarizationRun,
    identity_assembly: IdentityViewAssembly,
    destination: Path,
    *,
    revision: TranscriptRevision | None = None,
) -> tuple[
    SpeakerLabeledTranscriptView,
    SpeakerLabeledTranscriptReport,
    Path,
    bool,
]:
    destination = destination.expanduser().resolve()
    validate_speaker_labeled_transcript(
        view,
        assembly,
        diarization,
        identity_assembly,
        revision=revision,
    )
    root = destination / "speaker-transcripts" / view.view_id
    view_path = root / "view.json"
    report_path = root / "report.json"
    text_path = root / "transcript.txt"
    existing = (
        view_path.exists(),
        report_path.exists(),
        text_path.exists(),
    )
    if any(existing) and not all(existing):
        raise SpeakerTranscriptIntegrityError(
            "cached speaker transcript is incomplete"
        )
    expected_report = _report(view)
    if all(existing):
        stored = load_contract(
            view_path.read_bytes(), SpeakerLabeledTranscriptView
        )
        report = load_contract(
            report_path.read_bytes(), SpeakerLabeledTranscriptReport
        )
        validate_speaker_labeled_transcript(
            stored,
            assembly,
            diarization,
            identity_assembly,
            revision=revision,
            report=report,
        )
        if (
            stored != view
            or text_path.read_text(encoding="utf-8") != view.rendered_text
        ):
            raise SpeakerTranscriptIntegrityError(
                "cached speaker transcript is incompatible"
            )
        return stored, report, root, True
    _atomic(view_path, canonical_bytes(view))
    _atomic(report_path, canonical_bytes(expected_report))
    _atomic(text_path, view.rendered_text.encode("utf-8"))
    _atomic(
        root / "report.md",
        speaker_transcript_report_markdown(expected_report).encode("utf-8"),
    )
    return view, expected_report, root, False


def load_speaker_labeled_transcript(
    root: Path,
) -> tuple[SpeakerLabeledTranscriptView, SpeakerLabeledTranscriptReport]:
    root = root.expanduser().resolve(strict=True)
    return (
        load_contract(
            (root / "view.json").read_bytes(), SpeakerLabeledTranscriptView
        ),
        load_contract(
            (root / "report.json").read_bytes(),
            SpeakerLabeledTranscriptReport,
        ),
    )
