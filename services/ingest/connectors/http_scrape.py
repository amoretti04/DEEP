"""HTTP-scrape connector.

Covers the largest class of sources in the workbook: static HTML pages
following a stable ``list → detail`` pattern. JS-rendered sources use
HeadlessConnector; API-backed sources use APIConnector.

Each concrete tribunal / gazette / auction aggregator inherits from this
and implements :meth:`enumerate_detail_urls`. The bulk of the work — HTTP
mechanics, retries, politeness, persistence — is handled by the base
class and this generic HTTP scaffold.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, AsyncIterator
from urllib.parse import urlparse

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from services.ingest.core.base import FetchResult, SourceConnector

if TYPE_CHECKING:
    from services.ingest.core.base import ConnectorContext


@dataclass(frozen=True, slots=True)
class DetailLink:
    """A URL-plus-natural-key tuple a list page yields for its details."""

    url: str
    natural_key: str
    published_at_local: datetime | None = None


class HttpScrapeConnector(SourceConnector):
    """Generic list→detail HTTP scraper.

    Subclasses override :meth:`enumerate_detail_urls` to produce
    :class:`DetailLink` objects. This class handles fetching each detail
    page with retries, politeness, and UA/header management.
    """

    #: Default UA pool; per-source override via Source.politeness.user_agent_pool
    DEFAULT_UA = (
        "Mozilla/5.0 (compatible; DIP-Bot/0.1; +https://dip.local/bot)"
    )

    #: Retry policy for transient HTTP failures. 429 / 5xx / network errors.
    _RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

    def __init__(
        self,
        ctx: ConnectorContext,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(ctx)
        self._http = http_client
        self._owns_client = http_client is None

    async def fetch(self) -> AsyncIterator[FetchResult]:
        client = self._http or self._new_client()
        try:
            domain = urlparse(str(self.source.base_url)).netloc
            async for link in self.enumerate_detail_urls(client):
                await self.ctx.rate_limiter.acquire(domain)
                response = await self._get_with_retries(client, link.url)
                yield FetchResult(
                    source_url=link.url,
                    payload=response.content,
                    content_type=response.headers.get("content-type", "text/html"),
                    natural_key=link.natural_key,
                    published_at_local=link.published_at_local,
                    http_status=response.status_code,
                )
                await self.ctx.rate_limiter.sleep_jitter(
                    self.source.politeness.min_delay_s,
                    self.source.politeness.max_delay_s,
                )
        finally:
            if self._owns_client and self._http is None:
                await client.aclose()

    # ── subclass contract ───────────────────────────────────────────
    async def enumerate_detail_urls(
        self, client: httpx.AsyncClient
    ) -> AsyncIterator[DetailLink]:
        """Yield :class:`DetailLink` for each detail page.

        Concrete implementations typically:

        1. Fetch the list page(s) (respecting politeness).
        2. Parse out detail links + stable natural keys.
        3. Yield one :class:`DetailLink` per item.

        The base class handles the detail fetches.
        """
        raise NotImplementedError
        # Workaround to make this an async generator for type-checkers.
        yield  # type: ignore[unreachable]

    # ── internals ───────────────────────────────────────────────────
    def _new_client(self) -> httpx.AsyncClient:
        self._http = httpx.AsyncClient(
            headers={
                "User-Agent": self.DEFAULT_UA,
                "Accept-Language": self._accept_language(),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            follow_redirects=True,
            timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0),
            http2=True,
        )
        return self._http

    def _accept_language(self) -> str:
        # Match the source's language so servers don't try to redirect us
        # to an English mirror and break our parsers.
        return {
            "it": "it-IT,it;q=0.9,en;q=0.6",
            "de": "de-DE,de;q=0.9,en;q=0.6",
            "fr": "fr-FR,fr;q=0.9,en;q=0.6",
            "es": "es-ES,es;q=0.9,en;q=0.6",
            "nl": "nl-NL,nl;q=0.9,en;q=0.6",
            "en": "en-GB,en;q=0.9",
            "ar": "ar-AE,ar;q=0.9,en;q=0.6",
        }.get(self.source.language.value, "en;q=0.9")

    async def _get_with_retries(
        self, client: httpx.AsyncClient, url: str
    ) -> httpx.Response:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(6),
            wait=wait_exponential_jitter(initial=2.0, max=600.0, jitter=2.0),
            retry=retry_if_exception_type(
                (httpx.TransportError, httpx.HTTPStatusError)
            ),
            reraise=True,
        ):
            with attempt:
                response = await client.get(url)
                if response.status_code in self._RETRY_STATUSES:
                    # Trigger tenacity retry without masking the status.
                    raise httpx.HTTPStatusError(
                        f"Retryable {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                return response
        # Unreachable: AsyncRetrying with reraise=True always raises or returns.
        raise RuntimeError("retry loop exited without result")  # pragma: no cover
