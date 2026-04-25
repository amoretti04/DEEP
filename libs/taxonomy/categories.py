"""Normalize the blueprint's free-text categories onto the 9 canonical codes.

Loads ``source_category_map.yaml`` at import time. Exact match wins; if no
exact match, the first keyword pattern that matches applies; otherwise
:class:`SourceCategory.UNKNOWN` is returned and the importer routes the
row to a human review queue.

The mapping file is the source of truth — *do not* hard-code additional
rules in Python. Anyone adding a source who hits UNKNOWN should either
(a) add an exact-match entry or (b) extend a pattern, with a PR that
includes the workbook row that triggered the gap.
"""

from __future__ import annotations

import re
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Final

import yaml


class SourceCategory(str, Enum):
    """The 9 canonical source categories from CLAUDE.md §5.1 plus UNKNOWN."""

    GAZ = "GAZ"
    COURT = "COURT"
    INS_REG = "INS-REG"
    AUCT = "AUCT"
    REG = "REG"
    CRED = "CRED"
    NEWS = "NEWS"
    REGU = "REGU"
    MKT = "MKT"
    UNKNOWN = "UNKNOWN"


CATEGORY_CODES: Final[frozenset[str]] = frozenset(
    c.value for c in SourceCategory if c is not SourceCategory.UNKNOWN
)

_MAP_PATH = Path(__file__).parent / "source_category_map.yaml"
_WS_RE = re.compile(r"\s+")


def _normalize(raw: str) -> str:
    """Lowercase, collapse whitespace, strip — match the map keys."""
    return _WS_RE.sub(" ", raw.strip().lower())


def _code_to_enum(code: str) -> SourceCategory:
    # YAML uses the dashed form for INS-REG; Python enum uses underscore.
    if code == "INS-REG":
        return SourceCategory.INS_REG
    return SourceCategory(code)


@lru_cache(maxsize=1)
def _load_map() -> tuple[dict[str, SourceCategory], list[tuple[list[str], SourceCategory]]]:
    """Return (exact_map, patterns_list). Cached for the process lifetime."""
    with _MAP_PATH.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)

    # Validate: codes section must contain exactly the 9 canonical codes.
    declared = set(data["codes"].keys())
    expected = {c.value if c is not SourceCategory.INS_REG else "INS-REG"
                for c in SourceCategory if c is not SourceCategory.UNKNOWN}
    if declared != expected:
        missing = expected - declared
        extra = declared - expected
        raise ValueError(
            f"source_category_map.yaml codes mismatch: "
            f"missing={sorted(missing)} extra={sorted(extra)}"
        )

    exact: dict[str, SourceCategory] = {
        _normalize(k): _code_to_enum(v) for k, v in data.get("exact", {}).items()
    }
    patterns: list[tuple[list[str], SourceCategory]] = [
        ([str(s).lower() for s in entry["contains"]], _code_to_enum(entry["code"]))
        for entry in data.get("patterns", [])
    ]
    return exact, patterns


def map_source_category(raw_category: str | None) -> SourceCategory:
    """Map a workbook free-text category to a canonical :class:`SourceCategory`.

    Returns :attr:`SourceCategory.UNKNOWN` if neither an exact match nor any
    pattern applies — callers MUST treat UNKNOWN as a review signal, never
    silently coerce to a default.
    """
    if not raw_category or not raw_category.strip():
        return SourceCategory.UNKNOWN

    normalized = _normalize(raw_category)
    exact, patterns = _load_map()

    if (hit := exact.get(normalized)) is not None:
        return hit

    for keywords, code in patterns:
        if any(kw in normalized for kw in keywords):
            return code

    return SourceCategory.UNKNOWN
