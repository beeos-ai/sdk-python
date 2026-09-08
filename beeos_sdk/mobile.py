"""Stable task-first helpers for BeeOS Android runtimes."""

from __future__ import annotations

import time
import math
from collections.abc import Iterator
from typing import Optional

from beeos_sdk.api.mobile_api import MobileApi
from beeos_sdk._lifecycle import close_api_client
from beeos_sdk.api.tasks_api import TasksApi
from beeos_sdk.api_client import ApiClient
from beeos_sdk.configuration import Configuration
from beeos_sdk.models.cancel_task_request import CancelTaskRequest
from beeos_sdk.models.create_task_request import CreateTaskRequest
from beeos_sdk.models.task_response import TaskResponse

_TERMINAL = {"completed", "failed", "canceled", "cancelled", "timeout", "rejected"}


class MobileClient:
    """Convenience client shared by Device Agent, BeeRunner, and Redroid."""

    def __init__(
        self,
        *,
        api_key: str,
        agent_id: str,
        instance_id: str,
        base_url: str = "https://openapi.beeos.ai",
        poll_interval: float = 1.0,
        api_client: Optional[ApiClient] = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        if not agent_id:
            raise ValueError("agent_id is required")
        if not instance_id:
            raise ValueError("instance_id is required")
        self.agent_id = agent_id
        self.instance_id = instance_id
        if not math.isfinite(poll_interval) or poll_interval < 0:
            raise ValueError("poll_interval must be nonnegative and finite")
        self.poll_interval = poll_interval
        self._owns_api_client = api_client is None
        self.api_client = api_client or ApiClient(
            Configuration(host=base_url.rstrip("/"), access_token=api_key, retries=False)
        )
        self.mobile = MobileApi(self.api_client)
        self.tasks = TasksApi(self.api_client)

    def close(self) -> None:
        if self._owns_api_client:
            close_api_client(self.api_client)

    def __enter__(self) -> "MobileClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def wait_ready(self, timeout: float = 60.0):
        """Wait until the atomic mobile surface reports the runtime online."""
        deadline = time.monotonic() + _timeout(timeout)
        while True:
            response = self.mobile.get_mobile_info(id=self.instance_id, _request_timeout=_remaining(deadline))
            _remaining(deadline)
            if response.data is not None and response.data.online:
                return response
            if time.monotonic() >= deadline:
                raise TimeoutError("mobile runtime did not become ready before timeout")
            time.sleep(min(self.poll_interval, _remaining(deadline)))

    def run(
        self,
        message: str,
        *,
        timeout: float = 120.0,
        idempotency_key: Optional[str] = None,
    ) -> TaskResponse:
        """Submit one durable phone task and wait for its terminal snapshot."""
        deadline = time.monotonic() + _timeout(timeout)
        created = self.tasks.create_task(
            agent_id=self.agent_id,
            create_task_request=CreateTaskRequest(
                message=message,
                deadline_ms=max(0, int(timeout * 1000)),
                idempotency_key=idempotency_key,
            ),
            _request_timeout=_remaining(deadline),
        )
        while True:
            snapshot = self.tasks.get_task(
                agent_id=self.agent_id,
                task_id=created.data.task_id,
                _request_timeout=_remaining(deadline),
            )
            _remaining(deadline)
            _validate_snapshot(snapshot, self.agent_id, created.data.task_id)
            if _status_value(snapshot) in _TERMINAL:
                return snapshot
            if time.monotonic() >= deadline:
                raise TimeoutError(f"task {created.data.task_id} did not finish before timeout")
            time.sleep(min(self.poll_interval, _remaining(deadline)))

    def watch(self, task_id: str, timeout: float = 120.0) -> Iterator[TaskResponse]:
        """Yield changed task snapshots until a terminal state is reached."""
        deadline = time.monotonic() + _timeout(timeout)
        previous = None
        while True:
            snapshot = self.tasks.get_task(agent_id=self.agent_id, task_id=task_id, _request_timeout=_remaining(deadline))
            _remaining(deadline)
            _validate_snapshot(snapshot, self.agent_id, task_id)
            status = _status_value(snapshot)
            if status != previous:
                yield snapshot
                previous = status
            if status in _TERMINAL:
                return
            if time.monotonic() >= deadline:
                raise TimeoutError(f"task {task_id} did not finish before timeout")
            time.sleep(min(self.poll_interval, _remaining(deadline)))

    def cancel(self, task_id: str, reason: Optional[str] = None, *, timeout: float = 30.0) -> TaskResponse:
        request = CancelTaskRequest(reason=reason) if reason else None
        return self.tasks.cancel_task(
            agent_id=self.agent_id,
            task_id=task_id,
            cancel_task_request=request,
            _request_timeout=_timeout(timeout),
        )


def _status_value(snapshot: TaskResponse) -> str:
    status = snapshot.data.status
    return status.value if hasattr(status, "value") else str(status)


def _timeout(value: float) -> float:
    if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        raise ValueError("timeout must be positive and finite")
    return float(value)


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("BeeOS wait timed out; the remote task was not automatically cancelled")
    return remaining


def _validate_snapshot(snapshot: TaskResponse, agent_id: str, task_id: str) -> None:
    if snapshot.data.agent_id != agent_id or snapshot.data.task_id != task_id:
        raise ValueError("Task response identity does not match the requested task")
    if getattr(snapshot.data, "truncated", False):
        raise ValueError("Task snapshot is truncated; use the event stream for the authoritative tail")
