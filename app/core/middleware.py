from __future__ import annotations

import hashlib
import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core.metrics import RATE_LIMIT_REJECTED
from app.core.rate_limit import RateLimitDecision, RateLimiter

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming if incoming and len(incoming) <= 64 else str(uuid.uuid4())
        request.state.request_id = request_id

        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.exception(
                "request_failed",
                extra={
                    "extra": {
                        "request_id": request_id,
                        "path": request.url.path,
                        "method": request.method,
                        "duration_ms": duration_ms,
                    }
                },
            )
            raise

        duration_ms = int((time.perf_counter() - start) * 1000)
        response.headers[REQUEST_ID_HEADER] = request_id
        logger.info(
            "request_completed",
            extra={
                "extra": {
                    "request_id": request_id,
                    "path": request.url.path,
                    "method": request.method,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                }
            },
        )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per API-key (and per-tenant) request rate limiting.

    Identity precedence:
      1. ``X-API-Key`` header (hashed) + ``X-Tenant-Id``
      2. Client IP + ``X-Tenant-Id`` (anonymous limit)

    Excluded paths bypass the limiter entirely (health, readiness, metrics
    and OpenAPI documentation by default).
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        limiter: RateLimiter,
        limit_per_window: int,
        window_seconds: int,
        excluded_paths: tuple[str, ...] = (),
        anonymous_limit: int | None = None,
    ) -> None:
        super().__init__(app)
        self._limiter = limiter
        self._limit = limit_per_window
        self._window = window_seconds
        self._excluded = tuple(p.rstrip("/") or "/" for p in excluded_paths)
        self._anonymous_limit = (
            anonymous_limit if anonymous_limit is not None else limit_per_window
        )

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if self._is_excluded(request.url.path):
            return await call_next(request)

        identity, limit = self._compute_identity(request)
        if identity is None:
            return await call_next(request)

        decision = await self._limiter.check(
            identity, limit=limit, window_seconds=self._window
        )
        if not decision.allowed:
            kind = identity.split(":", 1)[0]
            RATE_LIMIT_REJECTED.labels(identity_kind=kind).inc()
            request_id = getattr(request.state, "request_id", None)
            payload: dict[str, object] = {
                "error": {
                    "code": "rate_limit_exceeded",
                    "message": "request rate limit exceeded",
                }
            }
            if request_id:
                payload["request_id"] = request_id
            rejection: Response = JSONResponse(status_code=429, content=payload)
            rejection.headers["Retry-After"] = str(decision.retry_after_seconds)
            self._write_headers(rejection, decision)
            logger.info(
                "rate_limit_rejected",
                extra={
                    "extra": {
                        "request_id": request_id,
                        "identity_kind": kind,
                        "path": request.url.path,
                        "limit": decision.limit,
                    }
                },
            )
            return rejection

        response = await call_next(request)
        self._write_headers(response, decision)
        return response

    def _is_excluded(self, path: str) -> bool:
        normalized = path.rstrip("/") or "/"
        for excluded in self._excluded:
            if normalized == excluded:
                return True
            if excluded != "/" and normalized.startswith(excluded + "/"):
                return True
        return False

    def _compute_identity(self, request: Request) -> tuple[str | None, int]:
        api_key = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
        tenant = (request.headers.get("X-Tenant-Id") or "default").strip()[:64] or "default"
        if api_key:
            digest = hashlib.sha256(api_key.encode()).hexdigest()[:16]
            return f"api:{digest}:{tenant}", self._limit
        client = request.client
        if client and client.host:
            return f"ip:{client.host}:{tenant}", self._anonymous_limit
        return None, 0

    @staticmethod
    def _write_headers(response: Response, decision: RateLimitDecision) -> None:
        if decision.limit > 0:
            response.headers["X-RateLimit-Limit"] = str(decision.limit)
            response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
            response.headers["X-RateLimit-Reset"] = str(decision.reset_at)
