from __future__ import annotations

import pytest
from pydantic import ValidationError

from ratiocinatus.turn_repair_contracts import (
    TURN_REPAIR_CONTRACT_MODELS,
    TurnRepairActionKind,
    TurnRepairPolicy,
    TurnRepairProposedChange,
)


def test_turn_repair_contract_inventory_and_policy_are_strict() -> None:
    assert len(TURN_REPAIR_CONTRACT_MODELS) == 8
    assert len({item.__name__ for item in TURN_REPAIR_CONTRACT_MODELS}) == 8
    for model in TURN_REPAIR_CONTRACT_MODELS:
        assert model.model_json_schema().get("additionalProperties") is False
    policy = TurnRepairPolicy()
    assert policy.automatic_word_reassignment == "prohibited"
    assert policy.automatic_source_mutation == "prohibited"


def test_boundary_move_and_word_repair_require_bounded_inputs() -> None:
    with pytest.raises(ValidationError, match="boundary move"):
        TurnRepairProposedChange(
            action=TurnRepairActionKind.MOVE_BOUNDARY,
            description="Invalid unbounded move.",
        )
    with pytest.raises(ValidationError, match="requires transcript words"):
        TurnRepairProposedChange(
            action=TurnRepairActionKind.REASSIGN_TRANSCRIPT_WORDS,
            description="Invalid unbounded reassignment.",
        )
    with pytest.raises(ValidationError, match="cannot discard"):
        TurnRepairProposedChange(
            action=TurnRepairActionKind.MARK_UNRESOLVED,
            preserves_all_source_intervals=False,
            description="Invalid destructive proposal.",
        )
