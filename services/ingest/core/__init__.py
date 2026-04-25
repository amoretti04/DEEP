"""Connector framework — shared scaffolding for every concrete connector."""

from services.ingest.core.base import ConnectorContext, FetchResult, SourceConnector
from services.ingest.core.rate_limiter import (
    InMemoryRateLimiter,
    RateLimiter,
    RedisRateLimiter,
)
from services.ingest.core.raw_lake import RawLake, S3RawLake

__all__ = [
    "ConnectorContext",
    "FetchResult",
    "InMemoryRateLimiter",
    "RateLimiter",
    "RawLake",
    "RedisRateLimiter",
    "S3RawLake",
    "SourceConnector",
]
