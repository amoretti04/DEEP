"""Schema invariants — every canonical entity must carry source references.

Plus targeted tests for the scope-gate fields on Source, the Money type,
and the SourceReference cross-check.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from libs.provenance import build_envelope, new_ulid
from libs.schemas import (
    Asset,
    AssetClass,
    Company,
    CompanyIdentifier,
    ConnectorType,
    Country,
    FetchMode,
    IdentifierScheme,
    JurisdictionClass,
    Language,
    LegalReviewStatus,
    Money,
    Proceeding,
    ProceedingStatus,
    Source,
    SourceReference,
    SourceSchedule,
    Tier,
)
from libs.taxonomy import SourceCategory, UnifiedProceedingType


def _envelope(source_id: str = "it-test-source") -> object:
    return build_envelope(
        source_id=source_id,
        source_url="https://example.com/a",
        stable_natural_key="nk-1",
        fetched_at_utc=datetime(2026, 4, 21, tzinfo=UTC),
        published_at_local=datetime(2026, 4, 21, 9, 0, tzinfo=UTC),
        raw_object_key=f"{source_id}/2026/04/21/{'a' * 64}.html",
        raw_sha256="a" * 64,
        parser_version="it.test_v1.0.0",
        extractor_run_id=new_ulid(),
        data_owner="team",
        legal_basis="LIA on file",
    )


def _ref(source_id: str = "it-test-source") -> SourceReference:
    return SourceReference(envelope=_envelope(source_id), source_id=source_id)  # type: ignore[arg-type]


# ── Money ─────────────────────────────────────────────────────────────
class TestMoney:
    def test_valid(self) -> None:
        m = Money(amount=Decimal("1234.56"), currency="EUR")
        assert m.currency == "EUR"
        assert m.amount == Decimal("1234.56")

    def test_rejects_lowercase(self) -> None:
        # Policy: ISO 4217 is uppercase; callers normalize at their boundary.
        with pytest.raises(ValidationError):
            Money(amount=Decimal("1"), currency="eur")

    def test_rejects_bad_currency(self) -> None:
        with pytest.raises(ValidationError):
            Money(amount=Decimal("1"), currency="EURO")

    def test_rejects_negative(self) -> None:
        with pytest.raises(ValidationError):
            Money(amount=Decimal("-1"), currency="EUR")


# ── SourceReference cross-check ──────────────────────────────────────
class TestSourceReference:
    def test_valid(self) -> None:
        ref = _ref("it-milano")
        assert ref.source_id == "it-milano"

    def test_mismatch_raises(self) -> None:
        env = _envelope("it-milano")
        with pytest.raises(ValueError, match="must equal"):
            SourceReference(envelope=env, source_id="it-roma")  # type: ignore[arg-type]


# ── Source ────────────────────────────────────────────────────────────
class TestSource:
    def _base_kwargs(self) -> dict[str, object]:
        return dict(
            source_id="it-tribunale-milano-fallimenti",
            name="Tribunale di Milano — Sezione Fallimentare",
            workbook_country="Italy",
            workbook_category="Bankruptcy Tribunal",
            workbook_row=4,
            country=Country.IT,
            language=Language.IT,
            tier=Tier.T1,
            category=SourceCategory.COURT,
            jurisdiction_class=JurisdictionClass.EU_GDPR,
            connector=ConnectorType.HTTP_SCRAPE,
            fetch_mode=FetchMode.LIST_AND_DETAIL,
            base_url="https://www.tribunale.milano.giustizia.it/",
            schedule=SourceSchedule(cron="0 */3 * * *", timezone="Europe/Rome"),
            in_priority_scope=True,
        )

    def test_valid(self) -> None:
        s = Source(**self._base_kwargs())  # type: ignore[arg-type]
        assert s.country is Country.IT
        assert s.legal_review.verdict is LegalReviewStatus.PENDING
        assert s.enabled is False

    def test_rejects_malformed_source_id(self) -> None:
        kw = self._base_kwargs()
        kw["source_id"] = "IT Tribunale Milano"  # spaces + caps
        with pytest.raises(ValidationError):
            Source(**kw)  # type: ignore[arg-type]

    def test_politeness_delay_ordering(self) -> None:
        from libs.schemas.source import Politeness
        kw = self._base_kwargs()
        kw["politeness"] = Politeness(min_delay_s=10.0, max_delay_s=5.0)
        with pytest.raises(ValidationError, match="max_delay_s"):
            Source(**kw)  # type: ignore[arg-type]


# ── Canonical entities must carry ≥ 1 source_ref ─────────────────────
class TestSourceRefRequirement:
    """
    CLAUDE.md §4.2 / §11: every canonical entity carries ≥ 1 source_ref.
    Regression lock: if someone later relaxes one of these, this test
    fails and forces them to either fix it or write an ADR.
    """

    def test_company_requires_ref(self) -> None:
        with pytest.raises(ValidationError):
            Company(
                company_pid=new_ulid(),
                legal_name="Test SpA",
                country=Country.IT,
                source_references=[],
            )

    def test_proceeding_requires_ref(self) -> None:
        with pytest.raises(ValidationError):
            Proceeding(
                proceeding_pid=new_ulid(),
                company_pid=new_ulid(),
                jurisdiction=Country.IT,
                proceeding_type=UnifiedProceedingType.LIQUIDATION,
                proceeding_type_original="Liquidazione giudiziale",
                status=ProceedingStatus.OPEN,
                source_references=[],
            )

    def test_asset_requires_ref(self) -> None:
        with pytest.raises(ValidationError):
            Asset(
                asset_pid=new_ulid(),
                proceeding_pid=new_ulid(),
                asset_class=AssetClass.GOING_CONCERN_BUSINESS,
                tied_to_operating_business=True,
                description_original="Ramo d'azienda",
                source_references=[],
            )


# ── Identifiers ───────────────────────────────────────────────────────
class TestCompanyIdentifier:
    def test_valid_lei(self) -> None:
        cid = CompanyIdentifier(
            scheme=IdentifierScheme.LEI, value="529900T8BM49AURSDO55"
        )
        assert cid.scheme is IdentifierScheme.LEI

    def test_multiple_on_company(self) -> None:
        c = Company(
            company_pid=new_ulid(),
            legal_name="Test SpA",
            country=Country.IT,
            identifiers=[
                CompanyIdentifier(
                    scheme=IdentifierScheme.LEI,
                    value="529900T8BM49AURSDO55",
                ),
                CompanyIdentifier(
                    scheme=IdentifierScheme.CODICE_FISCALE,
                    value="01234567890",
                ),
                CompanyIdentifier(
                    scheme=IdentifierScheme.VAT, value="IT01234567890"
                ),
            ],
            source_references=[_ref()],
        )
        assert len(c.identifiers) == 3


# ── Proceeding unified taxonomy ──────────────────────────────────────
def test_proceeding_preserves_original_label() -> None:
    p = Proceeding(
        proceeding_pid=new_ulid(),
        company_pid=new_ulid(),
        jurisdiction=Country.IT,
        proceeding_type=UnifiedProceedingType.LIQUIDATION,
        proceeding_type_original="Liquidazione giudiziale",
        opened_at=date(2026, 4, 20),
        status=ProceedingStatus.OPEN,
        source_references=[_ref()],
    )
    assert p.proceeding_type is UnifiedProceedingType.LIQUIDATION
    assert p.proceeding_type_original == "Liquidazione giudiziale"
