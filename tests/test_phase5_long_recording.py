import pytest

from ratiocinatus.kernel import load_contract
from ratiocinatus.phase5_completion_contracts import (
    Phase5LongRecordingQualification,
)
from ratiocinatus.phase5_long_recording import (
    Phase5LongRecordingError,
    persist_phase5_long_recording,
    qualify_phase5_long_recording,
    validate_phase5_long_recording,
)

from test_phase5_foundation import NOW


def test_more_than_two_hours_uses_bounded_incremental_state(tmp_path):
    result = qualify_phase5_long_recording(generated_at=NOW)
    assert result.duration_microseconds > 7_200_000_000
    assert result.processing_chunk_count == 121
    assert result.utterance_count == result.discourse_act_count == 121
    assert result.maximum_active_context_utterances == 12
    assert result.maximum_relation_search_utterances == 20
    assert result.cross_chunk_continuity_count == 120
    assert result.duplicate_act_ownership_count == 0
    assert result.peak_memory_bytes < 64 * 1024
    assert result.export_reload_valid
    assert result.final_integrity_valid
    assert result.natural_discourse_accuracy_claim is False
    validate_phase5_long_recording(result)
    path = persist_phase5_long_recording(result, tmp_path / "long.json")
    assert load_contract(
        path.read_bytes(), Phase5LongRecordingQualification
    ) == result
    assert persist_phase5_long_recording(result, path) == path


def test_long_recording_refuses_short_input_and_tampering():
    with pytest.raises(Phase5LongRecordingError, match="exceed two hours"):
        qualify_phase5_long_recording(
            generated_at=NOW, duration_microseconds=7_200_000_000
        )
    result = qualify_phase5_long_recording(generated_at=NOW)
    tampered = result.model_copy(update={"discourse_act_count": 999})
    with pytest.raises(Phase5LongRecordingError, match="integrity"):
        validate_phase5_long_recording(tampered)
