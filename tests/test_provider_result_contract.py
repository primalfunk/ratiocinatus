import pytest
from pydantic import ValidationError

from ratiocinatus.contracts import (
    EvidenceArtifact, FailureKind, ProviderResult,
)

INVOCATION_ID = "inv_" + "0" * 32


def test_provider_result_requires_consistent_success_shape() -> None:
    artifact = EvidenceArtifact(artifact_type="mock.test", payload="synthetic")
    assert ProviderResult(
        invocation_id=INVOCATION_ID, success=True, output=artifact
    ).success
    with pytest.raises(ValidationError):
        ProviderResult(invocation_id=INVOCATION_ID, success=True)
    with pytest.raises(ValidationError):
        ProviderResult(
            invocation_id=INVOCATION_ID, success=True, output=artifact,
            failure=FailureKind.PROVIDER_FAILURE,
        )


def test_provider_result_requires_consistent_failure_shape() -> None:
    assert not ProviderResult(
        invocation_id=INVOCATION_ID, success=False,
        failure=FailureKind.PROVIDER_FAILURE,
    ).success
    with pytest.raises(ValidationError):
        ProviderResult(invocation_id=INVOCATION_ID, success=False)

