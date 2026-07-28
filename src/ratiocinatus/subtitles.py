"""Deterministic WebVTT/SRT export from declared transcript versions."""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path
from typing import Any

from .addressing_contracts import MediaInterval, TimeDomain
from .correction_contracts import (
    TranscriptRevision,
    TranscriptSegmentState,
    TranscriptViewKind,
)
from .corrections import (
    _state_from_segment,
    _verify_persisted_revision,
    validate_transcript_revision,
)
from .kernel import canonical_bytes, canonical_hash, load_contract, typed_id
from .subtitle_contracts import (
    SubtitleCue,
    SubtitleExportFile,
    SubtitleExportManifest,
    SubtitleExportPolicy,
    SubtitleFormat,
    SubtitleLossClassification,
    SubtitleLossRecord,
    SubtitleSegmentationOrigin,
    SubtitleValidationReport,
)
from .transcript_assembly import (
    _verify_persisted as _verify_persisted_assembly,
    validate_transcript_assembly,
)
from .transcript_contracts import (
    TranscriptAssembly,
    TranscriptAssemblyStatus,
    TranscriptWord,
)


class SubtitleExportIntegrityError(RuntimeError):
    pass


def _atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.partial-{uuid.uuid4().hex}")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _seal(model: Any) -> Any:
    payload = model.model_dump(mode="json")
    payload.pop("integrity_sha256")
    return model.model_copy(update={"integrity_sha256": canonical_hash(payload)})


def _verify_seal(model: Any, label: str) -> None:
    payload = model.model_dump(mode="json")
    actual = payload.pop("integrity_sha256")
    if canonical_hash(payload) != actual:
        raise SubtitleExportIntegrityError(
            f"{label} integrity hash does not match its content"
        )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalize(text: str) -> str:
    return " ".join(text.split())


def _end(interval: MediaInterval) -> int:
    return interval.start_microseconds + interval.duration_microseconds


def _mapped_interval(
    start: int,
    end: int,
    *,
    domain: TimeDomain,
) -> MediaInterval:
    return MediaInterval(
        domain=domain,
        start_microseconds=start,
        duration_microseconds=end - start,
    )


def _round(start: int, end: int, policy: SubtitleExportPolicy) -> tuple[int, int]:
    resolution = policy.rounding.resolution_microseconds
    start_ms = start // resolution
    end_ms = (end + resolution - 1) // resolution
    minimum = policy.rounding.minimum_rounded_duration_milliseconds
    if end_ms - start_ms < minimum:
        end_ms = start_ms + minimum
    return start_ms, end_ms


def _lines(text: str, policy: SubtitleExportPolicy) -> tuple[str, ...]:
    words = text.split()
    if not words:
        raise SubtitleExportIntegrityError("subtitle cue text is empty")
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > policy.maximum_line_characters:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return tuple(lines)


def _loss(
    export_id: str,
    classification: SubtitleLossClassification,
    explanation: str,
    *,
    cue_id: str | None = None,
) -> SubtitleLossRecord:
    return SubtitleLossRecord(
        loss_id=typed_id(
            "subtitleloss",
            export_id,
            cue_id,
            classification.value,
            explanation,
        ),
        cue_id=cue_id,
        classification=classification,
        explanation=explanation,
    )


def _word_groups(
    state: TranscriptSegmentState,
    words: tuple[TranscriptWord, ...],
    policy: SubtitleExportPolicy,
) -> tuple[tuple[TranscriptWord, ...], ...] | None:
    if not words:
        return None
    ordered = tuple(
        sorted(
            words,
            key=lambda item: (
                item.normalized_audio_interval.start_microseconds,
                item.sequence_position,
            ),
        )
    )
    joined = _normalize("".join(item.surface_text for item in ordered))
    if joined != state.normalized_text:
        return None
    groups: list[list[TranscriptWord]] = []
    current: list[TranscriptWord] = []
    for word in ordered:
        candidate = current + [word]
        candidate_text = _normalize(
            "".join(item.surface_text for item in candidate)
        )
        duration = (
            _end(candidate[-1].normalized_audio_interval)
            - candidate[0].normalized_audio_interval.start_microseconds
        )
        if current and (
            len(candidate_text) > policy.maximum_cue_characters
            or duration > policy.maximum_cue_duration_microseconds
        ):
            groups.append(current)
            current = [word]
        else:
            current = candidate
    if current:
        groups.append(current)
    return tuple(tuple(group) for group in groups)


def _cue_parts(
    state: TranscriptSegmentState,
    word_by_id: dict[str, TranscriptWord],
    policy: SubtitleExportPolicy,
) -> tuple[
    tuple[
        MediaInterval,
        MediaInterval,
        str,
        tuple[str, ...],
        SubtitleSegmentationOrigin,
    ],
    ...,
]:
    interval = state.normalized_audio_interval
    long = (
        len(state.normalized_text) > policy.maximum_cue_characters
        or interval.duration_microseconds
        > policy.maximum_cue_duration_microseconds
    )
    if not long:
        return (
            (
                state.source_interval,
                interval,
                state.normalized_text,
                state.retained_word_ids,
                SubtitleSegmentationOrigin.CANONICAL_SEGMENT,
            ),
        )
    retained = tuple(
        word_by_id[word_id]
        for word_id in state.retained_word_ids
        if word_id in word_by_id
    )
    groups = _word_groups(state, retained, policy)
    if groups is None or len(groups) <= 1:
        return (
            (
                state.source_interval,
                interval,
                state.normalized_text,
                state.retained_word_ids,
                SubtitleSegmentationOrigin.CANONICAL_SEGMENT,
            ),
        )
    parts = []
    for group in groups:
        normalized_start = group[0].normalized_audio_interval.start_microseconds
        normalized_end = _end(group[-1].normalized_audio_interval)
        source_start = group[0].source_interval.start_microseconds
        source_end = _end(group[-1].source_interval)
        parts.append(
            (
                _mapped_interval(
                    source_start, source_end, domain=TimeDomain.SOURCE_MEDIA
                ),
                _mapped_interval(
                    normalized_start,
                    normalized_end,
                    domain=TimeDomain.NORMALIZED_CORPUS,
                ),
                _normalize("".join(item.surface_text for item in group)),
                tuple(item.word_id for item in group),
                SubtitleSegmentationOrigin.PROVIDER_WORD_TIMESTAMPS,
            )
        )
    return tuple(parts)


def _build_cues(
    *,
    export_id: str,
    states: tuple[TranscriptSegmentState, ...],
    assembly: TranscriptAssembly,
    policy: SubtitleExportPolicy,
) -> tuple[tuple[SubtitleCue, ...], tuple[SubtitleLossRecord, ...]]:
    word_by_id = {item.word_id: item for item in assembly.words}
    regions = assembly.low_confidence_regions
    cues: list[SubtitleCue] = []
    losses: list[SubtitleLossRecord] = []
    for state in states:
        related_regions = tuple(
            item
            for item in regions
            if item.segment_id in state.origin_segment_ids
            or (
                item.word_id is not None
                and item.word_id in state.retained_word_ids
            )
        )
        parts = _cue_parts(state, word_by_id, policy)
        long_original = (
            len(state.normalized_text) > policy.maximum_cue_characters
            or state.normalized_audio_interval.duration_microseconds
            > policy.maximum_cue_duration_microseconds
        )
        for part_index, (
            source_interval,
            normalized_interval,
            text,
            word_ids,
            origin,
        ) in enumerate(parts):
            if "-->" in text or "\x00" in text:
                raise SubtitleExportIntegrityError(
                    "subtitle text contains a prohibited control or timing token"
                )
            try:
                text.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise SubtitleExportIntegrityError(
                    "subtitle text contains malformed Unicode"
                ) from exc
            start = normalized_interval.start_microseconds
            end = _end(normalized_interval)
            start_ms, end_ms = _round(start, end, policy)
            cue_id = typed_id(
                "cue",
                export_id,
                state.artifact_id,
                part_index,
                normalized_interval.model_dump(mode="json"),
                text,
            )
            rendered_lines = _lines(text, policy)
            cue = SubtitleCue(
                cue_id=cue_id,
                sequence_position=len(cues),
                source_interval=source_interval,
                normalized_audio_interval=normalized_interval,
                rounded_start_milliseconds=start_ms,
                rounded_end_milliseconds=end_ms,
                text=text,
                rendered_lines=rendered_lines,
                source_artifact_ids=tuple(
                    dict.fromkeys(
                        (state.artifact_id, *state.origin_segment_ids)
                    )
                ),
                retained_word_ids=word_ids,
                low_confidence_region_ids=tuple(
                    item.region_id for item in related_regions
                ),
                review_recommended=any(
                    item.review_recommended for item in related_regions
                ),
                segmentation_origin=origin,
            )
            cues.append(cue)
            if start % 1000 or end % 1000:
                losses.append(
                    _loss(
                        export_id,
                        SubtitleLossClassification.MILLISECOND_TIMESTAMP_ROUNDING,
                        "Canonical microseconds were rounded: start=floor, end=ceiling.",
                        cue_id=cue_id,
                    )
                )
            if _normalize(state.text) != state.text:
                losses.append(
                    _loss(
                        export_id,
                        SubtitleLossClassification.NORMALIZED_TEXT_RENDERING,
                        "Subtitle rendering uses the versioned normalized text.",
                        cue_id=cue_id,
                    )
                )
            if origin == SubtitleSegmentationOrigin.PROVIDER_WORD_TIMESTAMPS:
                losses.append(
                    _loss(
                        export_id,
                        SubtitleLossClassification.WORD_TIMING_SEGMENTATION,
                        "Long canonical segment was divided at retained provider-native word timestamps.",
                        cue_id=cue_id,
                    )
                )
            elif long_original:
                losses.append(
                    _loss(
                        export_id,
                        SubtitleLossClassification.LONG_CUE_RETAINED,
                        "Long cue lacked safe retained word timing and was preserved unsplit.",
                        cue_id=cue_id,
                    )
                )
            if len(rendered_lines) > policy.maximum_lines_per_cue or any(
                len(line) > policy.maximum_line_characters
                for line in rendered_lines
            ):
                losses.append(
                    _loss(
                        export_id,
                        SubtitleLossClassification.LINE_LENGTH_EXCEEDED,
                        "Cue cannot satisfy configured line constraints without unsupported timing inference.",
                        cue_id=cue_id,
                    )
                )
            if related_regions:
                losses.append(
                    _loss(
                        export_id,
                        SubtitleLossClassification.LOW_CONFIDENCE_IN_COMPANION_MANIFEST,
                        "Low-confidence evidence is retained by cue reference in manifest.json.",
                        cue_id=cue_id,
                    )
                )
    return tuple(cues), tuple(losses)


def _timestamp(milliseconds: int, separator: str) -> str:
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return (
        f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        f"{separator}{millis:03d}"
    )


def render_webvtt(export_id: str, version_id: str, cues: tuple[SubtitleCue, ...]) -> bytes:
    lines = [
        "WEBVTT",
        "",
        f"NOTE Ratiocinatus export {export_id}",
        f"NOTE Transcript version {version_id}; evidentiary metadata: manifest.json",
        "",
    ]
    for cue in cues:
        lines.extend(
            [
                cue.cue_id,
                (
                    f"{_timestamp(cue.rounded_start_milliseconds, '.')} --> "
                    f"{_timestamp(cue.rounded_end_milliseconds, '.')}"
                ),
                *cue.rendered_lines,
                "",
            ]
        )
    return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


def render_srt(cues: tuple[SubtitleCue, ...]) -> bytes:
    lines: list[str] = []
    for index, cue in enumerate(cues, start=1):
        lines.extend(
            [
                str(index),
                (
                    f"{_timestamp(cue.rounded_start_milliseconds, ',')} --> "
                    f"{_timestamp(cue.rounded_end_milliseconds, ',')}"
                ),
                *cue.rendered_lines,
                "",
            ]
        )
    return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


def _rendered_files(
    export_id: str,
    version_id: str,
    cues: tuple[SubtitleCue, ...],
    formats: tuple[SubtitleFormat, ...],
) -> tuple[tuple[SubtitleExportFile, ...], dict[str, bytes]]:
    values: dict[str, bytes] = {}
    references: list[SubtitleExportFile] = []
    for subtitle_format in formats:
        if subtitle_format == SubtitleFormat.WEBVTT:
            relative = "transcript.vtt"
            media_type = "text/vtt"
            data = render_webvtt(export_id, version_id, cues)
        else:
            relative = "transcript.srt"
            media_type = "application/x-subrip"
            data = render_srt(cues)
        values[relative] = data
        references.append(
            SubtitleExportFile(
                subtitle_format=subtitle_format,
                relative_path=relative,
                media_type=media_type,
                content_sha256=_sha256(data),
                byte_size=len(data),
            )
        )
    return tuple(references), values


def _validate_cue_addressing(
    cues: tuple[SubtitleCue, ...],
    *,
    duration_microseconds: int,
    source_mapping_offset_microseconds: int,
    policy: SubtitleExportPolicy,
) -> None:
    if tuple(item.sequence_position for item in cues) != tuple(range(len(cues))):
        raise SubtitleExportIntegrityError(
            "subtitle cue positions must be contiguous"
        )
    if len({item.cue_id for item in cues}) != len(cues):
        raise SubtitleExportIntegrityError("subtitle cue IDs must be unique")
    previous_start = 0
    previous_rounded_start = 0
    duration_ms = (duration_microseconds + 999) // 1000
    for cue in cues:
        start = cue.normalized_audio_interval.start_microseconds
        end = _end(cue.normalized_audio_interval)
        expected_start = start // 1000
        expected_end = max(
            (end + 999) // 1000,
            expected_start
            + policy.rounding.minimum_rounded_duration_milliseconds,
        )
        if (
            start < previous_start
            or cue.rounded_start_milliseconds < previous_rounded_start
            or end > duration_microseconds
            or cue.source_interval.start_microseconds
            != start + source_mapping_offset_microseconds
            or _end(cue.source_interval)
            != end + source_mapping_offset_microseconds
            or cue.rounded_start_milliseconds != expected_start
            or cue.rounded_end_milliseconds != expected_end
            or cue.rounded_end_milliseconds > duration_ms
        ):
            raise SubtitleExportIntegrityError(
                "subtitle cue timing regresses or exceeds source addressing"
            )
        previous_start = start
        previous_rounded_start = cue.rounded_start_milliseconds


def _validate_cues(
    cues: tuple[SubtitleCue, ...],
    assembly: TranscriptAssembly,
    policy: SubtitleExportPolicy,
) -> None:
    _validate_cue_addressing(
        cues,
        duration_microseconds=assembly.normalized_audio_duration_microseconds,
        source_mapping_offset_microseconds=(
            assembly.source_mapping_offset_microseconds
        ),
        policy=policy,
    )


def _report(
    manifest: SubtitleExportManifest,
) -> SubtitleValidationReport:
    start_losses = tuple(
        item.normalized_audio_interval.start_microseconds
        - item.rounded_start_milliseconds * 1000
        for item in manifest.cues
    )
    end_losses = tuple(
        item.rounded_end_milliseconds * 1000
        - _end(item.normalized_audio_interval)
        for item in manifest.cues
    )
    return SubtitleValidationReport(
        report_id=typed_id("subtitlevalidation", manifest.export_id),
        export_id=manifest.export_id,
        transcript_version_id=manifest.transcript_version_id,
        generated_at=manifest.generated_at,
        cue_count=len(manifest.cues),
        reviewed_cue_count=sum(
            item.review_recommended for item in manifest.cues
        ),
        split_cue_count=sum(
            item.segmentation_origin
            == SubtitleSegmentationOrigin.PROVIDER_WORD_TIMESTAMPS
            for item in manifest.cues
        ),
        loss_record_count=len(manifest.losses),
        maximum_start_rounding_loss_microseconds=max(start_losses, default=0),
        maximum_end_rounding_loss_microseconds=max(end_losses, default=0),
        checked_formats=tuple(item.subtitle_format for item in manifest.files),
        valid=True,
    )


def validate_subtitle_export(
    manifest: SubtitleExportManifest,
    root: Path,
    *,
    assembly: TranscriptAssembly | None = None,
    report: SubtitleValidationReport | None = None,
) -> None:
    _verify_seal(manifest, "subtitle export manifest")
    _validate_cue_addressing(
        manifest.cues,
        duration_microseconds=(
            manifest.normalized_audio_duration_microseconds
        ),
        source_mapping_offset_microseconds=(
            manifest.source_mapping_offset_microseconds
        ),
        policy=manifest.policy,
    )
    if report is not None and report != _report(manifest):
        raise SubtitleExportIntegrityError(
            "subtitle validation report differs from the manifest"
        )
    if assembly is not None:
        if (
            manifest.base_assembly_id != assembly.assembly_id
            or manifest.corpus_id != assembly.version.corpus_id
            or manifest.source_id != assembly.source_id
            or manifest.normalized_audio_duration_microseconds
            != assembly.normalized_audio_duration_microseconds
        ):
            raise SubtitleExportIntegrityError(
                "subtitle export belongs to another base assembly"
            )
        _validate_cues(manifest.cues, assembly, manifest.policy)
    root = root.resolve()
    expected_files, rendered = _rendered_files(
        manifest.export_id,
        manifest.transcript_version_id,
        manifest.cues,
        manifest.policy.formats,
    )
    if manifest.files != expected_files:
        raise SubtitleExportIntegrityError(
            "subtitle file references differ from deterministic rendering"
        )
    for reference in manifest.files:
        relative = Path(reference.relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise SubtitleExportIntegrityError("unsafe subtitle export path")
        path = (root / relative).resolve()
        if root not in path.parents:
            raise SubtitleExportIntegrityError(
                "subtitle file escapes export root"
            )
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise SubtitleExportIntegrityError(
                f"subtitle file is missing: {reference.relative_path}"
            ) from exc
        if (
            data != rendered[reference.relative_path]
            or _sha256(data) != reference.content_sha256
            or len(data) != reference.byte_size
        ):
            raise SubtitleExportIntegrityError(
                f"subtitle file failed validation: {reference.relative_path}"
            )


def export_subtitles(
    assembly_root: Path,
    destination: Path,
    *,
    revision_root: Path | None = None,
    view_kind: TranscriptViewKind = TranscriptViewKind.ORIGINAL_MACHINE,
    policy: SubtitleExportPolicy | None = None,
) -> tuple[
    SubtitleExportManifest,
    SubtitleValidationReport,
    Path,
    bool,
]:
    assembly_root = assembly_root.expanduser().resolve(strict=True)
    destination = destination.expanduser().resolve()
    if destination == assembly_root or assembly_root in destination.parents:
        raise ValueError(
            "subtitle output must not modify the base assembly directory"
        )
    assembly = load_contract(
        (assembly_root / "assembly.json").read_bytes(), TranscriptAssembly
    )
    validate_transcript_assembly(assembly)
    _verify_persisted_assembly(assembly_root, assembly)
    if assembly.status == TranscriptAssemblyStatus.BLOCKED:
        raise SubtitleExportIntegrityError(
            "blocked transcript assembly cannot be exported"
        )
    revision = None
    if revision_root is not None:
        revision_root = revision_root.expanduser().resolve(strict=True)
        revision = load_contract(
            (revision_root / "revision.json").read_bytes(),
            TranscriptRevision,
        )
        validate_transcript_revision(revision, assembly=assembly)
        _verify_persisted_revision(revision_root, revision)
    if view_kind == TranscriptViewKind.CURRENT_CORRECTED:
        if revision is None:
            raise SubtitleExportIntegrityError(
                "corrected subtitle view requires a transcript revision"
            )
        view = revision.current_corrected_view
    elif revision is not None:
        view = revision.original_machine_view
    else:
        states = _state_from_segment(assembly)
        from .corrections import _view

        view = _view(
            version_id=assembly.version.version_id,
            kind=TranscriptViewKind.ORIGINAL_MACHINE,
            segments=states,
            created_at=assembly.assembled_at,
        )
    policy = policy or SubtitleExportPolicy()
    export_id = typed_id(
        "subtitleexport",
        assembly.assembly_id,
        revision.revision_id if revision is not None else None,
        view.version_id,
        view_kind.value,
        policy.model_dump(mode="json"),
    )
    cues, cue_losses = _build_cues(
        export_id=export_id,
        states=view.segments,
        assembly=assembly,
        policy=policy,
    )
    _validate_cues(cues, assembly, policy)
    global_losses = tuple(
        _loss(
            export_id,
            SubtitleLossClassification.FORMAT_METADATA_IN_COMPANION_MANIFEST,
            (
                f"{subtitle_format.value} cannot carry the complete source, "
                "confidence, policy, and loss model; see manifest.json."
            ),
        )
        for subtitle_format in policy.formats
    )
    files, rendered = _rendered_files(
        export_id, view.version_id, cues, policy.formats
    )
    losses = cue_losses + global_losses
    manifest = _seal(
        SubtitleExportManifest(
            export_id=export_id,
            base_assembly_id=assembly.assembly_id,
            revision_id=(
                revision.revision_id if revision is not None else None
            ),
            transcript_version_id=view.version_id,
            view_kind=view_kind,
            corpus_id=assembly.version.corpus_id,
            source_id=assembly.source_id,
            normalized_audio_duration_microseconds=(
                assembly.normalized_audio_duration_microseconds
            ),
            source_mapping_offset_microseconds=(
                assembly.source_mapping_offset_microseconds
            ),
            generated_at=view.created_at,
            policy=policy,
            cues=cues,
            losses=losses,
            files=files,
            status="warning" if losses else "complete",
            integrity_sha256="0" * 64,
        )
    )
    report = _report(manifest)
    root = destination / "subtitle-exports" / export_id
    manifest_path = root / "manifest.json"
    report_path = root / "validation-report.json"
    if manifest_path.exists() or report_path.exists():
        if not manifest_path.exists() or not report_path.exists():
            raise SubtitleExportIntegrityError(
                "cached subtitle export is incomplete"
            )
        stored = load_contract(
            manifest_path.read_bytes(), SubtitleExportManifest
        )
        stored_report = load_contract(
            report_path.read_bytes(), SubtitleValidationReport
        )
        if stored != manifest or stored_report != report:
            raise SubtitleExportIntegrityError(
                "cached subtitle export is incompatible"
            )
        validate_subtitle_export(
            stored, root, assembly=assembly, report=stored_report
        )
        return stored, stored_report, root, True
    for relative, data in rendered.items():
        _atomic(root / relative, data)
    _atomic(manifest_path, canonical_bytes(manifest))
    _atomic(report_path, canonical_bytes(report))
    validate_subtitle_export(
        manifest, root, assembly=assembly, report=report
    )
    return manifest, report, root, False
