from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app.core.cache import cache_client
from app.core.database import engine
from app.core.metrics import REGISTRY
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

router = APIRouter(tags=["ops"])


@router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def readiness_check(request: Request) -> dict[str, object]:
    db_ok = True
    redis_ok = True
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    try:
        if cache_client._client is not None:
            await cache_client._client.ping()
        else:
            redis_ok = False
    except Exception:
        redis_ok = False
    return {
        "status": "ok" if db_ok and redis_ok else "degraded",
        "database": "ok" if db_ok else "down",
        "cache": "ok" if redis_ok else "down",
    }


@router.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
