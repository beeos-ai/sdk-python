from types import SimpleNamespace

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
