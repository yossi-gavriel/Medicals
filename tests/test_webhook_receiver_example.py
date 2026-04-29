from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import sign_payload
from scripts.webhook_receiver_example import build_app, verify_signature


def test_verify_signature_accepts_matching_hmac() -> None:
    body = b'{"job_id":"abc"}'
    provided = sign_payload("shh", body)
    assert verify_signature("shh", body, provided)


def test_verify_signature_rejects_mismatched_secret() -> None:
    body = b'{"job_id":"abc"}'
    provided = sign_payload("shh", body)
    assert not verify_signature("other-secret", body, provided)


def test_verify_signature_rejects_missing_or_malformed() -> None:
    assert not verify_signature("shh", b"x", None)
    assert not verify_signature("shh", b"x", "missing-prefix")
    assert not verify_signature("shh", b"x", "sha256=")


def test_build_app_requires_secret() -> None:
    with pytest.raises(ValueError):
        build_app("")


@pytest.mark.asyncio
async def test_receiver_accepts_signed_request() -> None:
    secret = "shared-secret"
    app = build_app(secret)
    body = {"event": "classification.completed", "job_id": "abc", "result_code": 1}
    raw = json.dumps(body, separators=(",", ":")).encode()
    headers = {
        "X-Signature": sign_payload(secret, raw),
        "X-Event-Id": "ev-1",
        "X-Event-Type": "classification.completed",
        "Content-Type": "application/json",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/hooks/classifications",
            content=raw,
            headers=headers,
        )
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_receiver_rejects_unsigned_request() -> None:
    secret = "shared-secret"
    app = build_app(secret)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/hooks/classifications",
            json={"job_id": "abc"},
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_receiver_rejects_signature_for_different_body() -> None:
    secret = "shared-secret"
    app = build_app(secret)
    raw_body = b'{"job_id":"abc"}'
    other_body = b'{"job_id":"different"}'
    headers = {
        "X-Signature": sign_payload(secret, raw_body),
        "Content-Type": "application/json",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/hooks/classifications",
            content=other_body,
            headers=headers,
        )
    assert response.status_code == 401
