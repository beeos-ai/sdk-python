# beeos-sdk

Python client for the BeeOS OpenAPI contract served by
[`openapi-gateway`](https://github.com/beeos-ai/openagent/tree/main/backend/services/openapi-gateway).

This package is generated from
[`backend/openapi/beeos-platform-v1.yaml`](https://github.com/beeos-ai/openagent/blob/main/backend/openapi/beeos-platform-v1.yaml)
with [OpenAPI Generator](https://openapi-generator.tech). The generated
client is the public API; do not edit generated files manually.

## Install

```bash
python -m pip install beeos-sdk
```

## Usage

```python
import beeos_sdk

configuration = beeos_sdk.Configuration(
    host="https://openapi.beeos.ai",
    access_token="oag_your_api_key",
)

with beeos_sdk.ApiClient(configuration) as client:
    tasks = beeos_sdk.TasksApi(client)
    response = tasks.create_task(
        agent_id="agent-id",
        create_task_request=beeos_sdk.CreateTaskRequest(message="Open Settings"),
    )
    print(response)
```

Authentication uses `Authorization: Bearer <jwt>` or
`Authorization: Bearer <oag_user_api_key>` through the generated
`Configuration`.

For phone automation across Device Agent, BeeRunner, and Redroid:

```python
from beeos_sdk import MobileClient

with MobileClient(
    api_key="oag_your_api_key",
    agent_id="agent-id",
    instance_id="instance-id",
) as mobile:
    mobile.wait_ready()
    result = mobile.run("Open Settings")
```

`mobile.mobile` exposes the generated atomic-control API. BeeRunner uses the
durable task methods and does not advertise atomic control until a trusted
Portal adapter exists.

## Regenerate

Maintainers regenerate this repository from the `openagent` workspace:

```bash
cd sdks/openapi-sdk
make sync-spec
make gen
```

This repository is synchronized from the `openagent` SDK generation workflow.
