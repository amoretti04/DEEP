"""Validate every Source Card YAML against ``sources/_schema.yaml``.

Wired into CI as ``make sources-validate``. Any YAML under ``sources/``
(except the schema itself and READMEs) is loaded and validated. A single
failure fails the whole check so no bad card ever lands on ``main``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
SOURCES_DIR = ROOT / "sources"
SCHEMA_PATH = SOURCES_DIR / "_schema.yaml"


def main() -> int:
    if not SCHEMA_PATH.exists():
        print(f"error: {SCHEMA_PATH} missing", file=sys.stderr)
        return 2

    with SCHEMA_PATH.open(encoding="utf-8") as f:
        schema: dict[str, Any] = yaml.safe_load(f)

    validator = Draft202012Validator(schema)

    errors = 0
    checked = 0
    for path in sorted(SOURCES_DIR.rglob("*.yaml")):
        if path.name.startswith("_") or "README" in path.name:
            continue
        checked += 1
        with path.open(encoding="utf-8") as f:
            card = yaml.safe_load(f)
        if not isinstance(card, dict):
            print(f"FAIL  {path.relative_to(ROOT)}: not a mapping")
            errors += 1
            continue
        found = list(validator.iter_errors(card))
        if found:
            errors += 1
            print(f"FAIL  {path.relative_to(ROOT)}")
            for e in found:
                loc = ".".join(str(p) for p in e.absolute_path) or "<root>"
                print(f"        at {loc}: {e.message}")
        else:
            print(f"ok    {path.relative_to(ROOT)}")

    print("─" * 60)
    print(f"{checked} card(s) checked, {errors} failed")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
