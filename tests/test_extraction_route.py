from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.routes_extractions import router
from app.core.database import Base, get_db_session
from app.core.settings import get_settings
from app.models import ExtractionAudit, ExtractionRow, ExtractionRun
from app.services.extraction_engine import ExtractionEngine


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    db_url = f"sqlite+aiosqlite:///{tmp_path/'test.db'}"
    try:
        engine = create_async_engine(db_url, future=True)
    except ModuleNotFoundError:  # pragma: no cover
        pytest.skip("aiosqlite is required for async SQLite tests")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


def _build_client(
    engine: ExtractionEngine | None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> TestClient:
    app = FastAPI()
    app.state.extraction_engine = engine
    app.include_router(router)

    if session_factory is not None:
        async def _override_session() -> AsyncGenerator[AsyncSession, None]:
            async with session_factory() as session:
                yield session

        app.dependency_overrides[get_db_session] = _override_session

    return TestClient(app)


def _spec_payload() -> dict:
    return {
        "version": "1.0",
        "treatments": [
            {
                "treatment_code": "CATARACT_SURGERY",
                "rules": [
                    {
                        "field_name": "has_cataract_diagnosis",
                        "type": "boolean",
                        "positive_indicators": ["cataract"],
                        "negative_indicators": ["no cataract"],
                        "default_when_missing": False,
                    },
                    {
                        "field_name": "surgery_date",
                        "type": "date",
                    },
                    {
                        "field_name": "operated_eye",
                        "type": "enum",
                        "allowed_values": ["left", "right", "both", "unknown"],
                    },
                ],
            }
        ],
    }


def test_run_endpoint_returns_rows_and_audit(session_factory):
    client = _build_client(ExtractionEngine(), session_factory=session_factory)

    response = client.post(
        "/v1/extractions/run",
        json={
            "document_id": "doc_123",
            "document_text": "Cataract diagnosed; surgery date 10/02/2024. Left eye.",
            "spec": _spec_payload(),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["document_id"] == "doc_123"
    assert body["spec_version"] == "1.0"
    assert body["spec_hash"] and len(body["spec_hash"]) == 64
    assert body["run_id"]
    assert len(body["rows"]) == 1
    row = body["rows"][0]
    assert row == {
        "document_id": "doc_123",
        "treatment_code": "CATARACT_SURGERY",
        "has_cataract_diagnosis": True,
        "surgery_date": "2024-02-10",
        "operated_eye": "left",
    }
    audit_fields = {entry["field_name"] for entry in body["audit"]}
    assert audit_fields == {"has_cataract_diagnosis", "surgery_date", "operated_eye"}
    diag_audit = next(e for e in body["audit"] if e["field_name"] == "has_cataract_diagnosis")
    assert diag_audit["confidence"] > 0
    assert diag_audit["evidence"]
    assert diag_audit["reason"]


def test_run_endpoint_persists_run_rows_and_audit_in_one_transaction(session_factory):
    """End-to-end: a 200 response must mean the data is durably in the DB."""
    client = _build_client(ExtractionEngine(), session_factory=session_factory)

    response = client.post(
        "/v1/extractions/run",
        json={
            "document_id": "doc_persist",
            "document_text": "Cataract diagnosed; surgery date 10/02/2024. Left eye.",
            "spec": _spec_payload(),
        },
    )

    assert response.status_code == 200
    run_id_str = response.json()["run_id"]
    assert run_id_str

    import asyncio

    async def _verify():
        async with session_factory() as session:
            runs = (await session.execute(select(ExtractionRun))).scalars().all()
            rows = (await session.execute(select(ExtractionRow))).scalars().all()
            audit = (await session.execute(select(ExtractionAudit))).scalars().all()
        return runs, rows, audit

    runs, rows, audit = asyncio.get_event_loop().run_until_complete(_verify())
    assert len(runs) == 1
    assert str(runs[0].id) == run_id_str
    assert len(rows) == 1
    assert "document_id" not in rows[0].values
    assert "treatment_code" not in rows[0].values
    assert len(audit) == 3


def test_run_endpoint_response_shape_remains_stable(session_factory):
    """API consumers should see the same top-level keys as before plus run_id/spec_hash."""
    client = _build_client(ExtractionEngine(), session_factory=session_factory)

    response = client.post(
        "/v1/extractions/run",
        json={
            "document_id": "doc_shape",
            "document_text": "Cataract diagnosed.",
            "spec": _spec_payload(),
        },
    )

    body = response.json()
    assert set(body.keys()) == {
        "run_id",
        "document_id",
        "spec_version",
        "spec_hash",
        "rows",
        "audit",
        "compliance",
        "masked",
        "pii_masked_count",
    }


def test_run_endpoint_rejects_invalid_spec(session_factory):
    client = _build_client(ExtractionEngine(), session_factory=session_factory)

    response = client.post(
        "/v1/extractions/run",
        json={
            "document_id": "doc_1",
            "document_text": "text",
            "spec": {
                "version": "1.0",
                "treatments": [
                    {
                        "treatment_code": "X",
                        "rules": [
                            {"field_name": "a", "type": "boolean"},
                            {"field_name": "a", "type": "boolean"},
                        ],
                    }
                ],
            },
        },
    )

    assert response.status_code == 422


def test_run_endpoint_rejects_missing_document_text(session_factory):
    client = _build_client(ExtractionEngine(), session_factory=session_factory)

    response = client.post(
        "/v1/extractions/run",
        json={
            "document_id": "doc_1",
            "document_text": "",
            "spec": _spec_payload(),
        },
    )

    assert response.status_code == 422


def test_run_endpoint_returns_503_when_engine_not_initialized(session_factory):
    client = _build_client(engine=None, session_factory=session_factory)

    response = client.post(
        "/v1/extractions/run",
        json={
            "document_id": "doc_1",
            "document_text": "text",
            "spec": _spec_payload(),
        },
    )

    assert response.status_code == 503


@pytest.fixture
def _api_key_required(monkeypatch):
    """Force the API key requirement for the duration of one test.

    The security module imports get_settings by name, so we patch the bound
    reference there (and the original) rather than mutating env vars — which
    pydantic-settings would parse as JSON for list fields.
    """
    from app.core import security as security_module
    from app.core import settings as settings_module

    test_settings = settings_module.Settings(api_keys=["test-key-abc"])
    monkeypatch.setattr(security_module, "get_settings", lambda: test_settings)
    monkeypatch.setattr(settings_module, "get_settings", lambda: test_settings)
    get_settings.cache_clear()
    yield "test-key-abc"
    get_settings.cache_clear()


def test_run_endpoint_rejects_missing_api_key_when_keys_configured(
    _api_key_required, session_factory
):
    client = _build_client(ExtractionEngine(), session_factory=session_factory)

    response = client.post(
        "/v1/extractions/run",
        json={
            "document_id": "doc_x",
            "document_text": "Cataract diagnosed.",
            "spec": _spec_payload(),
        },
    )

    assert response.status_code == 401


def test_run_endpoint_accepts_correct_api_key_when_keys_configured(
    _api_key_required, session_factory
):
    client = _build_client(ExtractionEngine(), session_factory=session_factory)

    response = client.post(
        "/v1/extractions/run",
        headers={"X-API-Key": _api_key_required},
        json={
            "document_id": "doc_x",
            "document_text": "Cataract diagnosed.",
            "spec": _spec_payload(),
        },
    )

    assert response.status_code == 200


def test_authenticated_extraction_persists_tenant_id_from_api_key(
    _api_key_required, session_factory
):
    """Authenticated requests must persist the API-key-derived tenant identity."""
    client = _build_client(ExtractionEngine(), session_factory=session_factory)

    response = client.post(
        "/v1/extractions/run",
        headers={"X-API-Key": _api_key_required},
        json={
            "document_id": "doc_tenant",
            "document_text": "Cataract diagnosed.",
            "spec": _spec_payload(),
        },
    )

    assert response.status_code == 200

    import asyncio

    async def _fetch():
        async with session_factory() as session:
            return (await session.execute(select(ExtractionRun))).scalars().all()

    runs = asyncio.get_event_loop().run_until_complete(_fetch())
    assert len(runs) == 1
    # tenant_id is the sha256(api_key)[:12] hash assigned by require_api_key.
    import hashlib

    expected_hash = hashlib.sha256(_api_key_required.encode()).hexdigest()[:12]
    assert runs[0].tenant_id == expected_hash


def test_invalid_api_key_does_not_persist_anything(_api_key_required, session_factory):
    client = _build_client(ExtractionEngine(), session_factory=session_factory)

    response = client.post(
        "/v1/extractions/run",
        headers={"X-API-Key": "WRONG-KEY"},
        json={
            "document_id": "doc_no_persist",
            "document_text": "Cataract diagnosed.",
            "spec": _spec_payload(),
        },
    )
    assert response.status_code == 401

    import asyncio

    async def _fetch():
        async with session_factory() as session:
            return (await session.execute(select(ExtractionRun))).scalars().all()

    runs = asyncio.get_event_loop().run_until_complete(_fetch())
    assert runs == []


def test_x_tenant_id_header_alone_is_not_trusted(_api_key_required, session_factory):
    """When the client supplies X-Tenant-Id without an API key, it is rejected."""
    client = _build_client(ExtractionEngine(), session_factory=session_factory)

    response = client.post(
        "/v1/extractions/run",
        headers={"X-Tenant-Id": "evil-tenant"},
        json={
            "document_id": "doc_tenant_only",
            "document_text": "Cataract diagnosed.",
            "spec": _spec_payload(),
        },
    )
    assert response.status_code == 401

    import asyncio

    async def _fetch():
        async with session_factory() as session:
            return (await session.execute(select(ExtractionRun))).scalars().all()

    runs = asyncio.get_event_loop().run_until_complete(_fetch())
    assert runs == []


def test_x_tenant_id_header_is_ignored_when_api_key_authenticates(
    _api_key_required, session_factory
):
    """API key wins. A spoofed X-Tenant-Id header must not influence persisted tenant."""
    client = _build_client(ExtractionEngine(), session_factory=session_factory)

    response = client.post(
        "/v1/extractions/run",
        headers={
            "X-API-Key": _api_key_required,
            "X-Tenant-Id": "spoofed-other-tenant",
        },
        json={
            "document_id": "doc_spoof",
            "document_text": "Cataract diagnosed.",
            "spec": _spec_payload(),
        },
    )
    assert response.status_code == 200

    import asyncio

    async def _fetch():
        async with session_factory() as session:
            return (await session.execute(select(ExtractionRun))).scalars().all()

    runs = asyncio.get_event_loop().run_until_complete(_fetch())
    assert len(runs) == 1
    import hashlib

    expected_hash = hashlib.sha256(_api_key_required.encode()).hexdigest()[:12]
    assert runs[0].tenant_id == expected_hash
    assert runs[0].tenant_id != "spoofed-other-tenant"


def test_local_mode_without_api_keys_persists_null_tenant(session_factory):
    """When the deployment has no api_keys configured (local/test mode), the
    request is anonymous and tenant_id stays NULL on the persisted run."""
    client = _build_client(ExtractionEngine(), session_factory=session_factory)

    response = client.post(
        "/v1/extractions/run",
        json={
            "document_id": "doc_local",
            "document_text": "Cataract diagnosed.",
            "spec": _spec_payload(),
        },
    )
    assert response.status_code == 200

    import asyncio

    async def _fetch():
        async with session_factory() as session:
            return (await session.execute(select(ExtractionRun))).scalars().all()

    runs = asyncio.get_event_loop().run_until_complete(_fetch())
    assert len(runs) == 1
    assert runs[0].tenant_id is None
