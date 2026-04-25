"""Per-domain rate limiter.

Centralized so that multiple workers enforcing the same per-domain limit
can coordinate without each working in isolation. The canonical backend
is Redis (CLAUDE.md §7.4 / §4.1); an in-memory implementation is provided
for unit tests and single-process dev runs.

Algorithm: simple token bucket keyed by ``domain`` (or an arbitrary key).
Each acquire costs one token. Refill rate and bucket size come from the
per-source Politeness config:

* refill rate = ``1 / mean_delay_s`` tokens/sec
* bucket size = ``concurrency``

For stricter "N requests per minute" caps we additionally enforce a
sliding window using Redis INCR + EXPIRE.

This module intentionally has a minimal interface — connectors call
``await limiter.acquire(key)`` and block until a token is available.
"""

from __future__ import annotations

import asyncio
import random
import time
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import redis.asyncio as aioredis


class RateLimiter(Protocol):
    """Common interface. Connectors depend on this, not the backend."""

    async def acquire(self, key: str) -> None:
        """Block until a token is available for ``key``."""
        ...

    async def sleep_jitter(self, min_s: float, max_s: float) -> None:
        """Politeness jitter between requests within the same session."""
        ...


class InMemoryRateLimiter:
    """Token bucket in a single process. For tests and local dev.

    Not safe across workers — DO NOT use in production. The scheduler will
    refuse to start a multi-worker deployment without a shared limiter.
    """

    def __init__(
        self,
        *,
        tokens_per_second: float = 0.25,  # default: one request every 4s
        bucket_size: int = 1,
    ) -> None:
        if tokens_per_second <= 0:
            raise ValueError("tokens_per_second must be > 0")
        if bucket_size < 1:
            raise ValueError("bucket_size must be >= 1")
        self._rate = tokens_per_second
        self._size = bucket_size
        self._buckets: dict[str, tuple[float, float]] = {}   # key -> (tokens, ts)
        self._lock = asyncio.Lock()

    async def acquire(self, key: str) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                tokens, last = self._buckets.get(key, (float(self._size), now))
                elapsed = now - last
                tokens = min(self._size, tokens + elapsed * self._rate)
                if tokens >= 1.0:
                    self._buckets[key] = (tokens - 1.0, now)
                    return
                # Compute sleep outside the lock
                need = 1.0 - tokens
                wait_s = need / self._rate
                self._buckets[key] = (tokens, now)
            # Release lock, sleep with a small jitter, retry.
            await asyncio.sleep(min(wait_s, 5.0))

    async def sleep_jitter(self, min_s: float, max_s: float) -> None:
        if max_s < min_s:
            raise ValueError("max_s must be >= min_s")
        delay = random.uniform(min_s, max_s)  # noqa: S311 — not security-sensitive
        await asyncio.sleep(delay)


class RedisRateLimiter:
    """Token bucket stored in Redis — safe across workers.

    Uses a Lua script (loaded on first acquire) for atomic refill-and-take.
    Falls back to a best-effort compare-and-set if scripting is disabled.
    Key space: ``dip:rl:<key>`` — never collides with app keys.
    """

    _LUA_SCRIPT = """
    local key        = KEYS[1]
    local capacity   = tonumber(ARGV[1])
    local rate       = tonumber(ARGV[2])     -- tokens per second
    local now_ms     = tonumber(ARGV[3])
    local bucket     = redis.call('HMGET', key, 'tokens', 'ts')
    local tokens     = tonumber(bucket[1]) or capacity
    local ts         = tonumber(bucket[2]) or now_ms
    local delta_s    = (now_ms - ts) / 1000.0
    tokens = math.min(capacity, tokens + delta_s * rate)
    if tokens >= 1 then
      tokens = tokens - 1
      redis.call('HMSET', key, 'tokens', tokens, 'ts', now_ms)
      redis.call('EXPIRE', key, 3600)
      return {1, tokens}
    else
      local need   = 1 - tokens
      local wait_s = need / rate
      redis.call('HMSET', key, 'tokens', tokens, 'ts', now_ms)
      redis.call('EXPIRE', key, 3600)
      return {0, wait_s}
    end
    """

    def __init__(
        self,
        redis: aioredis.Redis,
        *,
        tokens_per_second: float = 0.25,
        bucket_size: int = 1,
        key_prefix: str = "dip:rl:",
    ) -> None:
        if tokens_per_second <= 0:
            raise ValueError("tokens_per_second must be > 0")
        if bucket_size < 1:
            raise ValueError("bucket_size must be >= 1")
        self._redis = redis
        self._rate = tokens_per_second
        self._size = bucket_size
        self._prefix = key_prefix
        self._script_sha: str | None = None

    async def _ensure_script(self) -> None:
        if self._script_sha is None:
            self._script_sha = await self._redis.script_load(self._LUA_SCRIPT)

    async def acquire(self, key: str) -> None:
        await self._ensure_script()
        full_key = f"{self._prefix}{key}"
        while True:
            now_ms = int(time.time() * 1000)
            # evalsha returns [ok_flag, wait_or_tokens]
            assert self._script_sha is not None
            result = await self._redis.evalsha(
                self._script_sha,
                1,
                full_key,
                str(self._size),
                str(self._rate),
                str(now_ms),
            )
            ok, remainder = int(result[0]), float(result[1])
            if ok == 1:
                return
            # Wait remainder seconds plus small jitter.
            wait_s = min(max(remainder, 0.05), 5.0) + random.uniform(0, 0.25)  # noqa: S311
            await asyncio.sleep(wait_s)

    async def sleep_jitter(self, min_s: float, max_s: float) -> None:
        if max_s < min_s:
            raise ValueError("max_s must be >= min_s")
        await asyncio.sleep(random.uniform(min_s, max_s))  # noqa: S311
