from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.cache import CacheClient  # noqa: F401  (PEP 563 string-annotation reference)

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    reset_at: int
    retry_after_seconds: int


class RateLimiter:
    """Fixed-window rate limiter, Redis-backed with in-memory fallback.

    Uses INCR + EXPIRE for atomic counting in Redis. When Redis is unavailable
    (or transiently fails), the limiter falls back to a per-process counter so
    the API stays available — accepting a small risk of over-limit behaviour
    across multiple instances during the outage.
    """

    def __init__(self, cache_client: CacheClient | None = None) -> None:
        self._cache = cache_client
        self._memory: dict[str, tuple[int, float]] = {}
        self._lock = asyncio.Lock()

    async def check(
        self,
        identity: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> RateLimitDecision:
        if limit <= 0 or window_seconds <= 0:
            now = int(time.time())
            return RateLimitDecision(
                allowed=True,
                limit=0,
                remaining=0,
                reset_at=now,
                retry_after_seconds=0,
            )

        now = int(time.time())
        window_start = now - (now % window_seconds)
        reset_at = window_start + window_seconds
        key = f"rl:{identity}:{window_start}"

        count = await self._incr(key, window_seconds=window_seconds, expires_at=float(reset_at))

        if count <= limit:
            return RateLimitDecision(
                allowed=True,
                limit=limit,
                remaining=max(0, limit - count),
                reset_at=reset_at,
                retry_after_seconds=0,
            )
        return RateLimitDecision(
            allowed=False,
            limit=limit,
            remaining=0,
            reset_at=reset_at,
            retry_after_seconds=max(1, reset_at - now),
        )

    async def _incr(self, key: str, *, window_seconds: int, expires_at: float) -> int:
        redis = self._cache._client if self._cache else None
        if redis is not None:
            try:
                count = await redis.incr(key)
                if int(count) == 1:
                    await redis.expire(key, window_seconds)
                return int(count)
            except Exception as exc:  # pragma: no cover - network failure path
                logger.warning(
                    "rate_limit_redis_failed_fallback_memory",
                    extra={"extra": {"error": str(exc)}},
                )
        return await self._memory_incr(key, expires_at=expires_at)

    async def _memory_incr(self, key: str, *, expires_at: float) -> int:
        async with self._lock:
            now = time.time()
            count, exp = self._memory.get(key, (0, 0.0))
            if exp <= now:
                count = 0
            count += 1
            self._memory[key] = (count, expires_at)
            if len(self._memory) > 1024:
                self._cleanup_memory(now)
            return count

    def _cleanup_memory(self, now: float) -> None:
        expired = [k for k, (_, exp) in self._memory.items() if exp <= now]
        for k in expired:
            self._memory.pop(k, None)
