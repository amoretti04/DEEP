"""Parser for Tribunal de Commerce de Paris.

Thin subclass of :class:`GreffeTribunalParser`. Status: **unverified**
(ADR-0006) — selectors inherited from the shared Greffe base but not
yet confirmed against a captured page from the Paris tribunal portal.
Promote via ``scripts/verify_selectors.py`` before enabling.
"""

from __future__ import annotations

from services.extract.parsers.fr._greffe_base import GreffeTribunalParser


class TcParisParser(GreffeTribunalParser):
    PARSER_ID = "parsers.fr.tc_paris_v1"
    VERSION = "1.0.0"
    COURT_NAME = "Tribunal de Commerce de Paris"
