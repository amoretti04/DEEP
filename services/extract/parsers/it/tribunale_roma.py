"""Parser for Tribunale di Roma — Sezione Fallimentare.

Thin subclass of :class:`ItalianTribunaleParser`. Status: **unverified**
(ADR-0006) — selectors inherited from the Milano reference but not yet
confirmed against a captured page from the Rome tribunale portal.
Promote via ``scripts/verify_selectors.py`` before enabling.
"""

from __future__ import annotations

from services.extract.parsers.it._tribunale_base import ItalianTribunaleParser


class TribunaleRomaParser(ItalianTribunaleParser):
    PARSER_ID = "parsers.it.tribunale_roma_v1"
    VERSION = "1.0.0"
    COURT_NAME = "Tribunale di Roma — Sezione Fallimentare"
