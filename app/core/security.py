from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from app.core.settings import Settings, get_settings


def _matches_any(provided: str, candidates: list[str]) -> bool:
    return any(secrets.compare_digest(provided, candidate) for candidate in candidates)


def require_api_key(
    request: Request,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> str:
    settings: Settings = get_settings()
    if not settings.api_keys:
        return "anonymous"

    if not x_api_key or not _matches_any(x_api_key, settings.api_keys):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing API key",
        )

    request.state.api_key_id = hashlib.sha256(x_api_key.encode()).hexdigest()[:12]
    return request.state.api_key_id


def require_internal_api_key(
    request: Request,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> str:
    settings: Settings = get_settings()
    accepted = settings.internal_api_keys or settings.api_keys
    if not accepted:
        return "anonymous"

    if not x_api_key or not _matches_any(x_api_key, accepted):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing internal API key",
        )

    request.state.api_key_id = hashlib.sha256(x_api_key.encode()).hexdigest()[:12]
    return request.state.api_key_id


ApiKeyDep = Annotated[str, Depends(require_api_key)]
InternalApiKeyDep = Annotated[str, Depends(require_internal_api_key)]


def resolve_tenant_id(request: Request) -> str | None:
    """Return the authenticated tenant identity, or None for anonymous/local mode.

    Identity is derived ONLY from the validated API key (``request.state.api_key_id``,
    set by :func:`require_api_key`/``require_internal_api_key``). The ``X-Tenant-Id``
    header is intentionally ignored: a client must not be able to choose its own
    tenant. When no API keys are configured (local/test mode) ``api_key_id`` is
    not set on request.state and we return ``None`` — the DB column is nullable
    for exactly this case.
    """
    api_key_id = getattr(request.state, "api_key_id", None)
    if not api_key_id or api_key_id == "anonymous":
        return None
    return str(api_key_id)


def sign_payload(secret: str, payload: bytes) -> str:
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"
