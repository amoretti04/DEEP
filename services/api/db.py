"""Database session wiring."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from services.api.settings import get_settings


def make_engine(dsn: str | None = None) -> object:
    url = dsn or get_settings().database_url
    return create_async_engine(url, pool_pre_ping=True, echo=False)


_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _lazy_init() -> async_sessionmaker[AsyncSession]:
    global _engine, _sessionmaker  # noqa: PLW0603
    if _sessionmaker is None:
        _engine = make_engine()
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)  # type: ignore[arg-type]
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    sm = _lazy_init()
    async with sm() as session:
        yield session


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Programmatic context manager for scripts and workers."""
    sm = _lazy_init()
    async with sm() as session:
        yield session
