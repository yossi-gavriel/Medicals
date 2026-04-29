from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.middleware import RateLimitMiddleware
from app.core.rate_limit import RateLimiter


def _build_app(*, limit: int, window: int = 60, anonymous_limit: int | None = None) -> FastAPI:
    app = FastAPI()
    limiter = RateLimiter(cache_client=None)
    app.add_middleware(
        RateLimitMiddleware,
        limiter=limiter,
        limit_per_window=limit,
        window_seconds=window,
        excluded_paths=("/health",),
        anonymous_limit=anonymous_limit,
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/whoami")
    async def whoami() -> dict[str, str]:
        return {"ok": "true"}

    return app


@pytest.mark.asyncio
async def test_rate_limiter_in_memory_blocks_above_limit() -> None:
    limiter = RateLimiter(cache_client=None)
    decisions = []
    for _ in range(3):
        decisions.append(await limiter.check("k", limit=2, window_seconds=60))
    assert decisions[0].allowed is True
    assert decisions[1].allowed is True
    assert decisions[2].allowed is False
    assert decisions[2].retry_after_seconds >= 1
    assert decisions[2].limit == 2
    assert decisions[2].remaining == 0


@pytest.mark.asyncio
async def test_rate_limiter_zero_limit_treated_as_disabled() -> None:
    limiter = RateLimiter(cache_client=None)
    for _ in range(10):
        decision = await limiter.check("k", limit=0, window_seconds=60)
        assert decision.allowed is True
        assert decision.limit == 0


@pytest.mark.asyncio
async def test_rate_limiter_separate_identities_have_independent_buckets() -> None:
    limiter = RateLimiter(cache_client=None)
    a1 = await limiter.check("a", limit=1, window_seconds=60)
    b1 = await limiter.check("b", limit=1, window_seconds=60)
    a2 = await limiter.check("a", limit=1, window_seconds=60)
    assert a1.allowed and b1.allowed
    assert not a2.allowed


@pytest.mark.asyncio
async def test_middleware_excluded_paths_are_not_limited() -> None:
    app = _build_app(limit=1)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for _ in range(5):
            response = await client.get("/health", headers={"X-API-Key": "k1"})
            assert response.status_code == 200
            assert "X-RateLimit-Limit" not in response.headers


@pytest.mark.asyncio
async def test_middleware_returns_429_with_headers_when_exceeded() -> None:
    app = _build_app(limit=2)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ok1 = await client.get("/whoami", headers={"X-API-Key": "kk"})
        ok2 = await client.get("/whoami", headers={"X-API-Key": "kk"})
        rejected = await client.get("/whoami", headers={"X-API-Key": "kk"})

    assert ok1.status_code == 200
    assert ok2.status_code == 200
    assert rejected.status_code == 429

    assert ok1.headers["X-RateLimit-Limit"] == "2"
    assert ok1.headers["X-RateLimit-Remaining"] == "1"
    assert "X-RateLimit-Reset" in ok1.headers

    assert rejected.headers["X-RateLimit-Limit"] == "2"
    assert rejected.headers["X-RateLimit-Remaining"] == "0"
    assert int(rejected.headers["Retry-After"]) >= 1
    body = rejected.json()
    assert body["error"]["code"] == "rate_limit_exceeded"


@pytest.mark.asyncio
async def test_middleware_uses_api_key_plus_tenant_for_identity() -> None:
    app = _build_app(limit=1)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        a = await client.get(
            "/whoami", headers={"X-API-Key": "k", "X-Tenant-Id": "tenant-a"}
        )
        b = await client.get(
            "/whoami", headers={"X-API-Key": "k", "X-Tenant-Id": "tenant-b"}
        )
        a2 = await client.get(
            "/whoami", headers={"X-API-Key": "k", "X-Tenant-Id": "tenant-a"}
        )

    assert a.status_code == 200
    assert b.status_code == 200
    assert a2.status_code == 429


@pytest.mark.asyncio
async def test_middleware_falls_back_to_ip_when_no_api_key() -> None:
    app = _build_app(limit=2, anonymous_limit=1)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.get("/whoami")
        second = await client.get("/whoami")

    assert first.status_code == 200
    assert first.headers["X-RateLimit-Limit"] == "1"
    assert second.status_code == 429


@pytest.mark.asyncio
async def test_rate_limiter_resets_when_window_elapses(monkeypatch) -> None:
    import app.core.rate_limit as rl_module

    base_time = 1_000_000.0
    current = {"value": base_time}

    def fake_time() -> float:
        return current["value"]

    monkeypatch.setattr(rl_module.time, "time", fake_time)

    limiter = RateLimiter(cache_client=None)
    first = await limiter.check("kk", limit=1, window_seconds=10)
    second = await limiter.check("kk", limit=1, window_seconds=10)
    assert first.allowed
    assert not second.allowed

    current["value"] = base_time + 11
    third = await limiter.check("kk", limit=1, window_seconds=10)
    assert third.allowed
    assert third.remaining == 0
