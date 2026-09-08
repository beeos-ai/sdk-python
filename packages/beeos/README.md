# BeeOS for Python

`beeos` is the official Python entry point for BeeOS. It provides a stable,
convenient facade over the generated [`beeos-sdk`](https://pypi.org/project/beeos-sdk/)
Platform OpenAPI client.

## Install

```bash
python -m pip install beeos
```

## Usage

```python
from beeos import BeeOS

client = BeeOS()
agent = client.agents.list().data[0]
task = client.tasks.create(
    agent_id=agent.id,
    message="Create a promotional video for BeeOS",
)
print(task.data.task_id)
```

`BeeOS()` reads `BEEOS_API_KEY` and optionally `BEEOS_API_URL` from the
environment. Both remain explicitly configurable when needed:

```python
client = BeeOS(
    api_key="oag_your_api_key",
    base_url="https://openapi.beeos.ai",
)
```

Use the client as a context manager when its lifetime should be explicit:

```python
with BeeOS() as client:
    agents = client.agents.list()
```

Use `beeos.sdk` when you need the complete generated API and model surface:

```python
import beeos

configuration = beeos.Configuration(
    host="https://openapi.beeos.ai",
    access_token="oag_your_api_key",
)

with beeos.ApiClient(configuration) as client:
    response = beeos.sdk.AgentsApi(client).list_agents()
    print(response)
```
You can also install and import `beeos-sdk` / `beeos_sdk` directly.

## Resource Facade (Unreleased)

The methods below are local development additions, not in PyPI `beeos==0.2.0`
yet. Existing generated APIs and constructor arguments remain compatible.

```python
import os
import uuid
from beeos import BeeOS

client = BeeOS()
try:
    instance = client.instance(os.environ["BEEOS_INSTANCE_ID"])
    instance.mobile.wait_ready(timeout=60)
    info = instance.mobile.info()
    if "ui_tree" in info.data.supported_actions:
        print(instance.mobile.ui_tree(format="compact").data)

    agent_id = os.environ["BEEOS_AGENT_ID"]
    created = client.tasks.create(
        agent_id=agent_id,
        message="Open Settings and report the battery level without changing settings",
        idempotency_key=str(uuid.uuid4()),
    )
    task = client.task(agent_id, created.data.task_id)
    print(task.wait(timeout=120).data.result)
finally:
    client.close()
```

Select an agent belonging to this instance. Capability discovery is required:
the facade does not bypass runtime `action_unsupported` or `device_busy` errors.

- `client.instances.create/get/list` and `instance.start/stop/restart/destroy`
  wrap the existing lifecycle APIs. Destroy only a workflow-owned instance.
- `instance.mobile` binds screenshot/UI tree/apps/tap/drag/swipe/scroll/type/key/
  button/open-app calls; `instance.computer` binds desktop pointer/keyboard calls.
- `task.get/wait/cancel/messages/events` reuse the original task ID. `wait`
  requires `completed`; inspect `TaskExecutionError.snapshot` on other terminal
  states, or explicitly set `require_success=False`. Existing
  `beeos_sdk.MobileClient.run` retains terminal-only behavior.
- Local timeout does not cancel/resubmit the remote task. Writes are not retried
  automatically. An explicit task cancellation is a separate operation.
- `client.files.download(file_id, max_bytes=..., expected_content_type=...)`
  returns bytes, resolves authorized metadata, caps downloads at 32 MiB by
  default, and sends no API key/cookies/client certificates to object storage.
  HTTPS is required unless `allow_insecure_http=True` is explicitly set for a
  trusted local fixture. Redirects are rejected.

Consume real SSE without buffering the full response. Close early-exited
generators explicitly; leaving a Python `for` loop alone does not close them:

```python
from contextlib import closing

with closing(task.events(since=last_offset, timeout=120)) as events:
    for event in events:
        print(event.event, event.data)
        # Persist the returned offset; gaps are allowed. Handle
        # backfill_truncated explicitly before declaring recovery complete.
```

`timeout` also configures transport connect/read limits. Slow streaming reads
are checked against the elapsed budget between chunks; it is not a scheduler
deadline for the remote task. `completed` alone is not proof of a valid PDF or
other business result; validate and download the expected artifact separately.
