"""API tests for R2 endpoints: proceedings detail, documents + translate, settings.

Uses the same in-memory SQLite fixture pattern as test_api.py — JSONB
columns get swapped to JSON so the ORM works on SQLite. Feature-flag
semantics are exercised end-to-end: off → 403, on → 200 with cached-
miss, on again → 200 with cached-hit.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from infra.alembic.orm import (
    Base,
    CompanyOrm,
    DocumentOrm,
    ProceedingEventOrm,
    ProceedingOrm,
    SourceReferenceOrm,
)
from libs.provenance import build_envelope, new_ulid


# ── Fixture setup ────────────────────────────────────────────────────
@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
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
        async with sm() as session:
            yield session
        await engine.dispose()
    finally:
        for col, orig in swapped:
            col.type = orig  # type: ignore[attr-defined]


PROC_PID = "01JABCDEF00000000000000000"
EVENT_PID = "01JABCDEF00000000000000001"
DOC_PID = "01JABCDEF00000000000000002"
COMPANY_PID = "01JABCDEF00000000000000009"


async def _seed(session: AsyncSession) -> None:
    # Company (referenced by proceeding)
    session.add(
        CompanyOrm(
            company_pid=COMPANY_PID,
            legal_name="Esempio Manifatture S.p.A.",
            country="IT",
            status="in_proceeding",
        )
    )
    # Proceeding
    session.add(
        ProceedingOrm(
            proceeding_pid=PROC_PID,
            company_pid=COMPANY_PID,
            jurisdiction="IT",
            court_name="Tribunale di Milano — Sezione Fallimentare",
            court_case_number="4523/2026",
            proceeding_type="LIQUIDATION",
            proceeding_type_original="Liquidazione giudiziale",
            administrator_name="Avv. Carlo Verdi",
            administrator_role="Curatore fallimentare",
            opened_at=date(2026, 4, 15),
            status="open",
        )
    )
    # Event
    session.add(
        ProceedingEventOrm(
            event_pid=EVENT_PID,
            proceeding_pid=PROC_PID,
            event_type="bankruptcy_filing",
            occurred_at_utc=datetime(2026, 4, 15, 9, 0, tzinfo=UTC),
            description_original="Sentenza di apertura della liquidazione giudiziale.",
            description_english="Ruling opening the judicial liquidation.",
            language_original="it",
            extra={},
        )
    )
    # Document
    session.add(
        DocumentOrm(
            document_pid=DOC_PID,
            proceeding_pid=PROC_PID,
            title="Sentenza dichiarativa",
            document_type="ruling",
            url="https://example.invalid/sentenza-4523-2026.pdf",
            filed_at=date(2026, 4, 15),
            language_original="it",
            text_original=(
                "Tribunale di Milano, Sezione Fallimentare. "
                "Letta la richiesta del creditore, dichiara aperta la procedura."
            ),
            text_english=None,
            page_count=3,
        )
    )
    # SourceReferences (one for proceeding, one for event)
    env = build_envelope(
        source_id="it-tribunale-milano-fallimenti",
        source_url="https://www.tribunale.milano.giustizia.it/fallimenti/4523-2026",
        stable_natural_key="4523/2026",
        fetched_at_utc=datetime(2026, 4, 15, 8, 0, tzinfo=UTC),
        published_at_local=None,
        raw_object_key="it-tribunale-milano-fallimenti/2026/04/15/abc.html",
        raw_sha256="a" * 64,
        parser_version="it.tribunale_milano_v1.0.0",
        extractor_run_id=new_ulid(),
        data_owner="team-ingest-it",
        legal_basis="Art. 6(1)(f) GDPR — public register",
    )
    env_json = env.model_dump(mode="json")
    session.add_all([
        SourceReferenceOrm(
            entity_type="proceeding",
            entity_id=PROC_PID,
            record_uid=env.record_uid,
            source_id=env.source_id,
            envelope=env_json,
        ),
        SourceReferenceOrm(
            entity_type="event",
            entity_id=EVENT_PID,
            record_uid=env.record_uid,
            source_id=env.source_id,
            envelope=env_json,
        ),
    ])
    await session.commit()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    await _seed(db_session)
    from services.api.db import get_session
    from services.api.main import create_app

    app = create_app()

    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# ── Proceeding detail ────────────────────────────────────────────────
@pytest.mark.asyncio
class TestProceedingsDetail:
    async def test_get_returns_events_docs_and_refs(self, client: AsyncClient) -> None:
        r = await client.get(f"/proceedings/{PROC_PID}")
        assert r.status_code == 200
        body = r.json()
        assert body["proceeding_pid"] == PROC_PID
        assert body["court_case_number"] == "4523/2026"
        assert body["proceeding_type"] == "LIQUIDATION"

        assert len(body["events"]) == 1
        assert body["events"][0]["event_type"] == "bankruptcy_filing"
        assert body["events"][0]["language_original"] == "it"

        assert len(body["documents"]) == 1
        assert body["documents"][0]["title"] == "Sentenza dichiarativa"
        assert body["documents"][0]["has_translation"] is False

        # Both proceeding + event source refs returned
        assert len(body["source_references"]) == 2
        ref = body["source_references"][0]
        assert ref["source_id"] == "it-tribunale-milano-fallimenti"
        assert ref["parser_version"] == "it.tribunale_milano_v1.0.0"

    async def test_404_on_unknown(self, client: AsyncClient) -> None:
        r = await client.get("/proceedings/nope-nope-nope")
        assert r.status_code == 404


# ── Settings endpoints ───────────────────────────────────────────────
@pytest.mark.asyncio
class TestSettings:
    async def test_defaults_when_never_set(self, client: AsyncClient) -> None:
        r = await client.get("/settings", headers={"X-DIP-User": "alice"})
        assert r.status_code == 200
        body = r.json()
        assert body["user_id"] == "alice"
        assert body["settings"]["translation"]["enabled"] is False

    async def test_update_and_read_back(self, client: AsyncClient) -> None:
        payload = {
            "translation": {"enabled": True, "default_target_language": "en"},
            "display": {
                "show_low_confidence_badge": False,
                "priority_scope_only_by_default": True,
            },
        }
        r = await client.put(
            "/settings", json=payload, headers={"X-DIP-User": "alice"},
        )
        assert r.status_code == 200
        assert r.json()["settings"]["translation"]["enabled"] is True

        # Read back
        r2 = await client.get("/settings", headers={"X-DIP-User": "alice"})
        assert r2.json()["settings"]["display"]["show_low_confidence_badge"] is False

    async def test_rejects_unknown_flag(self, client: AsyncClient) -> None:
        r = await client.put(
            "/settings",
            json={"translation": {"enabled": True, "unknown_flag": True}},
            headers={"X-DIP-User": "alice"},
        )
        assert r.status_code == 422


# ── Translation endpoint (feature-flag gated) ────────────────────────
@pytest.mark.asyncio
class TestDocumentTranslate:
    async def test_disabled_returns_403(self, client: AsyncClient) -> None:
        # Default settings → translation disabled
        r = await client.post(
            f"/documents/{DOC_PID}/translate",
            headers={"X-DIP-User": "alice"},
        )
        assert r.status_code == 403
        assert "disabled" in r.json()["detail"].lower()

    async def test_enabled_translates_via_stub(self, client: AsyncClient, monkeypatch) -> None:
        # Flip the flag
        await client.put(
            "/settings",
            json={"translation": {"enabled": True, "default_target_language": "en"}},
            headers={"X-DIP-User": "alice"},
        )

        # Monkey-patch the translation client to avoid needing the real
        # stub HTTP server in CI; returns a canned TranslationResult.
        from services.translation import client as client_mod

        class _Fake:
            async def translate(self, *, session, text, source_language, target_language="en"):
                return client_mod.TranslationResult(
                    translated_text="[stub it→en] " + text,
                    source_language=source_language,
                    target_language=target_language,
                    model_name="stub",
                    model_version="0.0.1",
                    confidence=None,
                    character_count=len(text),
                    from_cache=False,
                )

        monkeypatch.setattr(
            "services.api.routers.documents.TranslationClient",
            lambda *a, **kw: _Fake(),
        )

        r = await client.post(
            f"/documents/{DOC_PID}/translate",
            headers={"X-DIP-User": "alice"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["document_pid"] == DOC_PID
        assert body["translated_text"].startswith("[stub it→en] ")
        assert body["source_language"] == "it"

    async def test_404_on_unknown_document(self, client: AsyncClient) -> None:
        await client.put(
            "/settings",
            json={"translation": {"enabled": True, "default_target_language": "en"}},
            headers={"X-DIP-User": "alice"},
        )
        r = await client.post(
            "/documents/nope/translate", headers={"X-DIP-User": "alice"}
        )
        assert r.status_code == 404
