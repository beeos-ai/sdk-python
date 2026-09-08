"""High-level BeeOS client with environment-based defaults."""

from __future__ import annotations

import os
import time
from typing import Dict, Optional

from beeos_sdk import (
    AgentListResponse,
    AgentsApi,
    ApiClient,
    Configuration,
    CancelTaskRequest,
    CreateTaskRequest,
    TaskCreatedResponse,
    TasksApi,
)
from .resources import Instances, Task, call, require_id, timeout_seconds
from .files import Files
from .streams import parse_events, read_chunk

_DEFAULT_API_URL = "https://openapi.beeos.ai"


class _Agents:
    def __init__(self, api_client: ApiClient) -> None:
        self._api = AgentsApi(api_client)

    def list(
        self,
        *,
        instance_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> AgentListResponse:
        """List agents owned by the current BeeOS account."""
        return self._api.list_agents(
            instance_id=instance_id,
            status=status,
            limit=limit,
            offset=offset,
        )


class _Tasks:
    def __init__(self, api_client: ApiClient) -> None:
        self._api = TasksApi(api_client)

    def create(
        self,
        *,
        agent_id: str,
        message: str,
        deadline_ms: Optional[int] = None,
        idempotency_key: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
        timeout: float = 30.0,
    ) -> TaskCreatedResponse:
        """Submit one durable task to an agent."""
        return call(self._api.create_task,
            agent_id=agent_id,
            create_task_request=CreateTaskRequest(
                message=message,
                deadline_ms=deadline_ms,
                idempotency_key=idempotency_key,
                metadata=metadata,
            ),
            timeout=timeout,
        )

    def get(self, *, agent_id: str, task_id: str, timeout: float = 30.0):
        return call(self._api.get_task, agent_id=require_id(agent_id, "agent_id"),
                    task_id=require_id(task_id, "task_id"), timeout=timeout)

    def wait(self, *, agent_id: str, task_id: str, timeout=120.0, poll_interval=1.0, require_success=True):
        return Task(self, agent_id, task_id).wait(timeout=timeout, poll_interval=poll_interval, require_success=require_success)

    def cancel(self, *, agent_id: str, task_id: str, reason=None, timeout=30.0):
        return call(self._api.cancel_task, agent_id=require_id(agent_id, "agent_id"),
                    task_id=require_id(task_id, "task_id"), cancel_task_request=CancelTaskRequest(reason=reason), timeout=timeout)

    def messages(self, *, agent_id: str, task_id: str, since=None, limit=None, include_deltas=False, timeout=30.0):
        return call(self._api.list_task_messages, agent_id=require_id(agent_id, "agent_id"),
                    task_id=require_id(task_id, "task_id"), since=since, limit=limit,
                    include_deltas=include_deltas, timeout=timeout)

    def events(self, *, agent_id: str, task_id: str, since=0, timeout=120.0):
        """Yield raw SSE frames; close the generator when stopping consumption early.

        Persist each event's offset and resume explicitly with ``since``. A local
        timeout or closed stream neither cancels nor resubmits the remote task.
        """
        deadline = time.monotonic() + timeout_seconds(timeout)
        response = call(self._api.stream_task_events_without_preload_content,
                        agent_id=require_id(agent_id, "agent_id"), task_id=require_id(task_id, "task_id"),
                        since=since, timeout=timeout)
        try:
            if not 200 <= response.status < 300:
                from beeos_sdk.exceptions import ApiException
                raise ApiException(status=response.status, reason="Task event stream failed")
            if response.headers.get("Content-Type", "").split(";")[0].strip().lower() != "text/event-stream":
                raise ValueError("Task event stream did not return text/event-stream")

            def chunks():
                while True:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Task event stream timed out; the remote task was not cancelled")
                    chunk = read_chunk(response, 65536, streaming=True)
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Task event stream timed out; the remote task was not cancelled")
                    if not chunk:
                        return
                    yield chunk

            for event in parse_events(chunks()):
                yield event
                if event.event == "end":
                    return
        finally:
            response.close()
            response.release_conn()


class BeeOS:
    """Convenient entry point for the BeeOS Platform API.

    By default the client reads ``BEEOS_API_KEY`` and ``BEEOS_API_URL``.
    Constructor arguments override their corresponding environment variables.
    """

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        api_client: Optional[ApiClient] = None,
    ) -> None:
        if api_client is not None and (api_key is not None or base_url is not None):
            raise ValueError("api_client cannot be combined with api_key or base_url")

        self._owns_api_client = api_client is None
        if api_client is None:
            resolved_api_key = api_key or os.getenv("BEEOS_API_KEY")
            if not resolved_api_key:
                raise ValueError(
                    "BeeOS API key is required; pass api_key or set BEEOS_API_KEY"
                )
            resolved_base_url = (
                base_url or os.getenv("BEEOS_API_URL") or _DEFAULT_API_URL
            )
            api_client = ApiClient(
                Configuration(
                    host=resolved_base_url.rstrip("/"),
                    access_token=resolved_api_key,
                    retries=False,
                )
            )

        self.api_client = api_client
        self.agents = _Agents(api_client)
        self.tasks = _Tasks(api_client)
        self.instances = Instances(self)
        self.files = Files(api_client)

    def instance(self, instance_id: str):
        """Bind a local resource handle without creating or fetching an instance."""
        return self.instances.ref(instance_id)

    def task(self, agent_id: str, task_id: str):
        """Resume an existing task without submitting another prompt."""
        return Task(self.tasks, agent_id, task_id)

    def close(self) -> None:
        """Release network resources owned by this client."""
        if self._owns_api_client:
            close = getattr(self.api_client, "close", None)
            if callable(close):
                close()
            else:
                # Also support the published generated SDK, whose __exit__ is
                # a no-op. Do not require an unreleased private SDK helper.
                rest = getattr(self.api_client, "rest_client", None)
                pool = getattr(rest, "pool_manager", None)
                clear = getattr(pool, "clear", None)
                if callable(clear):
                    clear()

    def __enter__(self) -> "BeeOS":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
