"""Parser for Tribunale di Torino — Sezione Fallimentare.

Thin subclass of :class:`ItalianTribunaleParser`. Status: **unverified**
(ADR-0006).
"""

from __future__ import annotations

from services.extract.parsers.it._tribunale_base import ItalianTribunaleParser


class TribunaleTorinoParser(ItalianTribunaleParser):
    PARSER_ID = "parsers.it.tribunale_torino_v1"
    VERSION = "1.0.0"
    COURT_NAME = "Tribunale di Torino — Sezione Fallimentare"
