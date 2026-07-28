from datetime import datetime, timezone

import pytest

from ratiocinatus.kernel import load_contract
from ratiocinatus.phase4_completion_contracts import (
    Phase4LongRecordingQualification,
)
from ratiocinatus.phase4_long_recording import (
    Phase4LongRecordingError,
    persist_phase4_long_recording,
    qualify_phase4_long_recording,
    validate_phase4_long_recording,
)


NOW = datetime(2026, 7, 27, tzinfo=timezone.utc)


def test_long_recording_qualifies_more_than_two_hours_with_bounded_state(
    tmp_path,
):
    result = qualify_phase4_long_recording(generated_at=NOW)
    assert result.duration_microseconds > 7_200_000_000
    assert result.processing_chunk_count == 121
    assert result.context_window_count == result.utterance_count * 9
    assert result.duplicate_word_ownership_count == 0
    assert result.duplicate_utterance_count == 0
    assert result.peak_memory_bytes < 64 * 1024
    assert result.natural_speech_accuracy_claim is False
    validate_phase4_long_recording(result)

    path = persist_phase4_long_recording(result, tmp_path / "long.json")
    loaded = load_contract(
        path.read_bytes(), Phase4LongRecordingQualification
    )
    assert loaded == result
    assert persist_phase4_long_recording(result, path) == path


def test_long_recording_refuses_two_hours_or_less_and_tampering():
    with pytest.raises(Phase4LongRecordingError, match="exceed two hours"):
        qualify_phase4_long_recording(
            generated_at=NOW,
            duration_microseconds=7_200_000_000,
        )

    result = qualify_phase4_long_recording(generated_at=NOW)
    tampered = result.model_copy(update={"utterance_count": 999})
    with pytest.raises(Phase4LongRecordingError, match="integrity"):
        validate_phase4_long_recording(tampered)
