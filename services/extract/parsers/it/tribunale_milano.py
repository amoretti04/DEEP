"""Parser for Tribunale di Milano — Sezione Fallimentare.

Thin subclass of :class:`ItalianTribunaleParser`. All Italian tribunali
share the same DOM patterns; see ``_tribunale_base.py`` for the shared
selectors. Milano was the R2 reference parser and its canary fixture is
the regression lock for the whole base.
"""

from __future__ import annotations

from services.extract.parsers.it._tribunale_base import ItalianTribunaleParser


class TribunaleMilanoParser(ItalianTribunaleParser):
    PARSER_ID = "parsers.it.tribunale_milano_v1"
    VERSION = "1.0.0"
    COURT_NAME = "Tribunale di Milano — Sezione Fallimentare"
