"""Parser for Tribunale di Firenze — Sezione Fallimentare.

Thin subclass of :class:`ItalianTribunaleParser`. Status: **unverified**
(ADR-0006).
"""

from __future__ import annotations

from services.extract.parsers.it._tribunale_base import ItalianTribunaleParser


class TribunaleFirenzeParser(ItalianTribunaleParser):
    PARSER_ID = "parsers.it.tribunale_firenze_v1"
    VERSION = "1.0.0"
    COURT_NAME = "Tribunale di Firenze — Sezione Fallimentare"
