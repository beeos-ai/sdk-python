from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from beeos import BeeOS, TaskExecutionError
from beeos.resources import Computer, Mobile
from beeos import resources
from beeos_sdk.exceptions import ApiException


def client():
    return BeeOS(api_key="test-key", base_url="https://example.test")


def snapshot(status="completed", **extra):
    return SimpleNamespace(data=SimpleNamespace(task_id="task", agent_id="agent", status=status, **extra))


def test_resource_handles_do_not_create_or_fetch_instances(monkeypatch):
    api = client()
    lookup = Mock(side_effect=AssertionError("should be lazy"))
    monkeypatch.setattr(api.instances.api, "get_instance", lookup)
    instance = api.instance("phone")
    assert instance.id == "phone"
    assert instance.mobile.instance_id == "phone"
    assert instance.computer.instance_id == "phone"
    assert instance.data is None


def test_instance_creation_and_lifecycle_reuse_generated_api(monkeypatch):
    api = client()
    created = SimpleNamespace(data=SimpleNamespace(id="phone"))
    create = Mock(return_value=created)
    monkeypatch.setattr(api.instances.api, "deploy_instance", create)
    instance = api.instances.create(name="SDK test", variant_id="variant")
    request = create.call_args.kwargs["deploy_instance_request"]
    assert request.name == "SDK test"
    assert request.variant_id == "variant"
    assert instance.data is created.data
    for method in ["start", "stop", "restart", "destroy"]:
        invoke = Mock(return_value=created)
        monkeypatch.setattr(instance._api, f"{method}_instance", invoke)
        assert getattr(instance, method)(timeout=12) is created
        invoke.assert_called_once_with(id="phone", _request_timeout=12.0)


def test_instance_ready_requires_online_connectivity(monkeypatch):
    instance = client().instance("phone")
    get = Mock(side_effect=[
        SimpleNamespace(data=SimpleNamespace(id="phone", status="running", connectivity="offline")),
        SimpleNamespace(data=SimpleNamespace(id="phone", status="running", connectivity="online")),
    ])
    monkeypatch.setattr(instance._api, "get_instance", get)
    assert instance.wait_ready(poll_interval=0) is instance
    assert get.call_count == 2


def test_instance_mismatch_and_failed_startup_fail(monkeypatch):
    instance = client().instance("phone")
    monkeypatch.setattr(instance._api, "get_instance", Mock(return_value=SimpleNamespace(data=SimpleNamespace(id="other"))))
    with pytest.raises(ValueError, match="identity"):
        instance.refresh()
    monkeypatch.setattr(instance._api, "get_instance", Mock(return_value=SimpleNamespace(data=SimpleNamespace(id="phone", status="failed"))))
    with pytest.raises(RuntimeError, match="cannot become ready"):
        instance.wait_ready()


@pytest.mark.parametrize("status", ["failed", "timeout", "canceled", "cancelled", "rejected"])
def test_task_wait_requires_success_by_default_and_preserves_failed_snapshot(monkeypatch, status):
    api = client()
    result = snapshot(status)
    get = Mock(return_value=result)
    monkeypatch.setattr(api.tasks._api, "get_task", get)
    task = api.task("agent", "task")
    with pytest.raises(TaskExecutionError) as error:
        task.wait()
    assert error.value.snapshot is result
    assert task.wait(require_success=False) is result


def test_task_identity_and_truncation_are_not_false_successes(monkeypatch):
    api = client()
    result = snapshot(truncated=True)
    monkeypatch.setattr(api.tasks._api, "get_task", Mock(return_value=result))
    with pytest.raises(ValueError, match="truncated"):
        api.task("agent", "task").wait()
    with pytest.raises(ValueError, match="identity"):
        api.task("agent", "another-task").wait()


def test_task_wait_uses_remaining_timeout_and_never_auto_cancels(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(resources.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(resources.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    api = client()
    get = Mock(return_value=snapshot("running"))
    cancel = Mock()
    monkeypatch.setattr(api.tasks._api, "get_task", get)
    monkeypatch.setattr(api.tasks._api, "cancel_task", cancel)
    with pytest.raises(TimeoutError, match="not automatically cancelled"):
        api.task("agent", "task").wait(timeout=2.5, poll_interval=1)
    assert [c.kwargs["_request_timeout"] for c in get.call_args_list] == [2.5, 1.5, 0.5]
    cancel.assert_not_called()


def test_task_get_cancel_and_messages_are_bound_to_the_same_identity(monkeypatch):
    api = client()
    task = api.task("agent", "task")
    for method, generated in [("get", "get_task"), ("cancel", "cancel_task"), ("messages", "list_task_messages")]:
        invoke = Mock(return_value=snapshot())
        monkeypatch.setattr(api.tasks._api, generated, invoke)
        getattr(task, method)(timeout=12)
        assert invoke.call_args.kwargs["agent_id"] == "agent"
        assert invoke.call_args.kwargs["task_id"] == "task"
        assert invoke.call_args.kwargs["_request_timeout"] == 12.0


class RecordingApi:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def invoke(**kwargs):
            self.calls.append((name, kwargs))
            return SimpleNamespace(data=SimpleNamespace(online=True))
        return invoke


def test_all_mobile_actions_use_generated_models_and_the_bound_instance():
    api = RecordingApi()
    phone = Mobile(api, "phone")
    phone.info(); phone.wait_ready(); phone.screenshot()
    phone.ui_tree(format="compact"); phone.list_apps(include_system=True)
    phone.tap(1, 2); phone.double_tap(3, 4); phone.long_press(5, 6, duration_ms=1000)
    phone.drag(1, 2, 3, 4); phone.swipe(1, 2, 3, 4); phone.scroll("down")
    phone.type("hello"); phone.key("BACK"); phone.press_button("home"); phone.open_app("com.android.settings")
    assert len(api.calls) == 15
    assert all(args["id"] == "phone" and args["_request_timeout"] > 0 for _, args in api.calls)
    assert api.calls[-1][1]["open_app_request"].app == "com.android.settings"
    assert api.calls[-3][1]["key_request"].keys == ["BACK"]
    assert api.calls[7][1]["long_press_request"].duration_ms == 1000


def test_computer_hotkey_and_pointer_actions_are_not_mobile_calls():
    api = RecordingApi()
    computer = Computer(api, "desktop")
    computer.info(); computer.screenshot(); computer.click(1, 2); computer.move(3, 4)
    computer.scroll("down"); computer.type("hello"); computer.key(["CTRL", "L"])
    assert all(args["id"] == "desktop" for _, args in api.calls)
    assert all(name.startswith("computer_") or name == "get_computer_info" for name, _ in api.calls)
    assert api.calls[-1][1]["key_request"].keys == ["CTRL", "L"]


def test_busy_control_error_is_propagated_without_implicit_retries():
    api = SimpleNamespace(mobile_press_button=Mock(side_effect=ApiException(status=409, reason="device_busy")))
    with pytest.raises(ApiException) as error:
        Mobile(api, "phone").press_button("home")
    assert error.value.status == 409
    assert api.mobile_press_button.call_count == 1


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), True])
def test_invalid_timeout_rejected_before_io(timeout):
    api = RecordingApi()
    with pytest.raises(ValueError, match="timeout"):
        Mobile(api, "phone").info(timeout=timeout)
    assert api.calls == []
