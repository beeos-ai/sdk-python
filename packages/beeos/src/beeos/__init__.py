"""Official Python entry point for BeeOS."""

from importlib.metadata import PackageNotFoundError, version

import beeos_sdk as sdk
from beeos_sdk import ApiClient, Configuration

try:
    __version__ = version("beeos")
except PackageNotFoundError:  # pragma: no cover - source-tree imports only
    __version__ = "0.1.0"

__all__ = ["ApiClient", "Configuration", "sdk"]
