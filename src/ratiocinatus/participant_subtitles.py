"""Participant-labeled WebVTT and SRT presentation derivatives."""

from __future__ import annotations

import hashlib
import os
import uuid
from collections import Counter
from pathlib import Path

from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .participant_subtitle_contracts import (
    ParticipantSubtitleCue,
    ParticipantSubtitleManifest,
    ParticipantSubtitlePolicy,
    ParticipantSubtitleReport,
)
from .speaker_transcript import (
    validate_speaker_labeled_transcript,
)
from .speaker_transcript_contracts import (
    SpeakerAttributionKind,
    SpeakerLabeledTranscriptSegment,
    SpeakerLabeledTranscriptView,
)
from .subtitle_contracts import (
    SubtitleExportFile,
    SubtitleFormat,
    SubtitleLossClassification,
    SubtitleLossRecord,
)
from .transcript_assembly import validate_transcript_assembly
from .transcript_contracts import TranscriptAssembly


class ParticipantSubtitleIntegrityError(RuntimeError):
    """Participant subtitle lineage or deterministic rendering is invalid."""


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


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _timestamp(milliseconds: int, separator: str) -> str:
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return (
        f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        f"{separator}{millis:03d}"
    )


def _round(
    start: int,
    end: int,
    policy: ParticipantSubtitlePolicy,
) -> tuple[int, int]:
    rounding = policy.subtitle_policy.rounding
    resolution = rounding.resolution_microseconds
    start_ms = start // resolution
    end_ms = (end + resolution - 1) // resolution
    end_ms = max(
        end_ms,
        start_ms + rounding.minimum_rounded_duration_milliseconds,
    )
    return start_ms, end_ms


def _body_lines(
    text: str,
    policy: ParticipantSubtitlePolicy,
) -> tuple[str, ...]:
    words = text.split()
    if not words:
        raise ParticipantSubtitleIntegrityError(
            "participant subtitle cue text is empty"
        )
    lines: list[str] = []
    current = ""
    maximum = policy.subtitle_policy.maximum_line_characters
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > maximum:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return tuple(lines)


def _cue_label(
    segment: SpeakerLabeledTranscriptSegment,
    policy: ParticipantSubtitlePolicy,
) -> str:
    labels: list[str] = []
    for span in segment.attribution_spans:
        if span.attribution_kind == SpeakerAttributionKind.CONFLICTED:
            raise ParticipantSubtitleIntegrityError(
                "conflicting speaker attribution blocks participant subtitles"
            )
        if span.reviewed_labels:
            labels.extend(span.reviewed_labels)
        elif span.original_machine_labels:
            labels.extend(span.original_machine_labels)
        elif span.attribution_kind == SpeakerAttributionKind.UNATTRIBUTED:
            labels.append(policy.unattributed_label)
        else:
            labels.append(policy.unknown_label)
    combined = " | ".join(dict.fromkeys(labels))
    if any(item.overlap_disclosed for item in segment.attribution_spans):
        combined = policy.overlap_label_prefix + combined
    return combined


def _loss(
    export_id: str,
    classification: SubtitleLossClassification,
    explanation: str,
) -> SubtitleLossRecord:
    return SubtitleLossRecord(
        loss_id=typed_id(
            "subtitleloss",
            export_id,
            classification.value,
            explanation,
        ),
        classification=classification,
        explanation=explanation,
    )


def _build_cues(
    view: SpeakerLabeledTranscriptView,
    export_id: str,
    policy: ParticipantSubtitlePolicy,
) -> tuple[
    tuple[ParticipantSubtitleCue, ...],
    tuple[SubtitleLossRecord, ...],
]:
    cues: list[ParticipantSubtitleCue] = []
    losses: list[SubtitleLossRecord] = []
    for segment in view.segments:
        start = segment.normalized_audio_interval.start_microseconds
        end = (
            start + segment.normalized_audio_interval.duration_microseconds
        )
        start_ms, end_ms = _round(start, end, policy)
        label = _cue_label(segment, policy)
        body = _body_lines(segment.normalized_text, policy)
        kinds = tuple(
            dict.fromkeys(
                item.attribution_kind for item in segment.attribution_spans
            )
        )
        unresolved = any(
            item
            in {
                SpeakerAttributionKind.UNKNOWN,
                SpeakerAttributionKind.UNATTRIBUTED,
                SpeakerAttributionKind.MULTIPLE_CANDIDATES,
            }
            for item in kinds
        )
        cue_payload = {
            "sequence_position": len(cues),
            "source_interval": segment.source_interval,
            "normalized_audio_interval": segment.normalized_audio_interval,
            "rounded_start_milliseconds": start_ms,
            "rounded_end_milliseconds": end_ms,
            "speaker_label": label,
            "text": segment.normalized_text,
            "rendered_lines": (label, *body),
            "source_segment_ids": (segment.segment_id,),
            "attribution_span_ids": tuple(
                item.span_id for item in segment.attribution_spans
            ),
            "identity_ids": tuple(
                dict.fromkeys(
                    identity
                    for item in segment.attribution_spans
                    for identity in item.identity_ids
                )
            ),
            "identity_view_entry_ids": tuple(
                dict.fromkeys(
                    entry
                    for item in segment.attribution_spans
                    for entry in item.identity_view_entry_ids
                )
            ),
            "attribution_kinds": kinds,
            "unresolved": unresolved,
            "overlap_disclosed": any(
                item.overlap_disclosed
                for item in segment.attribution_spans
            ),
            "findings": tuple(
                dict.fromkeys(
                    finding
                    for item in segment.attribution_spans
                    for finding in item.findings
                )
            ),
        }
        provisional = ParticipantSubtitleCue(
            cue_id="participantcue_" + "0" * 32,
            **cue_payload,
        )
        cues.append(
            provisional.model_copy(
                update={
                    "cue_id": typed_id(
                        "participantcue",
                        export_id,
                        provisional.model_dump(
                            mode="json", exclude={"cue_id"}
                        ),
                    )
                }
            )
        )
        if start_ms * 1000 != start or end_ms * 1000 != end:
            losses.append(
                _loss(
                    export_id,
                    SubtitleLossClassification.MILLISECOND_TIMESTAMP_ROUNDING,
                    "Microsecond cue boundaries were rounded outward to milliseconds.",
                )
            )
        if segment.source_text != segment.normalized_text:
            losses.append(
                _loss(
                    export_id,
                    SubtitleLossClassification.NORMALIZED_TEXT_RENDERING,
                    "Subtitle text uses the declared normalized transcript form.",
                )
            )
        if len(segment.attribution_spans) > 1:
            losses.append(
                _loss(
                    export_id,
                    SubtitleLossClassification.FORMAT_METADATA_IN_COMPANION_MANIFEST,
                    "Multiple attribution spans are represented by combined cue labels; see manifest.json.",
                )
            )
        if (
            len(body) + 1
            > policy.subtitle_policy.maximum_lines_per_cue
            or len(label)
            > policy.subtitle_policy.maximum_line_characters
        ):
            losses.append(
                _loss(
                    export_id,
                    SubtitleLossClassification.LINE_LENGTH_EXCEEDED,
                    "Participant label or transcript body exceeds configured line capacity and was retained.",
                )
            )
        if (
            len(segment.normalized_text)
            > policy.subtitle_policy.maximum_cue_characters
            or segment.normalized_audio_interval.duration_microseconds
            > policy.subtitle_policy.maximum_cue_duration_microseconds
        ):
            losses.append(
                _loss(
                    export_id,
                    SubtitleLossClassification.LONG_CUE_RETAINED,
                    "Long participant cue was retained because safe text-to-attribution splitting was unavailable.",
                )
            )
    unique_losses = {
        item.loss_id: item for item in losses
    }
    return tuple(cues), tuple(unique_losses.values())


def render_participant_webvtt(
    manifest_id: str,
    speaker_view_id: str,
    identity_view_id: str,
    cues: tuple[ParticipantSubtitleCue, ...],
) -> bytes:
    lines = [
        "WEBVTT",
        "",
        f"NOTE Ratiocinatus participant subtitle {manifest_id}",
        f"NOTE Speaker transcript {speaker_view_id}",
        f"NOTE Reviewed identity view {identity_view_id}",
        "NOTE Complete evidentiary metadata: manifest.json",
        "",
    ]
    for cue in cues:
        lines.extend(
            (
                cue.cue_id,
                (
                    f"{_timestamp(cue.rounded_start_milliseconds, '.')} --> "
                    f"{_timestamp(cue.rounded_end_milliseconds, '.')}"
                ),
                *cue.rendered_lines,
                "",
            )
        )
    return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


def render_participant_srt(
    cues: tuple[ParticipantSubtitleCue, ...],
) -> bytes:
    lines: list[str] = []
    for ordinal, cue in enumerate(cues, start=1):
        lines.extend(
            (
                str(ordinal),
                (
                    f"{_timestamp(cue.rounded_start_milliseconds, ',')} --> "
                    f"{_timestamp(cue.rounded_end_milliseconds, ',')}"
                ),
                *cue.rendered_lines,
                "",
            )
        )
    return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


def _rendered_files(
    export_id: str,
    speaker_view_id: str,
    identity_view_id: str,
    cues: tuple[ParticipantSubtitleCue, ...],
    policy: ParticipantSubtitlePolicy,
) -> tuple[tuple[SubtitleExportFile, ...], dict[str, bytes]]:
    rendered: dict[str, bytes] = {}
    references: list[SubtitleExportFile] = []
    for subtitle_format in policy.subtitle_policy.formats:
        if subtitle_format == SubtitleFormat.WEBVTT:
            relative = "participant-transcript.vtt"
            media_type = "text/vtt"
            data = render_participant_webvtt(
                export_id, speaker_view_id, identity_view_id, cues
            )
        else:
            relative = "participant-transcript.srt"
            media_type = "application/x-subrip"
            data = render_participant_srt(cues)
        rendered[relative] = data
        references.append(
            SubtitleExportFile(
                subtitle_format=subtitle_format,
                relative_path=relative,
                media_type=media_type,
                content_sha256=_sha256(data),
                byte_size=len(data),
            )
        )
    return tuple(references), rendered


def _report(
    manifest: ParticipantSubtitleManifest,
) -> ParticipantSubtitleReport:
    kinds = Counter(
        kind for cue in manifest.cues for kind in cue.attribution_kinds
    )
    return _seal(
        ParticipantSubtitleReport,
        {
            "report_id": typed_id(
                "participantsubtitlereport", manifest.export_id
            ),
            "export_id": manifest.export_id,
            "generated_at": manifest.generated_at,
            "cue_count": len(manifest.cues),
            "reviewed_cue_count": sum(
                SpeakerAttributionKind.REVIEWED in item.attribution_kinds
                for item in manifest.cues
            ),
            "machine_cue_count": sum(
                SpeakerAttributionKind.MACHINE_CLUSTER
                in item.attribution_kinds
                for item in manifest.cues
            ),
            "unresolved_cue_count": sum(
                item.unresolved for item in manifest.cues
            ),
            "unattributed_cue_count": sum(
                SpeakerAttributionKind.UNATTRIBUTED
                in item.attribution_kinds
                for item in manifest.cues
            ),
            "multiple_candidate_cue_count": sum(
                SpeakerAttributionKind.MULTIPLE_CANDIDATES
                in item.attribution_kinds
                for item in manifest.cues
            ),
            "overlap_disclosure_count": sum(
                item.overlap_disclosed for item in manifest.cues
            ),
            "loss_record_count": len(manifest.losses),
            "checked_formats": tuple(
                item.subtitle_format.value for item in manifest.files
            ),
            "findings": (
                "Participant labels are presentation metadata over a pinned speaker transcript.",
                "Unknown, unattributed, multiple-candidate, and overlap states remain explicit.",
            ),
            "limitations": (
                "WebVTT and SRT cannot carry the complete evidentiary graph; see manifest.json.",
                "This derivative is not an authoritative identity record.",
            ),
            "status": manifest.status,
            "valid": True,
        },
    )


def export_participant_subtitles(
    speaker_view: SpeakerLabeledTranscriptView,
    assembly: TranscriptAssembly,
    destination: Path,
    *,
    policy: ParticipantSubtitlePolicy | None = None,
) -> tuple[
    ParticipantSubtitleManifest,
    ParticipantSubtitleReport,
    Path,
    bool,
]:
    selected_policy = policy or ParticipantSubtitlePolicy()
    if (
        not speaker_view.trusted_for_participant_rendering
        or speaker_view.blocking_findings
        or any(
            span.attribution_kind
            == SpeakerAttributionKind.CONFLICTED
            for segment in speaker_view.segments
            for span in segment.attribution_spans
        )
    ):
        raise ParticipantSubtitleIntegrityError(
            "conflicting or blocked speaker attribution refuses participant subtitles"
        )
    validate_transcript_assembly(assembly)
    if canonical_hash(_integrity_payload(speaker_view)) != (
        speaker_view.integrity_sha256
    ):
        raise ParticipantSubtitleIntegrityError(
            "speaker transcript integrity is invalid"
        )
    if (
        speaker_view.source_assembly_id != assembly.assembly_id
        or speaker_view.corpus_id != assembly.version.corpus_id
    ):
        raise ParticipantSubtitleIntegrityError(
            "speaker transcript and source assembly lineage disagree"
        )
    destination = destination.expanduser().resolve()
    export_id = typed_id(
        "participantsubtitle",
        speaker_view.view_id,
        speaker_view.reviewed_identity_view_id,
        selected_policy.model_dump(mode="json"),
    )
    cues, cue_losses = _build_cues(
        speaker_view, export_id, selected_policy
    )
    metadata_losses = tuple(
        _loss(
            export_id,
            SubtitleLossClassification.FORMAT_METADATA_IN_COMPANION_MANIFEST,
            (
                f"{item.value} cannot carry complete transcript, identity, "
                "attribution, and policy lineage; see manifest.json."
            ),
        )
        for item in selected_policy.subtitle_policy.formats
    )
    losses_by_id = {
        item.loss_id: item for item in (*cue_losses, *metadata_losses)
    }
    losses = tuple(losses_by_id.values())
    files, rendered = _rendered_files(
        export_id,
        speaker_view.view_id,
        speaker_view.reviewed_identity_view_id,
        cues,
        selected_policy,
    )
    manifest = _seal(
        ParticipantSubtitleManifest,
        {
            "export_id": export_id,
            "speaker_transcript_view_id": speaker_view.view_id,
            "source_assembly_id": assembly.assembly_id,
            "source_transcript_version_id": (
                speaker_view.source_transcript_version_id
            ),
            "source_revision_id": speaker_view.source_revision_id,
            "identity_view_assembly_id": (
                speaker_view.identity_view_assembly_id
            ),
            "reviewed_identity_view_id": (
                speaker_view.reviewed_identity_view_id
            ),
            "diarization_run_id": speaker_view.diarization_run_id,
            "corpus_id": speaker_view.corpus_id,
            "source_id": assembly.source_id,
            "normalized_audio_duration_microseconds": (
                assembly.normalized_audio_duration_microseconds
            ),
            "source_mapping_offset_microseconds": (
                assembly.source_mapping_offset_microseconds
            ),
            "generated_at": speaker_view.created_at,
            "policy": selected_policy,
            "cues": cues,
            "losses": losses,
            "files": files,
            "status": "warning" if losses or any(
                item.unresolved or item.overlap_disclosed for item in cues
            ) else "complete",
        },
    )
    report = _report(manifest)
    root = destination / "participant-subtitles" / export_id
    manifest_path = root / "manifest.json"
    report_path = root / "validation-report.json"
    expected_paths = (
        manifest_path,
        report_path,
        *(root / item.relative_path for item in files),
    )
    existing = tuple(item.exists() for item in expected_paths)
    if any(existing) and not all(existing):
        raise ParticipantSubtitleIntegrityError(
            "cached participant subtitle export is incomplete"
        )
    if all(existing):
        stored = load_contract(
            manifest_path.read_bytes(), ParticipantSubtitleManifest
        )
        stored_report = load_contract(
            report_path.read_bytes(), ParticipantSubtitleReport
        )
        validate_participant_subtitles(
            stored,
            root,
            speaker_view,
            assembly,
            report=stored_report,
        )
        if stored != manifest or stored_report != report:
            raise ParticipantSubtitleIntegrityError(
                "cached participant subtitle export is incompatible"
            )
        return stored, stored_report, root, True
    for relative, data in rendered.items():
        _atomic(root / relative, data)
    _atomic(manifest_path, canonical_bytes(manifest))
    _atomic(report_path, canonical_bytes(report))
    validate_participant_subtitles(
        manifest, root, speaker_view, assembly, report=report
    )
    return manifest, report, root, False


def validate_participant_subtitles(
    manifest: ParticipantSubtitleManifest,
    root: Path,
    speaker_view: SpeakerLabeledTranscriptView,
    assembly: TranscriptAssembly,
    *,
    report: ParticipantSubtitleReport | None = None,
) -> None:
    if canonical_hash(_integrity_payload(manifest)) != (
        manifest.integrity_sha256
    ):
        raise ParticipantSubtitleIntegrityError(
            "participant subtitle manifest integrity is invalid"
        )
    validate_transcript_assembly(assembly)
    if canonical_hash(_integrity_payload(speaker_view)) != (
        speaker_view.integrity_sha256
    ):
        raise ParticipantSubtitleIntegrityError(
            "speaker transcript integrity is invalid"
        )
    if (
        manifest.speaker_transcript_view_id != speaker_view.view_id
        or manifest.source_assembly_id != assembly.assembly_id
        or manifest.source_transcript_version_id
        != speaker_view.source_transcript_version_id
        or manifest.source_revision_id != speaker_view.source_revision_id
        or manifest.identity_view_assembly_id
        != speaker_view.identity_view_assembly_id
        or manifest.reviewed_identity_view_id
        != speaker_view.reviewed_identity_view_id
        or manifest.diarization_run_id != speaker_view.diarization_run_id
        or manifest.corpus_id != assembly.version.corpus_id
        or manifest.source_id != assembly.source_id
    ):
        raise ParticipantSubtitleIntegrityError(
            "participant subtitle lineage is incompatible"
        )
    expected_cues, cue_losses = _build_cues(
        speaker_view, manifest.export_id, manifest.policy
    )
    if manifest.cues != expected_cues:
        raise ParticipantSubtitleIntegrityError(
            "participant subtitle cues differ from the speaker transcript"
        )
    metadata_losses = tuple(
        _loss(
            manifest.export_id,
            SubtitleLossClassification.FORMAT_METADATA_IN_COMPANION_MANIFEST,
            (
                f"{item.value} cannot carry complete transcript, identity, "
                "attribution, and policy lineage; see manifest.json."
            ),
        )
        for item in manifest.policy.subtitle_policy.formats
    )
    expected_losses = {
        item.loss_id: item
        for item in (*cue_losses, *metadata_losses)
    }
    if manifest.losses != tuple(expected_losses.values()):
        raise ParticipantSubtitleIntegrityError(
            "participant subtitle loss declarations are invalid"
        )
    previous = -1
    duration_ms = (
        manifest.normalized_audio_duration_microseconds + 999
    ) // 1000
    for ordinal, cue in enumerate(manifest.cues):
        start = cue.normalized_audio_interval.start_microseconds
        end = (
            start + cue.normalized_audio_interval.duration_microseconds
        )
        expected_start, expected_end = _round(
            start, end, manifest.policy
        )
        if (
            cue.sequence_position != ordinal
            or start < previous
            or cue.source_interval.start_microseconds
            != start + manifest.source_mapping_offset_microseconds
            or cue.rounded_start_milliseconds != expected_start
            or cue.rounded_end_milliseconds != expected_end
            or expected_end > duration_ms
        ):
            raise ParticipantSubtitleIntegrityError(
                "participant subtitle cue addressing is invalid"
            )
        previous = start
    expected_files, rendered = _rendered_files(
        manifest.export_id,
        speaker_view.view_id,
        speaker_view.reviewed_identity_view_id,
        manifest.cues,
        manifest.policy,
    )
    if manifest.files != expected_files:
        raise ParticipantSubtitleIntegrityError(
            "participant subtitle file references are invalid"
        )
    root = root.expanduser().resolve()
    for reference in manifest.files:
        relative = Path(reference.relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ParticipantSubtitleIntegrityError(
                "unsafe participant subtitle path"
            )
        path = (root / relative).resolve()
        if root not in path.parents:
            raise ParticipantSubtitleIntegrityError(
                "participant subtitle file escapes export root"
            )
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise ParticipantSubtitleIntegrityError(
                f"participant subtitle file is missing: {relative}"
            ) from exc
        if (
            data != rendered[reference.relative_path]
            or _sha256(data) != reference.content_sha256
            or len(data) != reference.byte_size
        ):
            raise ParticipantSubtitleIntegrityError(
                f"participant subtitle file failed validation: {relative}"
            )
    if report is not None and (
        canonical_hash(_integrity_payload(report)) != report.integrity_sha256
        or report != _report(manifest)
    ):
        raise ParticipantSubtitleIntegrityError(
            "participant subtitle report integrity or projection is invalid"
        )


def load_participant_subtitles(
    root: Path,
) -> tuple[ParticipantSubtitleManifest, ParticipantSubtitleReport]:
    root = root.expanduser().resolve(strict=True)
    return (
        load_contract(
            (root / "manifest.json").read_bytes(),
            ParticipantSubtitleManifest,
        ),
        load_contract(
            (root / "validation-report.json").read_bytes(),
            ParticipantSubtitleReport,
        ),
    )
