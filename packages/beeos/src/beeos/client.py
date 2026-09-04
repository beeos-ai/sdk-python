"""High-level BeeOS client with environment-based defaults."""

from __future__ import annotations

import os
from typing import Dict, Optional

from beeos_sdk import (
    AgentListResponse,
    AgentsApi,
    ApiClient,
    Configuration,
    CreateTaskRequest,
    TaskCreatedResponse,
    TasksApi,
)

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
    ) -> TaskCreatedResponse:
        """Submit one durable task to an agent."""
        return self._api.create_task(
            agent_id=agent_id,
            create_task_request=CreateTaskRequest(
                message=message,
                deadline_ms=deadline_ms,
                idempotency_key=idempotency_key,
                metadata=metadata,
            ),
        )


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
                )
            )

        self.api_client = api_client
        self.agents = _Agents(api_client)
        self.tasks = _Tasks(api_client)

    def close(self) -> None:
        """Release network resources owned by this client."""
        if self._owns_api_client:
            close = getattr(self.api_client, "close", None)
            if close is not None:
                close()

    def __enter__(self) -> "BeeOS":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
