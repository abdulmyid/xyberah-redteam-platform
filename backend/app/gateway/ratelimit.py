"""Leaky-bucket rate limiting and response caching, Redis-backed with an
in-process fallback.

Leaky bucket (as a meter): each consumer has a bucket of ``capacity`` units that
drains continuously at ``capacity / 60`` units per second. A request adds its cost
(1 for request limits, estimated tokens for token limits); it is rejected if the
bucket would overflow, with a precise Retry-After. Completion tokens are charged
after the response (``force``), so heavy consumers are throttled on their next
request. The Redis path is a single atomic Lua script using the server clock, so
limits hold across any number of gateway replicas.

If Redis is unreachable the gateway keeps serving using per-process buckets and
cache, and retries Redis periodically.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Optional

log = logging.getLogger("xyberah.gateway.ratelimit")

_LEAKY_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local cost = tonumber(ARGV[3])
local force = tonumber(ARGV[4])
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
local level = tonumber(redis.call('HGET', key, 'l') or '0')
local ts = tonumber(redis.call('HGET', key, 't') or tostring(now))
level = math.max(0, level - (now - ts) * rate)
local ttl = math.ceil(capacity / rate) + 60
if force == 0 and level + cost > capacity then
  redis.call('HSET', key, 'l', tostring(level), 't', tostring(now))
  redis.call('EXPIRE', key, ttl)
  return {0, tostring((level + cost - capacity) / rate)}
end
level = level + cost
redis.call('HSET', key, 'l', tostring(level), 't', tostring(now))
redis.call('EXPIRE', key, ttl)
return {1, tostring(level)}
"""


@dataclass
class LimitResult:
    """Outcome of a bucket check."""

    allowed: bool
    retry_after: float = 0.0


class _MemoryBucket:
    __slots__ = ("level", "ts")

    def __init__(self) -> None:
        self.level = 0.0
        self.ts = time.monotonic()


class Limiter:
    """Leaky-bucket limiter and TTL response cache with Redis + memory fallback."""

    RETRY_REDIS_SECONDS = 30.0
    MEMORY_CACHE_MAX = 2000

    def __init__(self, redis_url: str = "") -> None:
        self._redis_url = redis_url
        self._redis: Any = None
        self._script: Any = None
        self._redis_ok = False
        self._next_retry = 0.0
        self._buckets: dict[str, _MemoryBucket] = {}
        self._lock = asyncio.Lock()
        self._cache: OrderedDict[str, tuple[float, str]] = OrderedDict()

    @property
    def backend(self) -> str:
        """``redis`` when Redis is in use, else ``memory``."""
        return "redis" if self._redis_ok else "memory"

    async def connect(self) -> None:
        """Connect to Redis if configured; failure leaves the memory fallback active."""
        if not self._redis_url:
            return
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(self._redis_url, socket_timeout=0.5,
                                            socket_connect_timeout=1.0, decode_responses=True)
            await self._redis.ping()
            self._script = self._redis.register_script(_LEAKY_LUA)
            self._redis_ok = True
            log.info("rate limiter using Redis")
        except Exception as exc:  # noqa: BLE001 - any connection failure means fallback
            self._redis_ok = False
            self._next_retry = time.monotonic() + self.RETRY_REDIS_SECONDS
            log.warning("Redis unavailable (%s); using in-memory rate limiting and cache", exc)

    async def close(self) -> None:
        """Close the Redis connection pool."""
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:  # noqa: BLE001
                pass

    async def _maybe_reconnect(self) -> None:
        if self._redis_url and not self._redis_ok and time.monotonic() >= self._next_retry:
            await self.connect()

    def _redis_failed(self, exc: Exception) -> None:
        log.warning("Redis operation failed (%s); falling back to memory", exc)
        self._redis_ok = False
        self._next_retry = time.monotonic() + self.RETRY_REDIS_SECONDS

    async def hit(self, key: str, capacity: int, cost: float, force: bool = False) -> LimitResult:
        """Add ``cost`` to bucket ``key`` (capacity per minute). ``capacity <= 0`` is unlimited."""
        if capacity <= 0:
            return LimitResult(True)
        if cost > capacity and not force:
            return LimitResult(False, 60.0)
        rate = capacity / 60.0
        await self._maybe_reconnect()
        if self._redis_ok:
            try:
                ok, value = await self._script(keys=[f"xgw:rl:{key}"], args=[capacity, rate, cost, 1 if force else 0])
                return LimitResult(bool(int(ok)), 0.0 if int(ok) else float(value))
            except Exception as exc:  # noqa: BLE001
                self._redis_failed(exc)
        async with self._lock:
            bucket = self._buckets.setdefault(key, _MemoryBucket())
            now = time.monotonic()
            bucket.level = max(0.0, bucket.level - (now - bucket.ts) * rate)
            bucket.ts = now
            if not force and bucket.level + cost > capacity:
                return LimitResult(False, (bucket.level + cost - capacity) / rate)
            bucket.level += cost
            if len(self._buckets) > 50_000:
                self._buckets.pop(next(iter(self._buckets)))
            return LimitResult(True)

    async def cache_get(self, key: str) -> Optional[dict[str, Any]]:
        """Return a cached response entry or None."""
        await self._maybe_reconnect()
        if self._redis_ok:
            try:
                raw = await self._redis.get(f"xgw:cache:{key}")
                return json.loads(raw) if raw else None
            except Exception as exc:  # noqa: BLE001
                self._redis_failed(exc)
        entry = self._cache.get(key)
        if entry is None:
            return None
        expires, raw_mem = entry
        if expires < time.monotonic():
            self._cache.pop(key, None)
            return None
        self._cache.move_to_end(key)
        return json.loads(raw_mem)

    async def cache_set(self, key: str, value: dict[str, Any], ttl: int) -> None:
        """Store a response entry for ``ttl`` seconds."""
        raw = json.dumps(value, separators=(",", ":"))
        if len(raw) > 2_000_000:
            return
        if self._redis_ok:
            try:
                await self._redis.set(f"xgw:cache:{key}", raw, ex=max(1, ttl))
                return
            except Exception as exc:  # noqa: BLE001
                self._redis_failed(exc)
        self._cache[key] = (time.monotonic() + max(1, ttl), raw)
        self._cache.move_to_end(key)
        while len(self._cache) > self.MEMORY_CACHE_MAX:
            self._cache.popitem(last=False)

    async def ping(self) -> bool:
        """True if Redis answers (False when not configured or down)."""
        if not self._redis_ok:
            return False
        try:
            return bool(await self._redis.ping())
        except Exception as exc:  # noqa: BLE001
            self._redis_failed(exc)
            return False
