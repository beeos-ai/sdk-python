from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from beeos_sdk.mobile import MobileClient, _status_value


class FakeApiClient:
    def close(self):
        pass


def test_mobile_client_requires_runtime_identity():
    try:
        MobileClient(api_key="key", agent_id="", instance_id="instance")
    except ValueError as exc:
        assert "agent_id" in str(exc)
    else:
        raise AssertionError("missing agent_id accepted")


def test_status_value_accepts_generated_enum_shape():
    snapshot = SimpleNamespace(data=SimpleNamespace(status=SimpleNamespace(value="completed")))
    assert _status_value(snapshot) == "completed"


def test_injected_client_is_not_closed():
    api = Mock()
    mobile = MobileClient(api_key="key", agent_id="agent", instance_id="phone", api_client=api)
    mobile.close()
    api.close.assert_not_called()


def test_owned_generated_client_closes_without_attribute_error(monkeypatch):
    mobile = MobileClient(api_key="key", agent_id="agent", instance_id="phone")
    clear = Mock()
    monkeypatch.setattr(mobile.api_client.rest_client.pool_manager, "clear", clear)
    mobile.close()
    clear.assert_called_once()


def test_run_deadline_includes_submission_without_automatic_cancel(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("beeos_sdk.mobile.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("beeos_sdk.mobile.time.sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    mobile = MobileClient(api_key="key", agent_id="agent", instance_id="phone", api_client=Mock())
    def create(**kwargs):
        assert kwargs["_request_timeout"] == 2.5
        clock[0] += 2.0
        return SimpleNamespace(data=SimpleNamespace(task_id="task"))
    monkeypatch.setattr(mobile.tasks, "create_task", create)
    get = Mock(return_value=SimpleNamespace(data=SimpleNamespace(agent_id="agent", task_id="task", status="running")))
    cancel = Mock()
    monkeypatch.setattr(mobile.tasks, "get_task", get)
    monkeypatch.setattr(mobile.tasks, "cancel_task", cancel)
    with pytest.raises(TimeoutError, match="not automatically cancelled"):
        mobile.run("hello", timeout=2.5)
    assert get.call_count == 1
    assert get.call_args.kwargs["_request_timeout"] == 0.5
    cancel.assert_not_called()


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), True])
def test_mobile_invalid_timeout_never_submits(timeout):
    mobile = MobileClient(api_key="key", agent_id="agent", instance_id="phone", api_client=Mock())
    with pytest.raises(ValueError):
        mobile.run("hello", timeout=timeout)
