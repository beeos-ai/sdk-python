"""Official Python entry point for BeeOS."""

from importlib.metadata import PackageNotFoundError, version

import beeos_sdk as sdk
from beeos_sdk import ApiClient, Configuration, MobileClient

from .client import BeeOS

try:
    __version__ = version("beeos")
except PackageNotFoundError:  # pragma: no cover - source-tree imports only
    __version__ = "0.2.0"

__all__ = ["ApiClient", "BeeOS", "Configuration", "MobileClient", "sdk"]
