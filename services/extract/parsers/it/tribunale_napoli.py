"""Parser for Tribunale di Napoli — Sezione Fallimentare.

Thin subclass of :class:`ItalianTribunaleParser`. Status: **unverified**
(ADR-0006).
"""

from __future__ import annotations

from services.extract.parsers.it._tribunale_base import ItalianTribunaleParser


class TribunaleNapoliParser(ItalianTribunaleParser):
    PARSER_ID = "parsers.it.tribunale_napoli_v1"
    VERSION = "1.0.0"
    COURT_NAME = "Tribunale di Napoli — Sezione Fallimentare"
