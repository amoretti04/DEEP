"""Tests that lock in the scope gate: an unapproved source CANNOT run.

This is a regression-critical test. If any future refactor lets an
unapproved source hit the network, this file fails and blocks merge.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import AsyncIterator

import pytest

from libs.schemas import (
    ConnectorType,
    Country,
    FetchMode,
    JurisdictionClass,
    Language,
    LegalReviewStatus,
    Source,
    SourceSchedule,
    Tier,
)
from libs.schemas.source import LegalReview
from libs.taxonomy import SourceCategory
from services.ingest.core import InMemoryRateLimiter, SourceConnector
from services.ingest.core.base import (
    ConnectorContext,
    Disabled,
    FetchResult,
    NotApproved,
)


class _FakeRawLake:
    async def put(  # noqa: PLR0913
        self,
        *,
        source_id: str,
        payload: bytes,
        content_type: str,
        fetched_at_utc: datetime,
        extension: str,
    ) -> object:
        from services.ingest.core.raw_lake import StoredArtifact

        from libs.provenance import compute_raw_sha256, derive_raw_object_key
        sha = compute_raw_sha256(payload)
        key = derive_raw_object_key(
            source_id=source_id,
            fetched_at_utc=fetched_at_utc,
            raw_sha256=sha,
            extension=extension,
        )
        return StoredArtifact(
            bucket="test",
            object_key=key,
            content_sha256=sha,
            size_bytes=len(payload),
            content_type=content_type,
            existed_before=False,
        )

    async def get(self, _key: str) -> bytes:
        return b""

    async def exists(self, _key: str) -> bool:
        return False


class _TinyConnector(SourceConnector):
    async def fetch(self) -> AsyncIterator[FetchResult]:
        yield FetchResult(
            source_url="https://example.com/x",
            payload=b"<html></html>",
            content_type="text/html",
            natural_key="k",
        )


def _source(
    *,
    verdict: LegalReviewStatus = LegalReviewStatus.PENDING,
    enabled: bool = False,
) -> Source:
    return Source(
        source_id="it-demo",
        name="Demo",
        workbook_country="Italy",
        workbook_category="Bankruptcy Tribunal",
        country=Country.IT,
        language=Language.IT,
        tier=Tier.T1,
        category=SourceCategory.COURT,
        jurisdiction_class=JurisdictionClass.EU_GDPR,
        connector=ConnectorType.HTTP_SCRAPE,
        fetch_mode=FetchMode.LIST_AND_DETAIL,
        base_url="https://example.com/",
        schedule=SourceSchedule(cron="0 */3 * * *"),
        legal_review=LegalReview(verdict=verdict),
        enabled=enabled,
    )


def _ctx(source: Source) -> ConnectorContext:
    return ConnectorContext.for_run(
        source=source,
        source_card_version=1,
        rate_limiter=InMemoryRateLimiter(tokens_per_second=10.0),
        raw_lake=_FakeRawLake(),  # type: ignore[arg-type]
        data_owner="team-test",
        legal_basis="test",
    )


class TestScopeGate:
    async def test_disabled_source_refuses(self) -> None:
        src = _source(verdict=LegalReviewStatus.APPROVED, enabled=False)
        conn = _TinyConnector(_ctx(src))
        with pytest.raises(Disabled):
            async for _ in conn.run():
                pass

    async def test_pending_legal_review_refuses(self) -> None:
        src = _source(verdict=LegalReviewStatus.PENDING, enabled=True)
        conn = _TinyConnector(_ctx(src))
        with pytest.raises(NotApproved):
            async for _ in conn.run():
                pass

    async def test_rejected_legal_review_refuses(self) -> None:
        src = _source(verdict=LegalReviewStatus.REJECTED, enabled=True)
        conn = _TinyConnector(_ctx(src))
        with pytest.raises(NotApproved):
            async for _ in conn.run():
                pass

    async def test_approved_and_enabled_runs(self) -> None:
        src = _source(verdict=LegalReviewStatus.APPROVED, enabled=True)
        conn = _TinyConnector(_ctx(src))
        artifacts = [a async for a in conn.run()]
        assert len(artifacts) == 1
        assert artifacts[0].source_id == "it-demo"
        assert artifacts[0].content_type == "text/html"
        assert artifacts[0].size_bytes == len(b"<html></html>")


class TestInMemoryRateLimiter:
    async def test_acquires_and_refills(self) -> None:
        rl = InMemoryRateLimiter(tokens_per_second=100.0, bucket_size=2)
        # Two immediate acquires should succeed (bucket size 2).
        await rl.acquire("k")
        await rl.acquire("k")
        # Third acquires after a short wait via refill — should not hang.
        import asyncio
        await asyncio.wait_for(rl.acquire("k"), timeout=1.0)

    async def test_rejects_bad_params(self) -> None:
        with pytest.raises(ValueError):
            InMemoryRateLimiter(tokens_per_second=0)
        with pytest.raises(ValueError):
            InMemoryRateLimiter(bucket_size=0)
