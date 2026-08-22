#!/usr/bin/env python3
"""Fix OpenAPI Generator's string comparison for boolean const fields."""

from __future__ import annotations

import argparse
from pathlib import Path


REPLACEMENTS = {
    "if value not in set(['true']):": "if value is not True:",
    'raise ValueError("must be one of enum values (\'true\')")': (
        'raise ValueError("must be true")'
    ),
    "if value not in set(['false']):": "if value is not False:",
    'raise ValueError("must be one of enum values (\'false\')")': (
        'raise ValueError("must be false")'
    ),
}


def normalize(models_dir: Path) -> int:
    changed = 0
    for path in sorted(models_dir.glob("*.py")):
        original = path.read_text()
        updated = original
        for source, target in REPLACEMENTS.items():
            updated = updated.replace(source, target)
        if updated != original:
            path.write_text(updated)
            changed += 1
    return changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "models_dir",
        nargs="?",
        type=Path,
        default=Path("beeos_sdk/models"),
    )
    parser.add_argument("--require-change", action="store_true")
    args = parser.parse_args()

    changed = normalize(args.models_dir)
    if args.require_change and changed == 0:
        raise SystemExit("no generated boolean const validators were normalized")
    print(f"normalized boolean const validators in {changed} model files")


if __name__ == "__main__":
    main()
