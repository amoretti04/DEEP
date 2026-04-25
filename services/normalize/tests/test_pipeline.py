"""Tests for the R3 normalizer.

Covers:
* Happy path — ParsedRecord → Company + Proceeding + Event + Refs + ParsedFields.
* Idempotency — same record_uid twice, no duplicate rows.
* Cross-source linkage — two different record_uids for the same proceeding
  create one Proceeding + two SourceReferences (minimal R3 resolution on
  (jurisdiction, court_case_number)).
* Company resolution by external ID — repeat debtor codice_fiscale
  across two different proceedings → one Company, two Proceedings.
* Invariant enforcement — missing required canonical fields raises.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from sqlalchemy import JSON, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from infra.alembic.orm import (
    Base,
    CompanyIdentifierOrm,
    CompanyOrm,
    ParsedFieldOrm,
    ProceedingEventOrm,
    ProceedingOrm,
    SourceReferenceOrm,
)
from libs.provenance import build_envelope, new_ulid
from services.extract.framework import ParseContext
from services.extract.framework.base import ParsedRecord
from services.extract.framework.config import FieldProvenance
from services.normalize import Normalizer


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """In-memory SQLite session with JSONB swapped to JSON for portability."""
    swapped: list[tuple[object, object]] = []
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, JSONB):
                swapped.append((col, col.type))
                col.type = JSON()
    try:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sm = async_sessionmaker(engine, expire_on_commit=False)
        async with sm() as s:
            yield s
        await engine.dispose()
    finally:
        for col, orig in swapped:
            col.type = orig  # type: ignore[attr-defined]


def _ctx(source_id: str, record_suffix: str = "a") -> ParseContext:
    """Build a ParseContext with a deterministic-ish record_uid."""
    env = build_envelope(
        source_id=source_id,
        source_url=f"https://example.invalid/{source_id}/{record_suffix}",
        stable_natural_key=f"nk-{record_suffix}",
        fetched_at_utc=datetime(2026, 4, 21, 8, 0, tzinfo=UTC),
        published_at_local=None,
        raw_object_key=f"{source_id}/2026/04/21/{record_suffix * 64}"[:500],
        raw_sha256=(record_suffix * 64)[:64],
        parser_version="parsers.it.tribunale_milano_v1.0.0",
        extractor_run_id=new_ulid(),
        data_owner="test",
        legal_basis="test",
    )
    return ParseContext(
        source_id=source_id,
        parser_version=env.parser_version,
        run_id=env.extractor_run_id,
        envelope=env,
        raw_object_key=env.raw_object_key,
        source_url=env.source_url,
        natural_key_hint=f"nk-{record_suffix}",
    )


def _record(
    *,
    debtor="ACME S.p.A.",
    case_number="4523/2026",
    codice_fiscale="02468013579",
    ptype="LIQUIDATION",
    ptype_original="Liquidazione giudiziale",
    opened=date(2026, 4, 15),
    court="Tribunale di Milano — Sezione Fallimentare",
) -> ParsedRecord:
    """Build a ParsedRecord resembling what the Milano parser emits."""
    fields = {
        "debtor_name": debtor,
        "case_number": case_number,
        "court_case_number": case_number,
        "codice_fiscale": codice_fiscale,
        "piva": codice_fiscale,
        "proceeding_type": ptype,
        "proceeding_type_original": ptype_original,
        "opened_at": opened,
        "jurisdiction": "IT",
        "court_name": court,
        "administrator_name": "Avv. Test",
        "administrator_role": "Curatore fallimentare",
    }
    provenance = {
        name: FieldProvenance(
            field_name=name,
            selector=f"selector-for-{name}",
            raw_length=len(str(v)) if v is not None else None,
            transforms=[],
            confidence=1.0,
        )
        for name, v in fields.items()
    }
    return ParsedRecord(
        natural_key=case_number,
        fields=fields,
        field_provenance=provenance,
        language="it",
        confidence=1.0,
    )


# ── Happy path ───────────────────────────────────────────────────────
@pytest.mark.asyncio
class TestHappyPath:
    async def test_creates_full_graph(self, session: AsyncSession) -> None:
        n = Normalizer()
        out = await n.normalize(session, _record(), _ctx("it-tribunale-milano"))

        assert out.company_created is True
        assert out.proceeding_created is True
        assert out.source_ref_new is True
        assert out.parsed_fields_written > 0
        assert out.skipped_duplicate_record is False

        # Verify one Company written with codice_fiscale registered.
        companies = (await session.execute(select(CompanyOrm))).scalars().all()
        assert len(companies) == 1
        assert companies[0].legal_name == "ACME S.p.A."
        assert companies[0].country == "IT"

        ids = (await session.execute(select(CompanyIdentifierOrm))).scalars().all()
        assert {i.scheme for i in ids} == {"codice_fiscale", "vat"}

        # Verify one Proceeding.
        procs = (await session.execute(select(ProceedingOrm))).scalars().all()
        assert len(procs) == 1
        assert procs[0].court_case_number == "4523/2026"
        assert procs[0].proceeding_type == "LIQUIDATION"
        assert procs[0].opened_at == date(2026, 4, 15)

        # Verify one Event.
        events = (await session.execute(select(ProceedingEventOrm))).scalars().all()
        assert len(events) == 1
        assert events[0].event_type == "liquidation_announced"

        # Verify SourceRef on both proceeding + event.
        refs = (await session.execute(select(SourceReferenceOrm))).scalars().all()
        assert len(refs) == 2
        assert {r.entity_type for r in refs} == {"proceeding", "event"}

        # Verify parsed_field rows.
        pfs = (await session.execute(select(ParsedFieldOrm))).scalars().all()
        assert len(pfs) == out.parsed_fields_written
        assert {p.field_name for p in pfs} >= {
            "debtor_name", "case_number", "proceeding_type", "opened_at",
        }


# ── Idempotency ──────────────────────────────────────────────────────
@pytest.mark.asyncio
class TestIdempotency:
    async def test_same_record_uid_twice_noops(self, session: AsyncSession) -> None:
        n = Normalizer()
        ctx = _ctx("it-tribunale-milano")
        rec = _record()

        first = await n.normalize(session, rec, ctx)
        second = await n.normalize(session, rec, ctx)

        assert first.skipped_duplicate_record is False
        assert second.skipped_duplicate_record is True
        assert second.company_pid == first.company_pid
        assert second.proceeding_pid == first.proceeding_pid

        # Exactly one Company / Proceeding / Event.
        assert len((await session.execute(select(CompanyOrm))).scalars().all()) == 1
        assert len((await session.execute(select(ProceedingOrm))).scalars().all()) == 1
        assert len((await session.execute(select(ProceedingEventOrm))).scalars().all()) == 1

        # Exactly two source_refs (proc + event), not four.
        assert len((await session.execute(select(SourceReferenceOrm))).scalars().all()) == 2


# ── Cross-source linkage ─────────────────────────────────────────────
@pytest.mark.asyncio
class TestCrossSourceLinkage:
    async def test_same_proceeding_two_sources(self, session: AsyncSession) -> None:
        """Milano tribunal + BODACC announcement about the same case → 1 proc, 2 events."""
        n = Normalizer()

        # 1st: Milano tribunal report
        await n.normalize(
            session,
            _record(case_number="4523/2026"),
            _ctx("it-tribunale-milano", record_suffix="a"),
        )

        # 2nd: hypothetical IT gazette with the same case number
        await n.normalize(
            session,
            _record(case_number="4523/2026"),
            _ctx("it-gazzetta-ufficiale", record_suffix="b"),
        )

        # One Company, one Proceeding, two Events, 4 source_refs (proc+event × 2 records).
        assert len((await session.execute(select(CompanyOrm))).scalars().all()) == 1
        procs = (await session.execute(select(ProceedingOrm))).scalars().all()
        assert len(procs) == 1
        events = (await session.execute(select(ProceedingEventOrm))).scalars().all()
        assert len(events) == 2
        refs = (await session.execute(select(SourceReferenceOrm))).scalars().all()
        assert len(refs) == 4

        # Distinct source_ids on the proceeding's refs.
        proc_refs = [r for r in refs if r.entity_type == "proceeding"]
        assert {r.source_id for r in proc_refs} == {
            "it-tribunale-milano", "it-gazzetta-ufficiale",
        }


# ── Company resolution by external ID ────────────────────────────────
@pytest.mark.asyncio
class TestCompanyResolution:
    async def test_same_codice_fiscale_two_proceedings(self, session: AsyncSession) -> None:
        """Same company, two different proceedings → 1 Company, 2 Proceedings."""
        n = Normalizer()

        await n.normalize(
            session,
            _record(case_number="4523/2026", codice_fiscale="02468013579"),
            _ctx("it-tribunale-milano", record_suffix="a"),
        )
        # Different case number, same debtor codice fiscale
        await n.normalize(
            session,
            _record(case_number="5678/2026", codice_fiscale="02468013579"),
            _ctx("it-tribunale-milano", record_suffix="b"),
        )

        companies = (await session.execute(select(CompanyOrm))).scalars().all()
        assert len(companies) == 1

        procs = (await session.execute(select(ProceedingOrm))).scalars().all()
        assert len(procs) == 2
        # Both linked to the same company.
        assert {p.company_pid for p in procs} == {companies[0].company_pid}


# ── Invariants ───────────────────────────────────────────────────────
@pytest.mark.asyncio
class TestInvariants:
    async def test_missing_required_field_raises(self, session: AsyncSession) -> None:
        rec = _record()
        del rec.fields["proceeding_type"]

        n = Normalizer()
        with pytest.raises(ValueError, match="proceeding_type"):
            await n.normalize(session, rec, _ctx("x"))

    async def test_missing_jurisdiction_raises(self, session: AsyncSession) -> None:
        rec = _record()
        del rec.fields["jurisdiction"]

        n = Normalizer()
        with pytest.raises(ValueError, match="jurisdiction"):
            await n.normalize(session, rec, _ctx("x"))
