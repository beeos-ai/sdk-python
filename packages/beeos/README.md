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
import beeos

configuration = beeos.Configuration(
    host="https://openapi.beeos.ai",
    access_token="oag_your_api_key",
)

with beeos.ApiClient(configuration) as client:
    tasks = beeos.sdk.TasksApi(client)
    response = tasks.create_task(
        agent_id="agent-id",
        create_task_request=beeos.sdk.CreateTaskRequest(
            message="Open Settings",
        ),
    )
    print(response)
```

Use `beeos.sdk` when you need the complete generated API and model surface.
You can also install and import `beeos-sdk` / `beeos_sdk` directly.
