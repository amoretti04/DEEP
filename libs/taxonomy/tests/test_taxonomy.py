"""Tests for the source-category and proceeding-type normalizers.

The yaml files are structurally validated on load, so one class of bugs
is caught by ``_load_map`` itself — these tests cover the behavior.
"""

from __future__ import annotations

import pytest

from libs.taxonomy import (
    SourceCategory,
    UnifiedProceedingType,
    map_proceeding_type,
    map_source_category,
)


# ══ Categories ═══════════════════════════════════════════════════════
class TestSourceCategories:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            # Exact matches
            ("Bankruptcy Tribunal", SourceCategory.COURT),
            ("Insolvency Court", SourceCategory.COURT),
            ("Commercial Court", SourceCategory.COURT),
            ("Official Insolvency Register", SourceCategory.INS_REG),
            ("Cantonal Debt Enforcement Office", SourceCategory.INS_REG),
            ("StaRUG Register", SourceCategory.INS_REG),
            ("Provincial Official Gazette", SourceCategory.GAZ),
            ("Autonomous Community Gazette", SourceCategory.GAZ),
            ("Judicial Auction Aggregator", SourceCategory.AUCT),
            ("Industrial / Insolvency Auction", SourceCategory.AUCT),
            ("Company Registry", SourceCategory.REG),
            ("Commercial Register", SourceCategory.REG),
            ("Credit Bureau", SourceCategory.CRED),
            ("Business Information", SourceCategory.CRED),
            ("Financial Newspaper", SourceCategory.NEWS),
            ("Securities Regulator", SourceCategory.REGU),
            ("Central Bank", SourceCategory.REGU),
            ("Stock Exchange", SourceCategory.MKT),
            ("Financial Terminal", SourceCategory.MKT),
        ],
    )
    def test_exact_mapping(self, raw: str, expected: SourceCategory) -> None:
        assert map_source_category(raw) is expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Some Unknown Gazette Type", SourceCategory.GAZ),
            ("Strange Tribunal Label", SourceCategory.COURT),
            ("Weird Regional Auction House", SourceCategory.AUCT),
            ("Tiny Local Regulator", SourceCategory.REGU),
        ],
    )
    def test_pattern_fallback(self, raw: str, expected: SourceCategory) -> None:
        assert map_source_category(raw) is expected

    def test_case_and_whitespace_insensitive(self) -> None:
        assert map_source_category("  BANKRUPTCY   TRIBUNAL  ") is SourceCategory.COURT

    def test_unknown_for_empty(self) -> None:
        assert map_source_category("") is SourceCategory.UNKNOWN
        assert map_source_category(None) is SourceCategory.UNKNOWN
        assert map_source_category("   ") is SourceCategory.UNKNOWN

    def test_unknown_for_unmappable(self) -> None:
        # Deliberately semantic-free strings — must NOT silently bucket.
        assert map_source_category("xyzzy foo bar") is SourceCategory.UNKNOWN


# ══ Proceedings ══════════════════════════════════════════════════════
class TestProceedings:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            # IT
            ("Liquidazione giudiziale", UnifiedProceedingType.LIQUIDATION),
            ("Fallimento", UnifiedProceedingType.LIQUIDATION),
            ("Concordato preventivo", UnifiedProceedingType.REORGANIZATION),
            ("Composizione negoziata", UnifiedProceedingType.REORGANIZATION),
            ("Accordo di ristrutturazione", UnifiedProceedingType.MORATORIUM),
            # DE
            ("Regelinsolvenzverfahren", UnifiedProceedingType.LIQUIDATION),
            ("Schutzschirmverfahren", UnifiedProceedingType.REORGANIZATION),
            ("StaRUG-Verfahren", UnifiedProceedingType.MORATORIUM),
            # FR
            ("Liquidation judiciaire", UnifiedProceedingType.LIQUIDATION),
            ("Redressement judiciaire", UnifiedProceedingType.REORGANIZATION),
            ("Mandat ad hoc", UnifiedProceedingType.MORATORIUM),
            # ES
            ("Concurso en liquidación", UnifiedProceedingType.LIQUIDATION),
            ("Concurso con convenio", UnifiedProceedingType.REORGANIZATION),
            ("Preconcurso", UnifiedProceedingType.MORATORIUM),
            # UK
            ("Administration", UnifiedProceedingType.REORGANIZATION),
            ("CVA", UnifiedProceedingType.REORGANIZATION),
            ("Receivership", UnifiedProceedingType.RECEIVERSHIP),
            ("Administrative receivership", UnifiedProceedingType.RECEIVERSHIP),
            ("Creditors Voluntary Liquidation", UnifiedProceedingType.LIQUIDATION),
            # NL
            ("Faillissement", UnifiedProceedingType.LIQUIDATION),
            ("WHOA", UnifiedProceedingType.REORGANIZATION),
            ("Surseance van betaling", UnifiedProceedingType.MORATORIUM),
            # CH
            ("Konkurs", UnifiedProceedingType.LIQUIDATION),
            ("Nachlassverfahren", UnifiedProceedingType.REORGANIZATION),
            ("Nachlassstundung", UnifiedProceedingType.MORATORIUM),
        ],
    )
    def test_exact(self, raw: str, expected: UnifiedProceedingType) -> None:
        assert map_proceeding_type(raw) is expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Some novel reorganization procedure", UnifiedProceedingType.REORGANIZATION),
            ("Voluntary liquidation", UnifiedProceedingType.LIQUIDATION),
            ("Interim moratorium", UnifiedProceedingType.MORATORIUM),
        ],
    )
    def test_pattern(self, raw: str, expected: UnifiedProceedingType) -> None:
        assert map_proceeding_type(raw) is expected

    def test_unknown(self) -> None:
        assert map_proceeding_type(None) is UnifiedProceedingType.UNKNOWN
        assert map_proceeding_type("") is UnifiedProceedingType.UNKNOWN
        assert map_proceeding_type("xyzzy") is UnifiedProceedingType.UNKNOWN
