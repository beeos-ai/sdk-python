from types import SimpleNamespace

import pytest
from beeos import BeeOS


class FakeApiClient:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_beeos_reads_environment_defaults(monkeypatch):
    monkeypatch.setenv("BEEOS_API_KEY", "oag_test")
    monkeypatch.setenv("BEEOS_API_URL", "https://staging.example.test/")

    client = BeeOS()
    try:
        assert client.api_client.configuration.access_token == "oag_test"
        assert client.api_client.configuration.host == "https://staging.example.test"
    finally:
        client.close()


def test_beeos_requires_api_key(monkeypatch):
    monkeypatch.delenv("BEEOS_API_KEY", raising=False)

    with pytest.raises(ValueError, match="BEEOS_API_KEY"):
        BeeOS()


def test_beeos_accepts_injected_client_without_closing_it():
    api_client = FakeApiClient()
    client = BeeOS(api_client=api_client)

    client.close()

    assert api_client.closed is False


def test_task_resource_builds_generated_request(monkeypatch):
    api_client = FakeApiClient()
    client = BeeOS(api_client=api_client)
    expected = SimpleNamespace(data=SimpleNamespace(task_id="task-1"))

    def create_task(*, agent_id, create_task_request):
        assert agent_id == "agent-1"
        assert create_task_request.message == "Create a video"
        assert create_task_request.idempotency_key == "request-1"
        return expected

    monkeypatch.setattr(client.tasks._api, "create_task", create_task)

    result = client.tasks.create(
        agent_id="agent-1",
        message="Create a video",
        idempotency_key="request-1",
    )

    assert result is expected
