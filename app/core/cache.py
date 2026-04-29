from __future__ import annotations

import json
import logging
from typing import Any

from redis.asyncio import Redis

from app.core.settings import get_settings

logger = logging.getLogger(__name__)


class CacheClient:
    def __init__(self) -> None:
        self._client: Redis | None = None
        self._memory_store: dict[str, str] = {}
        self.settings = get_settings()

    async def connect(self) -> None:
        try:
            self._client = Redis.from_url(self.settings.redis_url, encoding="utf-8", decode_responses=True)
            await self._client.ping()
            logger.info("redis_connected", extra={"extra": {"redis_url": self.settings.redis_url}})
        except Exception as exc:  # pragma: no cover
            self._client = None
            logger.warning(
                "redis_unavailable_fallback_memory",
                extra={"extra": {"error": str(exc)}},
            )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close(close_connection_pool=True)

    async def get_json(self, key: str) -> dict[str, Any] | None:
        raw: str | None
        if self._client is not None:
            raw = await self._client.get(key)
        else:
            raw = self._memory_store.get(key)

        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    async def set_json(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        raw = json.dumps(value)
        if self._client is not None:
            await self._client.setex(key, ttl_seconds, raw)
        else:
            self._memory_store[key] = raw


cache_client = CacheClient()
