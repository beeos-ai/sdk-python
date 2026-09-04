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
