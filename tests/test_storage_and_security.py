from __future__ import annotations

from app.core.security import sign_payload
from app.core.storage import LocalDocumentStorage


import pytest


@pytest.mark.asyncio
async def test_local_storage_round_trip(tmp_path) -> None:
    storage = LocalDocumentStorage(tmp_path)
    uri = await storage.put("a/b/c.txt", b"hello", content_type="text/plain")
    assert uri.startswith("file://")
    payload = await storage.get("a/b/c.txt")
    assert payload == b"hello"


def test_sign_payload_is_stable() -> None:
    sig = sign_payload("secret", b"payload")
    assert sig.startswith("sha256=")
    assert sign_payload("secret", b"payload") == sig
    assert sign_payload("other", b"payload") != sig
