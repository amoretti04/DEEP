"""API smoke tests using aiosqlite — no Postgres required.

JSONB columns degrade gracefully to TEXT on SQLite so the ORM maps work
for read paths (which is what the API does in R1). These tests do not
exercise PG-specific features like partial indexes or JSONB operators.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from infra.alembic.orm import Base, ProceedingEventOrm, SourceOrm
from libs.provenance import new_ulid


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    # SQLite in-memory; swap every JSONB column to JSON for portability.
    swapped: list[tuple[object, JSONB]] = []
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, JSONB):
                swapped.append((col, col.type))  # type: ignore[arg-type]
                col.type = JSON()

    try:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sm = async_sessionmaker(engine, expire_on_commit=False)
        async with sm() as session:
            yield session
        await engine.dispose()
    finally:
        # Restore original JSONB so other tests aren't affected.
        for col, orig in swapped:
            col.type = orig  # type: ignore[attr-defined]


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    # Seed a few sources + events.
    db_session.add_all(
        [
            SourceOrm(
                source_id="it-milano",
                name="Tribunale di Milano",
                workbook_country="Italy",
                country="IT",
                language="it",
                tier=1,
                category="COURT",
                jurisdiction_class="eu_gdpr",
                connector="HttpScrapeConnector",
                fetch_mode="list+detail",
                base_url="https://tribunale.milano/",
                schedule={"cron": "0 */3 * * *", "timezone": "Europe/Rome"},
                politeness={"min_delay_s": 4, "max_delay_s": 9, "concurrency": 1},
                legal_review={"verdict": "pending"},
                on_failure={"alert_channel": "slack#ingest-alerts"},
                in_priority_scope=True,
                enabled=False,
                release_wave=1,
            ),
            SourceOrm(
                source_id="de-insolvenz",
                name="Insolvenzbekanntmachungen",
                workbook_country="Germany",
                country="DE",
                language="de",
                tier=1,
                category="INS-REG",
                jurisdiction_class="eu_gdpr",
                connector="HttpScrapeConnector",
                fetch_mode="list+detail",
                base_url="https://insolvenzbekanntmachungen.de/",
                schedule={"cron": "0 */3 * * *", "timezone": "Europe/Berlin"},
                politeness={"min_delay_s": 4, "max_delay_s": 9, "concurrency": 1},
                legal_review={"verdict": "approved"},
                on_failure={"alert_channel": "slack#ingest-alerts"},
                in_priority_scope=True,
                enabled=True,
                release_wave=1,
            ),
            SourceOrm(
                source_id="ae-adx",
                name="Abu Dhabi Exchange Disclosures",
                workbook_country="UAE",
                country="AE",
                language="en",
                tier=2,
                category="MKT",
                jurisdiction_class="non_eu_separate_regime",
                connector="APIConnector",
                fetch_mode="api",
                base_url="https://adx.ae/",
                schedule={"cron": "0 */8 * * *", "timezone": "Asia/Dubai"},
                politeness={"min_delay_s": 4, "max_delay_s": 9, "concurrency": 1},
                legal_review={"verdict": "pending"},
                on_failure={"alert_channel": "slack#ingest-alerts"},
                in_priority_scope=False,
                enabled=False,
                release_wave=7,
            ),
        ]
    )
    # One event — requires a proceeding row, but we can satisfy the FK by
    # inserting a stub event pointing at a placeholder proceeding. For
    # smoke purposes we use FK=OFF in SQLite defaults.
    db_session.add(
        ProceedingEventOrm(
            event_pid=new_ulid(),
            proceeding_pid=new_ulid(),
            event_type="bankruptcy_filing",
            occurred_at_utc=datetime(2026, 4, 20, 9, 0, tzinfo=UTC),
            description_original="Liquidazione giudiziale aperta.",
            description_english="Judicial liquidation opened.",
            language_original="it",
            extra={},
        )
    )
    await db_session.commit()

    from services.api.main import create_app
    from services.api.db import get_session

    app = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _override_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
class TestHealth:
    async def test_health_ok(self, client: AsyncClient) -> None:
        r = await client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] in {"ok", "degraded"}
        assert body["database"] in {"ok", "degraded", "unreachable"}


@pytest.mark.asyncio
class TestSources:
    async def test_list(self, client: AsyncClient) -> None:
        r = await client.get("/sources")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 3
        assert len(body["items"]) == 3

    async def test_filter_by_country(self, client: AsyncClient) -> None:
        r = await client.get("/sources", params={"country": "IT"})
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["items"][0]["source_id"] == "it-milano"

    async def test_filter_priority_scope(self, client: AsyncClient) -> None:
        r = await client.get("/sources", params={"in_priority_scope": True})
        assert r.status_code == 200
        assert r.json()["total"] == 2

    async def test_filter_enabled(self, client: AsyncClient) -> None:
        r = await client.get("/sources", params={"enabled": True})
        assert r.json()["total"] == 1
        assert r.json()["items"][0]["source_id"] == "de-insolvenz"

    async def test_search(self, client: AsyncClient) -> None:
        r = await client.get("/sources", params={"q": "milano"})
        assert r.json()["total"] == 1

    async def test_detail_found(self, client: AsyncClient) -> None:
        r = await client.get("/sources/it-milano")
        assert r.status_code == 200
        assert r.json()["source_id"] == "it-milano"
        assert r.json()["legal_review_verdict"] == "pending"

    async def test_detail_404(self, client: AsyncClient) -> None:
        r = await client.get("/sources/nope-nope-nope")
        assert r.status_code == 404

    async def test_counts(self, client: AsyncClient) -> None:
        r = await client.get("/sources/counts")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 3
        assert body["in_priority_scope"] == 2
        assert body["enabled"] == 1
        assert body["by_country"]["IT"] == 1
        assert body["by_tier"]["1"] == 2
        assert body["by_category"]["COURT"] == 1


@pytest.mark.asyncio
class TestEvents:
    async def test_list_events(self, client: AsyncClient) -> None:
        r = await client.get("/events")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["items"][0]["event_type"] == "bankruptcy_filing"
        assert body["items"][0]["language_original"] == "it"
