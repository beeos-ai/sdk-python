from pathlib import Path

import pytest
from pydantic import ValidationError

from beeos_sdk.models.agent_list_response import AgentListResponse
from beeos_sdk.models.error import Error
from beeos_sdk.models.error_response import ErrorResponse
from beeos_sdk.models.success_envelope import SuccessEnvelope


def test_success_responses_accept_real_json_boolean() -> None:
    assert SuccessEnvelope.from_dict({"success": True}).success is True
    response = AgentListResponse.from_dict({"success": True, "data": [], "total": 0})
    assert response.success is True


def test_error_responses_accept_real_json_boolean() -> None:
    response = ErrorResponse.from_dict({
        "success": False,
        "error": {"code": "invalid_request", "message": "invalid"},
    })
    assert response.success is False
    assert isinstance(response.error, Error)


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (SuccessEnvelope, {"success": False}),
        (AgentListResponse, {"success": False, "data": [], "total": 0}),
        (ErrorResponse, {
            "success": True,
            "error": {"code": "invalid_request", "message": "invalid"},
        }),
    ],
)
def test_const_direction_is_still_enforced(model: type, payload: dict) -> None:
    with pytest.raises(ValidationError):
        model.from_dict(payload)


def test_no_string_boolean_const_comparisons_remain() -> None:
    models_dir = Path(__file__).parents[1] / "beeos_sdk" / "models"
    offenders = [
        path.name
        for path in models_dir.glob("*.py")
        if "set(['true'])" in path.read_text()
        or "set(['false'])" in path.read_text()
    ]
    assert offenders == []
