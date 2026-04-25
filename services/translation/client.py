"""Translation client + cache — called by the API when a user requests
an EN view of a document.

Cache-miss path:
    1. Hash the source text.
    2. Look up ``(sha256, target_language)`` in ``translation_cache``.
    3. On hit: return cached text; bump ``use_count`` and ``last_used_at``.
    4. On miss: call the translation service over HTTP, persist the
       result, return it.

The cache is in Postgres (via SQLAlchemy); the service call is HTTP
(via httpx). This module doesn't know or care whether the other side is
the stub or NLLB — it's just an HTTP call.
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
from sqlalchemy import func, select, update

from services.translation.contract import TranslateRequest, TranslateResponse

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("dip.translation.client")


@dataclass(frozen=True, slots=True)
class TranslationResult:
    """What the API returns to the caller — cache status is exposed so
    the UI can show a 'just translated' vs 'cached' badge if it wants to."""

    translated_text: str
    source_language: str
    target_language: str
    model_name: str
    model_version: str
    confidence: float | None
    character_count: int
    from_cache: bool


class TranslationError(Exception):
    """Raised when the translation service is unreachable or returns an error."""


class TranslationClient:
    """Stateless client — every method takes an AsyncSession for the cache."""

    def __init__(
        self,
        *,
        service_url: str | None = None,
        http: httpx.AsyncClient | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        self._url = (service_url or os.getenv("TRANSLATION_SERVICE_URL", "http://localhost:8088")).rstrip("/")
        self._http = http
        self._owns_http = http is None
        self._timeout = timeout_s

    async def translate(
        self,
        *,
        session: AsyncSession,
        text: str,
        source_language: str,
        target_language: str = "en",
    ) -> TranslationResult:
        """Cached translation. See module docstring for the flow."""
        if not text.strip():
            return TranslationResult(
                translated_text="",
                source_language=source_language,
                target_language=target_language,
                model_name="noop",
                model_version="0",
                confidence=None,
                character_count=0,
                from_cache=False,
            )

        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()

        # ── 1. cache lookup ──
        cached = await self._read_cache(session, digest, target_language)
        if cached is not None:
            await self._touch_cache(session, digest, target_language)
            return cached

        # ── 2. service call ──
        response = await self._call_service(
            TranslateRequest(
                text=text,
                source_language=source_language,
                target_language=target_language,
            )
        )

        # ── 3. persist ──
        await self._write_cache(session, digest, response)

        return TranslationResult(
            translated_text=response.translated_text,
            source_language=response.source_language,
            target_language=response.target_language,
            model_name=response.model_name,
            model_version=response.model_version,
            confidence=response.confidence,
            character_count=response.character_count,
            from_cache=False,
        )

    # ── Cache helpers ──────────────────────────────────────────────
    async def _read_cache(
        self, session: AsyncSession, digest: str, target: str
    ) -> TranslationResult | None:
        # Lazy-import the ORM so tests that don't exercise DB paths
        # don't need it.
        from infra.alembic.orm import TranslationOrm

        stmt = select(TranslationOrm).where(
            TranslationOrm.source_sha256 == digest,
            TranslationOrm.target_language == target,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None
        return TranslationResult(
            translated_text=row.translated_text,
            source_language=row.source_language,
            target_language=row.target_language,
            model_name=row.model_name,
            model_version=row.model_version,
            confidence=row.confidence,
            character_count=row.character_count,
            from_cache=True,
        )

    async def _touch_cache(
        self, session: AsyncSession, digest: str, target: str
    ) -> None:
        from infra.alembic.orm import TranslationOrm

        stmt = (
            update(TranslationOrm)
            .where(
                TranslationOrm.source_sha256 == digest,
                TranslationOrm.target_language == target,
            )
            .values(
                last_used_at=datetime.now(UTC),
                use_count=TranslationOrm.use_count + 1,
            )
        )
        await session.execute(stmt)
        await session.commit()

    async def _write_cache(
        self, session: AsyncSession, digest: str, resp: TranslateResponse
    ) -> None:
        from infra.alembic.orm import TranslationOrm

        row = TranslationOrm(
            source_sha256=digest,
            source_language=resp.source_language,
            target_language=resp.target_language,
            translated_text=resp.translated_text,
            model_name=resp.model_name,
            model_version=resp.model_version,
            confidence=resp.confidence,
            character_count=resp.character_count,
        )
        session.add(row)
        await session.commit()

    # ── Service call ───────────────────────────────────────────────
    async def _call_service(self, req: TranslateRequest) -> TranslateResponse:
        http = self._http or httpx.AsyncClient(timeout=self._timeout)
        try:
            r = await http.post(
                f"{self._url}/translate",
                json=req.model_dump(mode="json"),
                timeout=self._timeout,
            )
            r.raise_for_status()
            return TranslateResponse.model_validate(r.json())
        except httpx.HTTPError as e:
            logger.warning("translation.service_error %s", e)
            raise TranslationError(f"translation service error: {e}") from e
        finally:
            if self._owns_http and self._http is None:
                await http.aclose()
