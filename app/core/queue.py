from __future__ import annotations

import logging
from typing import Any, Protocol

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.settings import Settings

logger = logging.getLogger(__name__)


class JobEnqueuer(Protocol):
    async def enqueue(self, function: str, **kwargs: Any) -> str:
        ...


def _redis_settings_from_url(url: str) -> RedisSettings:
    return RedisSettings.from_dsn(url)


class ArqJobEnqueuer:
    def __init__(self, pool: ArqRedis) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, settings: Settings) -> "ArqJobEnqueuer":
        pool = await create_pool(_redis_settings_from_url(settings.queue_redis_url))
        return cls(pool)

    async def close(self) -> None:
        await self._pool.aclose()

    async def enqueue(self, function: str, **kwargs: Any) -> str:
        job = await self._pool.enqueue_job(function, **kwargs)
        if job is None:
            raise RuntimeError(f"failed to enqueue job for {function}")
        return job.job_id


class InMemoryJobEnqueuer:
    """Fallback used in tests when no Redis queue is available."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def enqueue(self, function: str, **kwargs: Any) -> str:
        self.calls.append((function, kwargs))
        return f"in-memory-{len(self.calls)}"
