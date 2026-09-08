"""Bound resources over the generated API, without a second HTTP client."""

from __future__ import annotations

import math
import time
from typing import Optional

from beeos_sdk import (
    ComputerApi, InstancesApi, MobileApi,
    ClickRequest, DeployInstanceRequest, DragRequest, KeyRequest, LongPressRequest,
    MoveRequest, OpenAppRequest, PressButtonRequest, ScrollRequest, SwipeRequest,
    TapRequest, TypeRequest,
)

TERMINAL = {"completed", "failed", "canceled", "cancelled", "timeout", "rejected"}


def require_id(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value


def timeout_seconds(value: float) -> float:
    if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        raise ValueError("timeout must be positive and finite")
    return float(value)


def status_value(snapshot) -> str:
    value = snapshot.data.status
    return value.value if hasattr(value, "value") else str(value)


def call(method, *, timeout: float = 30.0, **kwargs):
    return method(**kwargs, _request_timeout=timeout_seconds(timeout))


def poll(get, ready, *, timeout: float, poll_interval: float = 1.0):
    deadline = time.monotonic() + timeout_seconds(timeout)
    if not math.isfinite(poll_interval) or poll_interval < 0:
        raise ValueError("poll_interval must be nonnegative and finite")
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("BeeOS wait timed out; the remote operation was not automatically cancelled")
        snapshot = get(timeout=remaining)
        if time.monotonic() >= deadline:
            raise TimeoutError("BeeOS wait timed out; the remote operation was not automatically cancelled")
        if ready(snapshot):
            return snapshot
        time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))


class TaskExecutionError(RuntimeError):
    """A task reached a non-success terminal; the snapshot remains inspectable."""

    def __init__(self, snapshot):
        self.snapshot = snapshot
        super().__init__(f"Task {snapshot.data.task_id} ended with {status_value(snapshot)}")


class Task:
    def __init__(self, tasks, agent_id: str, task_id: str):
        self._tasks = tasks
        self.agent_id = require_id(agent_id, "agent_id")
        self.id = require_id(task_id, "task_id")

    def get(self, *, timeout: float = 30.0):
        return self._tasks.get(agent_id=self.agent_id, task_id=self.id, timeout=timeout)

    def wait(self, *, timeout: float = 120.0, poll_interval: float = 1.0, require_success: bool = True):
        def ready(snapshot):
            if snapshot.data.task_id != self.id or snapshot.data.agent_id != self.agent_id:
                raise ValueError("Task response identity does not match the requested task")
            if getattr(snapshot.data, "truncated", False):
                raise ValueError("Task snapshot is truncated; resume events for the authoritative tail")
            status = status_value(snapshot)
            if status not in TERMINAL:
                return False
            if require_success and status != "completed":
                raise TaskExecutionError(snapshot)
            return True
        try:
            return poll(self.get, ready, timeout=timeout, poll_interval=poll_interval)
        except TimeoutError as error:
            raise TimeoutError(f"Task {self.id} did not finish before timeout; it was not automatically cancelled") from error

    def cancel(self, reason: Optional[str] = None, *, timeout: float = 30.0):
        return self._tasks.cancel(agent_id=self.agent_id, task_id=self.id, reason=reason, timeout=timeout)

    def messages(self, *, since=None, limit=None, include_deltas=False, timeout=30.0):
        return self._tasks.messages(agent_id=self.agent_id, task_id=self.id, since=since,
                                    limit=limit, include_deltas=include_deltas, timeout=timeout)

    def events(self, *, since=0, timeout=120.0):
        return self._tasks.events(agent_id=self.agent_id, task_id=self.id, since=since, timeout=timeout)


class Instances:
    def __init__(self, client):
        self._client = client
        self.api = InstancesApi(client.api_client)

    def ref(self, instance_id: str):
        return Instance(self._client, require_id(instance_id, "instance_id"))

    def get(self, instance_id: str, *, timeout: float = 30.0):
        return self.ref(instance_id).refresh(timeout=timeout)

    def create(self, request=None, *, timeout: float = 30.0, **parameters):
        if request is not None and parameters:
            raise ValueError("request cannot be combined with keyword instance parameters")
        if request is None:
            request = DeployInstanceRequest(**parameters)
        elif isinstance(request, dict):
            request = DeployInstanceRequest(**request)
        response = call(self.api.deploy_instance, deploy_instance_request=request, timeout=timeout)
        instance = self.ref(response.data.id)
        instance.data = response.data
        return instance

    def list(self, *, timeout: float = 30.0, **filters):
        return call(self.api.list_instances, timeout=timeout, **filters)


class Instance:
    def __init__(self, client, instance_id: str):
        self._client = client
        self.id = require_id(instance_id, "instance_id")
        self.data = None
        self._api = InstancesApi(client.api_client)
        self.mobile = Mobile(MobileApi(client.api_client), self.id)
        self.computer = Computer(ComputerApi(client.api_client), self.id)

    def refresh(self, *, timeout: float = 30.0):
        response = call(self._api.get_instance, id=self.id, timeout=timeout)
        if response.data.id != self.id:
            raise ValueError("Instance response identity does not match the requested instance")
        self.data = response.data
        return self

    def wait_ready(self, *, timeout: float = 60.0, poll_interval: float = 1.0):
        def ready(instance):
            if instance.data.status in {"failed", "error", "destroyed", "terminated"}:
                raise RuntimeError(f"Instance {self.id} cannot become ready: {instance.data.status}")
            return instance.data.status == "running" and instance.data.connectivity == "online"
        return poll(self.refresh, ready, timeout=timeout, poll_interval=poll_interval)

    def agents(self, *, timeout: float = 30.0):
        return call(self._client.agents._api.list_agents, instance_id=self.id, timeout=timeout)

    def start(self, *, timeout: float = 30.0):
        return call(self._api.start_instance, id=self.id, timeout=timeout)

    def stop(self, *, timeout: float = 30.0):
        return call(self._api.stop_instance, id=self.id, timeout=timeout)

    def restart(self, *, timeout: float = 30.0):
        return call(self._api.restart_instance, id=self.id, timeout=timeout)

    def destroy(self, *, timeout: float = 30.0):
        return call(self._api.destroy_instance, id=self.id, timeout=timeout)


class Mobile:
    def __init__(self, api, instance_id: str):
        self.api = api
        self.instance_id = require_id(instance_id, "instance_id")

    def info(self, *, timeout: float = 30.0):
        return call(self.api.get_mobile_info, id=self.instance_id, timeout=timeout)

    def wait_ready(self, *, timeout: float = 60.0, poll_interval: float = 1.0):
        return poll(self.info, lambda r: r.data is not None and r.data.online,
                    timeout=timeout, poll_interval=poll_interval)

    def screenshot(self, *, timeout: float = 30.0):
        return call(self.api.mobile_screenshot, id=self.instance_id, timeout=timeout)

    def ui_tree(self, *, query=None, format="compact", timeout=30.0):
        return call(self.api.mobile_get_ui_tree, id=self.instance_id, query=query, format=format, timeout=timeout)

    def list_apps(self, *, include_system=False, launchable_only=True, timeout=30.0):
        return call(self.api.mobile_list_apps, id=self.instance_id, include_system=include_system,
                    launchable_only=launchable_only, timeout=timeout)

    def tap(self, x: int, y: int, *, timeout: float = 30.0):
        return call(self.api.mobile_tap, id=self.instance_id, tap_request=TapRequest(x=x, y=y), timeout=timeout)

    def double_tap(self, x: int, y: int, *, timeout: float = 30.0):
        return call(self.api.mobile_double_tap, id=self.instance_id, tap_request=TapRequest(x=x, y=y), timeout=timeout)

    def long_press(self, x: int, y: int, *, duration_ms=None, timeout=30.0):
        return call(self.api.mobile_long_press, id=self.instance_id,
                    long_press_request=LongPressRequest(x=x, y=y, duration_ms=duration_ms), timeout=timeout)

    def drag(self, x1: int, y1: int, x2: int, y2: int, *, duration_ms=None, timeout=30.0):
        return call(self.api.mobile_drag, id=self.instance_id,
                    drag_request=DragRequest(x1=x1, y1=y1, x2=x2, y2=y2, duration_ms=duration_ms), timeout=timeout)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, *, duration_ms=None, timeout=30.0):
        return call(self.api.mobile_swipe, id=self.instance_id,
                    swipe_request=SwipeRequest(x1=x1, y1=y1, x2=x2, y2=y2, duration_ms=duration_ms), timeout=timeout)

    def scroll(self, direction: str, *, amount=None, x=None, y=None, timeout=30.0):
        return call(self.api.mobile_scroll, id=self.instance_id,
                    scroll_request=ScrollRequest(direction=direction, amount=amount, x=x, y=y), timeout=timeout)

    def type(self, text: str, *, submit=False, timeout=30.0):
        return call(self.api.mobile_type, id=self.instance_id, type_request=TypeRequest(text=text, submit=submit), timeout=timeout)

    def key(self, key: str, *, timeout=30.0):
        return call(self.api.mobile_key, id=self.instance_id, key_request=KeyRequest(keys=[key]), timeout=timeout)

    def press_button(self, button: str, *, timeout=30.0):
        return call(self.api.mobile_press_button, id=self.instance_id, press_button_request=PressButtonRequest(button=button), timeout=timeout)

    def open_app(self, app: str, *, timeout=30.0):
        return call(self.api.mobile_open_app, id=self.instance_id, open_app_request=OpenAppRequest(app=app), timeout=timeout)


class Computer:
    def __init__(self, api, instance_id: str):
        self.api = api
        self.instance_id = require_id(instance_id, "instance_id")

    def info(self, *, timeout=30.0):
        return call(self.api.get_computer_info, id=self.instance_id, timeout=timeout)

    def screenshot(self, *, timeout=30.0):
        return call(self.api.computer_screenshot, id=self.instance_id, timeout=timeout)

    def click(self, x: int, y: int, *, button=None, count=None, timeout=30.0):
        return call(self.api.computer_click, id=self.instance_id,
                    click_request=ClickRequest(x=x, y=y, button=button, count=count), timeout=timeout)

    def move(self, x: int, y: int, *, timeout=30.0):
        return call(self.api.computer_move, id=self.instance_id, move_request=MoveRequest(x=x, y=y), timeout=timeout)

    def scroll(self, direction: str, *, amount=None, x=None, y=None, timeout=30.0):
        return call(self.api.computer_scroll, id=self.instance_id,
                    scroll_request=ScrollRequest(direction=direction, amount=amount, x=x, y=y), timeout=timeout)

    def type(self, text: str, *, submit=False, timeout=30.0):
        return call(self.api.computer_type, id=self.instance_id, type_request=TypeRequest(text=text, submit=submit), timeout=timeout)

    def key(self, keys, *, timeout=30.0):
        return call(self.api.computer_key, id=self.instance_id,
                    key_request=KeyRequest(keys=[keys] if isinstance(keys, str) else keys), timeout=timeout)
