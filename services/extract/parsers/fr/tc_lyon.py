"""Parser for Tribunal de Commerce de Lyon.

Thin subclass of :class:`GreffeTribunalParser`. Status: **unverified**
(ADR-0006).
"""

from __future__ import annotations

from services.extract.parsers.fr._greffe_base import GreffeTribunalParser


class TcLyonParser(GreffeTribunalParser):
    PARSER_ID = "parsers.fr.tc_lyon_v1"
    VERSION = "1.0.0"
    COURT_NAME = "Tribunal de Commerce de Lyon"
