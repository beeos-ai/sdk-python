"""Read-only smoke for the unreleased resource facade; no private UI output."""

import json
import os
from beeos import BeeOS


with BeeOS() as client:
    instance = client.instance(os.environ["BEEOS_INSTANCE_ID"])
    mobile = instance.mobile
    ready = mobile.wait_ready(timeout=30)
    for action in ["screenshot", "ui_tree", "list_apps"]:
        if action not in ready.data.supported_actions:
            raise RuntimeError(f"Unsupported capability: {action}")
    tree = mobile.ui_tree()
    if not tree.data.supported or not tree.data.content.strip():
        raise RuntimeError("UI tree is empty or unsupported")
    apps = mobile.list_apps()
    if not apps.data.apps:
        raise RuntimeError("App list is empty")
    screenshot = mobile.screenshot()
    image = client.files.download(screenshot.data.file_id, max_bytes=8 * 1024 * 1024)
    if len(image) <= 100 or not image.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")):
        raise RuntimeError("Downloaded screenshot is not a PNG/JPEG")
    print(json.dumps({"sdk": "python", "ok": True, "instanceId": instance.id,
                      "checks": ["ready", "ui_tree", "list_apps", "screenshot", "authorized_file_download", "image_magic"],
                      "appCount": len(apps.data.apps), "screenshotBytes": len(image)}, indent=2))
