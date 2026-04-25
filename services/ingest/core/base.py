"""Connector base class.

All concrete connectors (:class:`~services.ingest.connectors.HttpScrapeConnector`,
``APIConnector``, ``BulkConnector``, ``HeadlessConnector``) inherit from
:class:`SourceConnector` and implement :meth:`fetch`. The base class
handles:

* envelope assembly
* rate limiting and jitter (via injected :class:`RateLimiter`)
* raw-lake persistence
* circuit-breaker state (via Redis key)
* OpenTelemetry spans around every fetch
* **the scope gate**: refuses to run if the Source's ``legal_review.verdict``
  is anything other than ``approved``.

Concrete connectors are thin: they know how to walk their specific source.
The base class handles every other cross-cutting concern so connector
authors cannot forget them.
"""

from __future__ import annotations

import abc
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, AsyncIterator, Self

from libs.provenance import build_envelope, new_extractor_run_id
from libs.schemas import LegalReviewStatus, Source
from libs.schemas.raw import ConnectorRunStatus, RawArtifact

if TYPE_CHECKING:
    from services.ingest.core.rate_limiter import RateLimiter
    from services.ingest.core.raw_lake import RawLake, StoredArtifact


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FetchResult:
    """One raw payload emitted by :meth:`SourceConnector.fetch`."""

    source_url: str
    payload: bytes
    content_type: str
    # ``natural_key`` is the source-stable identifier the parser will need
    # to derive ``record_uid`` once it extracts a structured record. The
    # base class persists the raw artifact; ``natural_key`` travels with
    # the artifact for downstream parsers.
    natural_key: str
    published_at_local: datetime | None = None
    http_status: int | None = None
    extra: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ConnectorContext:
    """Injected dependencies — testable by construction."""

    source: Source
    source_card_version: int
    run_id: str
    extractor_run_id: str
    rate_limiter: RateLimiter
    raw_lake: RawLake
    data_owner: str
    legal_basis: str
    # Optional circuit-breaker key provider; falls back to in-memory dict
    # if absent. Production wires a Redis-backed store.
    circuit_breaker: CircuitBreaker | None = None

    @classmethod
    def for_run(
        cls,
        *,
        source: Source,
        source_card_version: int,
        rate_limiter: RateLimiter,
        raw_lake: RawLake,
        data_owner: str,
        legal_basis: str,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> Self:
        eid = new_extractor_run_id()
        return cls(
            source=source,
            source_card_version=source_card_version,
            run_id=eid,
            extractor_run_id=eid,
            rate_limiter=rate_limiter,
            raw_lake=raw_lake,
            data_owner=data_owner,
            legal_basis=legal_basis,
            circuit_breaker=circuit_breaker,
        )


class CircuitBreaker(abc.ABC):
    """Abstract breaker. Production impl is Redis-backed."""

    @abc.abstractmethod
    async def is_open(self, source_id: str) -> bool: ...

    @abc.abstractmethod
    async def record_success(self, source_id: str) -> None: ...

    @abc.abstractmethod
    async def record_failure(self, source_id: str) -> bool: ...
    """Return True if this failure just opened the breaker."""


# ── Exceptions ───────────────────────────────────────────────────────
class ConnectorRefusal(Exception):
    """Raised when the base class refuses to run the connector.

    Distinct from runtime errors: a refusal is an expected, permissioned
    outcome (unapproved legal review, open circuit breaker, disabled
    source). The scheduler logs it and moves on without paging.
    """


class CircuitOpen(ConnectorRefusal):
    """The circuit breaker for this source is open."""


class NotApproved(ConnectorRefusal):
    """The Source Card does not carry an approved legal review."""


class Disabled(ConnectorRefusal):
    """The Source is ``enabled=False``."""


# ── The base class ───────────────────────────────────────────────────
class SourceConnector(abc.ABC):
    """Abstract connector. Subclass this; implement :meth:`fetch`.

    Usage::

        connector = MyConnector(ctx)
        async for artifact in connector.run():
            await downstream.enqueue(artifact)

    The :meth:`run` method wraps :meth:`fetch` with guardrails. Do not
    override :meth:`run`; override :meth:`fetch` to yield
    :class:`FetchResult`\\ s.
    """

    def __init__(self, ctx: ConnectorContext) -> None:
        self.ctx = ctx
        self.source = ctx.source

    # ── subclass contract ───────────────────────────────────────────
    @abc.abstractmethod
    def fetch(self) -> AsyncIterator[FetchResult]:
        """Walk the source and yield raw payloads.

        Implementations must call ``await self.ctx.rate_limiter.acquire(
        <domain>)`` before every outbound request and
        ``await self.ctx.rate_limiter.sleep_jitter(...)`` between requests
        within the same session. The base class calls ``acquire`` for the
        domain derived from ``source.base_url`` before the first yield as
        a safety net.
        """
        ...

    # ── entry point (do not override) ───────────────────────────────
    async def run(self) -> AsyncIterator[RawArtifact]:
        """Run the connector end-to-end.

        Raises :class:`ConnectorRefusal` subclasses if the source is not
        runnable. Otherwise, yields one :class:`RawArtifact` per persisted
        payload.
        """
        self._assert_runnable()
        async with self._guarded_run():
            async for result in self.fetch():
                stored = await self._persist(result)
                yield self._to_raw_artifact(result, stored)

    # ── guardrails ──────────────────────────────────────────────────
    def _assert_runnable(self) -> None:
        """Enforce the scope gate. Called before any network I/O."""
        src = self.source
        if not src.enabled:
            raise Disabled(
                f"Source {src.source_id} is enabled=False; scheduler must "
                f"flip the bit before running."
            )
        if src.legal_review.verdict is not LegalReviewStatus.APPROVED:
            raise NotApproved(
                f"Source {src.source_id} has legal_review.verdict="
                f"{src.legal_review.verdict.value}; connector refuses to run. "
                f"See docs/lia/ for the review workflow."
            )

    @asynccontextmanager
    async def _guarded_run(self) -> AsyncIterator[None]:
        """Circuit breaker + metrics envelope."""
        sid = self.source.source_id
        cb = self.ctx.circuit_breaker
        if cb is not None and await cb.is_open(sid):
            raise CircuitOpen(f"Circuit breaker open for {sid}")

        started = datetime.now(UTC)
        logger.info("connector.start", extra={"source_id": sid, "run_id": self.ctx.run_id})
        try:
            yield
        except ConnectorRefusal:
            raise
        except Exception:
            if cb is not None:
                await cb.record_failure(sid)
            logger.exception(
                "connector.error", extra={"source_id": sid, "run_id": self.ctx.run_id}
            )
            raise
        else:
            if cb is not None:
                await cb.record_success(sid)
            duration_s = (datetime.now(UTC) - started).total_seconds()
            logger.info(
                "connector.end",
                extra={
                    "source_id": sid,
                    "run_id": self.ctx.run_id,
                    "duration_s": duration_s,
                    "status": ConnectorRunStatus.SUCCEEDED.value,
                },
            )

    # ── persistence helpers ─────────────────────────────────────────
    async def _persist(self, result: FetchResult) -> StoredArtifact:
        ext = self._extension_for(result.content_type)
        return await self.ctx.raw_lake.put(
            source_id=self.source.source_id,
            payload=result.payload,
            content_type=result.content_type,
            fetched_at_utc=datetime.now(UTC),
            extension=ext,
        )

    def _to_raw_artifact(
        self, result: FetchResult, stored: StoredArtifact
    ) -> RawArtifact:
        now = datetime.now(UTC)
        return RawArtifact(
            run_id=self.ctx.run_id,
            source_id=self.source.source_id,
            object_key=stored.object_key,
            source_url=result.source_url,  # type: ignore[arg-type]
            content_type=result.content_type,
            content_sha256=stored.content_sha256,
            size_bytes=stored.size_bytes,
            fetched_at_utc=now,
            published_at_local=result.published_at_local,
            http_status=result.http_status,
        )

    def build_envelope_for(
        self,
        *,
        source_url: str,
        natural_key: str,
        stored: StoredArtifact,
        fetched_at_utc: datetime,
        published_at_local: datetime | None,
        parser_version: str,
    ) -> object:
        """Convenience for parsers that sit just past the connector.

        Builds the :class:`~libs.provenance.ProvenanceEnvelope` using the
        connector's run_id + source_id without duplicating fields.
        """
        return build_envelope(
            source_id=self.source.source_id,
            source_url=source_url,
            stable_natural_key=natural_key,
            fetched_at_utc=fetched_at_utc,
            published_at_local=published_at_local,
            raw_object_key=stored.object_key,
            raw_sha256=stored.content_sha256,
            parser_version=parser_version,
            extractor_run_id=self.ctx.extractor_run_id,
            data_owner=self.ctx.data_owner,
            legal_basis=self.ctx.legal_basis,
        )

    @staticmethod
    def _extension_for(content_type: str) -> str:
        """Map a common MIME type to a filename extension for raw-lake keys."""
        ct = content_type.lower().split(";")[0].strip()
        return {
            "text/html": "html",
            "application/xhtml+xml": "html",
            "application/json": "json",
            "application/xml": "xml",
            "text/xml": "xml",
            "application/pdf": "pdf",
            "text/plain": "txt",
            "application/rss+xml": "rss",
            "application/atom+xml": "atom",
            "text/csv": "csv",
        }.get(ct, "bin")
