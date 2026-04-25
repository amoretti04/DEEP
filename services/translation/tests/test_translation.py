"""Translation: contract + stub + client cache tests.

Does not exercise the real NLLB model (that requires 2.4GB of weights
and ~30s to load). The NLLB module is smoke-tested in the compose
stack under the `translation` profile, not in unit tests.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from infra.alembic.orm import Base, TranslationOrm
from services.translation.client import TranslationClient
from services.translation.contract import TranslateRequest, TranslateResponse
from services.translation.stub import app as stub_app


# ── Contract validation ──────────────────────────────────────────────
class TestContract:
    def test_request_valid(self) -> None:
        req = TranslateRequest(text="Ciao mondo", source_language="it")
        assert req.target_language == "en"
        assert req.source_language == "it"

    def test_rejects_bad_language_code(self) -> None:
        with pytest.raises(ValidationError):
            TranslateRequest(text="x", source_language="ITALIANO")

    def test_auto_source_allowed(self) -> None:
        TranslateRequest(text="x", source_language="auto")  # no raise

    def test_region_suffix_allowed(self) -> None:
        TranslateRequest(text="x", source_language="it-IT", target_language="en-GB")

    def test_response_has_metadata(self) -> None:
        r = TranslateResponse(
            translated_text="hello",
            source_language="it",
            target_language="en",
            model_name="stub",
            model_version="0",
            confidence=None,
            character_count=5,
        )
        assert r.model_name == "stub"


# ── Stub service ─────────────────────────────────────────────────────
class TestStubService:
    def test_health(self) -> None:
        c = TestClient(stub_app)
        r = c.get("/health")
        assert r.status_code == 200
        assert r.json()["mode"] == "stub"

    def test_echoes_with_marker(self) -> None:
        c = TestClient(stub_app)
        r = c.post(
            "/translate",
            json={"text": "Ciao mondo", "source_language": "it"},
        )
        assert r.status_code == 200
        body = r.json()
        assert "[stub it→en]" in body["translated_text"]
        assert body["translated_text"].endswith("Ciao mondo")
        assert body["character_count"] == 10
        assert body["model_name"] == "stub"


# ── Client + cache ───────────────────────────────────────────────────
@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """In-memory SQLite with JSONB swapped to JSON for portability."""
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


@pytest_asyncio.fixture
async def stub_http() -> AsyncIterator[AsyncClient]:
    """An AsyncClient wired directly to the stub's ASGI app — no network."""
    transport = ASGITransport(app=stub_app)
    async with AsyncClient(transport=transport, base_url="http://stub") as c:
        yield c


@pytest.mark.asyncio
class TestTranslationClient:
    async def test_miss_then_hit(
        self, db_session: AsyncSession, stub_http: AsyncClient
    ) -> None:
        client = TranslationClient(service_url="http://stub", http=stub_http)

        # First call: cache miss, hits the stub.
        a = await client.translate(
            session=db_session, text="Ciao mondo", source_language="it"
        )
        assert a.from_cache is False
        assert a.translated_text.endswith("Ciao mondo")
        assert a.model_name == "stub"

        # Second call, same text: cache hit, no service traffic needed.
        b = await client.translate(
            session=db_session, text="Ciao mondo", source_language="it"
        )
        assert b.from_cache is True
        assert b.translated_text == a.translated_text

    async def test_different_text_is_different_cache(
        self, db_session: AsyncSession, stub_http: AsyncClient
    ) -> None:
        client = TranslationClient(service_url="http://stub", http=stub_http)
        a = await client.translate(
            session=db_session, text="Alpha", source_language="it"
        )
        b = await client.translate(
            session=db_session, text="Beta", source_language="it"
        )
        assert a.translated_text != b.translated_text
        assert a.from_cache is False
        assert b.from_cache is False

    async def test_same_text_different_target_distinct_cache(
        self, db_session: AsyncSession, stub_http: AsyncClient
    ) -> None:
        client = TranslationClient(service_url="http://stub", http=stub_http)
        a = await client.translate(
            session=db_session,
            text="Ciao",
            source_language="it",
            target_language="en",
        )
        b = await client.translate(
            session=db_session,
            text="Ciao",
            source_language="it",
            target_language="fr",
        )
        assert a.from_cache is False
        assert b.from_cache is False
        assert a.target_language == "en"
        assert b.target_language == "fr"

    async def test_empty_text_noop(
        self, db_session: AsyncSession, stub_http: AsyncClient
    ) -> None:
        client = TranslationClient(service_url="http://stub", http=stub_http)
        r = await client.translate(
            session=db_session, text="", source_language="it"
        )
        assert r.translated_text == ""
        assert r.model_name == "noop"

    async def test_cache_row_persisted_with_metadata(
        self, db_session: AsyncSession, stub_http: AsyncClient
    ) -> None:
        client = TranslationClient(service_url="http://stub", http=stub_http)
        await client.translate(
            session=db_session, text="Hola", source_language="es"
        )
        from sqlalchemy import select

        rows = (
            await db_session.execute(select(TranslationOrm))
        ).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.source_language == "es"
        assert row.target_language == "en"
        assert row.model_name == "stub"
        assert row.character_count == 4
        assert row.use_count == 1

    async def test_use_count_bumped_on_hit(
        self, db_session: AsyncSession, stub_http: AsyncClient
    ) -> None:
        client = TranslationClient(service_url="http://stub", http=stub_http)
        await client.translate(
            session=db_session, text="Salut", source_language="fr"
        )
        await client.translate(
            session=db_session, text="Salut", source_language="fr"
        )
        await client.translate(
            session=db_session, text="Salut", source_language="fr"
        )
        from sqlalchemy import select

        row = (
            await db_session.execute(select(TranslationOrm))
        ).scalar_one()
        assert row.use_count == 3
