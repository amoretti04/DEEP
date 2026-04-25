"""Normalize local proceeding labels to the unified PRD §11.2 taxonomy.

Parsers emit whatever the source says verbatim (``proceeding_type_original``)
and a normalized code (``proceeding_type``). The normalized code is what the
UI groups by, what scoring rules key off, and what cross-jurisdiction
analytics compare.

The mapping is in ``proceedings.yaml``; this module loads and applies it.
"""

from __future__ import annotations

import re
from enum import Enum
from functools import lru_cache
from pathlib import Path

import yaml


class UnifiedProceedingType(str, Enum):
    """PRD §11.2 unified proceeding taxonomy."""

    REORGANIZATION = "REORGANIZATION"
    LIQUIDATION = "LIQUIDATION"
    MORATORIUM = "MORATORIUM"
    RECEIVERSHIP = "RECEIVERSHIP"
    UNKNOWN = "UNKNOWN"


_MAP_PATH = Path(__file__).parent / "proceedings.yaml"
_WS_RE = re.compile(r"\s+")


def _normalize(raw: str) -> str:
    return _WS_RE.sub(" ", raw.strip().lower())


@lru_cache(maxsize=1)
def _load_map() -> tuple[
    dict[str, UnifiedProceedingType],
    list[tuple[list[str], UnifiedProceedingType]],
]:
    with _MAP_PATH.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)

    declared = set(data["codes"].keys())
    expected = {
        c.value for c in UnifiedProceedingType if c is not UnifiedProceedingType.UNKNOWN
    }
    if declared != expected:
        raise ValueError(
            f"proceedings.yaml codes mismatch: "
            f"missing={sorted(expected - declared)} "
            f"extra={sorted(declared - expected)}"
        )

    exact = {
        _normalize(k): UnifiedProceedingType(v)
        for k, v in data.get("exact", {}).items()
    }
    patterns = [
        (
            [str(s).lower() for s in entry["contains"]],
            UnifiedProceedingType(entry["code"]),
        )
        for entry in data.get("patterns", [])
    ]
    return exact, patterns


def map_proceeding_type(raw_label: str | None) -> UnifiedProceedingType:
    """Map a local proceeding label onto the unified code.

    Returns ``UNKNOWN`` if neither exact nor pattern matches — caller MUST
    treat UNKNOWN as a signal to route the record to the review queue.
    """
    if not raw_label or not raw_label.strip():
        return UnifiedProceedingType.UNKNOWN

    normalized = _normalize(raw_label)
    exact, patterns = _load_map()

    if (hit := exact.get(normalized)) is not None:
        return hit

    for keywords, code in patterns:
        if any(kw in normalized for kw in keywords):
            return code

    return UnifiedProceedingType.UNKNOWN
