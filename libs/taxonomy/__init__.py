"""Unified taxonomies.

Two concerns live here, kept separate on purpose:

1. **Source categories** (:mod:`libs.taxonomy.categories`) — the ~200
   free-text labels in the blueprint workbook collapse to the 9 codes
   in CLAUDE.md §5.1.

2. **Proceeding types** (:mod:`libs.taxonomy.proceedings`) — local
   procedural labels ("Concordato preventivo", "Schutzschirmverfahren",
   "Chapter 15 recognition", …) map onto the unified set in PRD §11.2.

Both are versioned YAML files checked into the repo so changes show up
as diffs, not mystery.
"""

from libs.taxonomy.categories import (
    CATEGORY_CODES,
    SourceCategory,
    map_source_category,
)
from libs.taxonomy.proceedings import (
    UnifiedProceedingType,
    map_proceeding_type,
)

__all__ = [
    "CATEGORY_CODES",
    "SourceCategory",
    "UnifiedProceedingType",
    "map_proceeding_type",
    "map_source_category",
]
