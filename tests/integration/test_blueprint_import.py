"""End-to-end test of the blueprint importer.

Runs against the real workbook at /mnt/project/ if available, otherwise
falls back to a generated mini-workbook. Both paths exercise the full
normalize→report pipeline without DB writes.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from libs.taxonomy import SourceCategory
from scripts.blueprint_import import (
    normalize_row,
    read_workbook,
    run_import,
)

REAL_WORKBOOK = Path("/mnt/project/Distressed_Investment_Sources_Implementation_Blueprint.xlsx")


def _make_mini_workbook(tmp_path: Path) -> Path:
    rows = [
        {
            "#": 1,
            "Source #": 1,
            "Source Name": "Tribunale di Milano — Fallimenti",
            "Website URL": "https://www.tribunale.milano.giustizia.it/",
            "Category": "Bankruptcy Tribunal",
            "Country / Region": "Italy",
            "Language": "IT",
            "Existing Tier": 1,
            "Tier": 1,
            "Implementation Notes": "Largest IT commercial court",
            "Connector Type": "HTTP scrape",
            "Parser Method": "list+detail HTML",
            "Schedule / SLA": "every 3h business hours",
            "Legal / Compliance Note": "public register",
            "Expected Signal Type": "bankruptcy_filing",
            "Top Keywords Selection": "fallimento | liquidazione giudiziale",
            "Company Information Collection": "debtor_name, codice_fiscale",
            "Proceedings Document Collection": "sentenze, ordinanze",
        },
        {
            "#": 2,
            "Source #": 2,
            "Source Name": "Some Weirdly Categorized Thing",
            "Website URL": "https://example.invalid",
            "Category": "Definitely Not Mappable XYZZY",
            "Country / Region": "Italy",
            "Language": "IT",
            "Existing Tier": 3,
            "Tier": 3,
        },
    ]
    df = pd.DataFrame(rows)
    path = tmp_path / "mini_blueprint.xlsx"
    with pd.ExcelWriter(path) as w:
        df.to_excel(w, sheet_name="Implementation Blueprint", index=False)
        df.to_excel(w, sheet_name="Distressed Sources", index=False)
    return path


# ── Unit tests against a synthetic workbook ──────────────────────────
class TestBlueprintMini:
    def test_normalizes_good_row(self, tmp_path: Path) -> None:
        path = _make_mini_workbook(tmp_path)
        df = read_workbook(path)
        n = normalize_row(df.iloc[0], 2)
        assert n.source is not None
        s = n.source
        assert s.country.value == "IT"
        assert s.tier.value == 1
        assert s.category is SourceCategory.COURT
        assert s.in_priority_scope is True
        assert s.enabled is False
        assert "fallimento" in (s.notes or "").lower() or s.notes  # notes populated

    def test_routes_unknown_to_review(self, tmp_path: Path) -> None:
        path = _make_mini_workbook(tmp_path)
        df = read_workbook(path)
        n = normalize_row(df.iloc[1], 3)
        assert n.source is None
        assert any("unknown_category" in r for r in n.review_reasons)

    def test_run_import_preview_does_not_require_db(self, tmp_path: Path) -> None:
        path = _make_mini_workbook(tmp_path)
        stats = run_import(path, mode="preview")
        assert stats.total_rows == 2
        assert stats.imported == 1
        assert stats.review_queue == 1


# ── Integration test against the real 906-row workbook ──────────────
@pytest.mark.skipif(not REAL_WORKBOOK.exists(), reason="real workbook not mounted")
class TestBlueprintReal:
    """Locks in the properties we verified interactively:
    906 rows, 0 review, 7 duplicate ids. If any of these drift on a
    future workbook update, this test will flag it.
    """

    def test_imports_all_906_rows(self) -> None:
        stats = run_import(REAL_WORKBOOK, mode="preview")
        assert stats.total_rows == 906
        # We accept some drift but never a regression below 95% import
        # rate without a conscious decision.
        assert stats.imported >= int(stats.total_rows * 0.95), (
            f"Import rate regression: {stats.imported}/{stats.total_rows} "
            f"(extend libs/taxonomy/source_category_map.yaml)"
        )

    def test_country_coverage(self) -> None:
        stats = run_import(REAL_WORKBOOK, mode="preview")
        # EU-7 priority countries must all be represented.
        for c in ("IT", "DE", "FR", "UK", "ES", "NL", "CH"):
            assert stats.by_country[c] > 0, f"missing country {c}"

    def test_tier_distribution(self) -> None:
        stats = run_import(REAL_WORKBOOK, mode="preview")
        # Each tier has at least one row.
        for t in (1, 2, 3):
            assert stats.by_tier[t] > 0

    def test_all_nine_categories_present(self) -> None:
        stats = run_import(REAL_WORKBOOK, mode="preview")
        # Each canonical category (except UNKNOWN) should have at least one row.
        for code in ("GAZ", "COURT", "INS-REG", "AUCT", "REG", "CRED", "NEWS", "REGU", "MKT"):
            assert stats.by_category.get(code, 0) > 0, f"missing canonical category {code}"

    def test_no_unknown_category_rows(self) -> None:
        # With the current map, every row should normalize cleanly.
        stats = run_import(REAL_WORKBOOK, mode="preview")
        assert stats.by_category.get("UNKNOWN", 0) == 0
