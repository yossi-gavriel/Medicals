from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes_classification import router as classifications_router
from app.core import database as database_module
from app.core.database import Base, get_db_session
from app.core.errors import register_error_handlers
from app.core.queue import InMemoryJobEnqueuer
from app.core.settings import Settings
from app.core.storage import LocalDocumentStorage
from app.repositories.classification_repository import ClassificationRunRepository
from app.services.classification_pipeline import (
    ClassificationExecutor,
    ClassificationPipeline,
)
from app.services.medical_classifier import (
    ProcedureClassificationService,
    build_generic_fallback_prompt_json,
)


class _StubRunner:
    def run_idx(self, *, text: str, prompt: str, key: str, system_message: str):
        return {"result_code": "1"}


@pytest_asyncio.fixture
async def app_and_session(tmp_path, monkeypatch):
    db_url = f"sqlite+aiosqlite:///{tmp_path/'test.db'}"
    try:
        engine = create_async_engine(db_url, future=True)
    except ModuleNotFoundError:
        pytest.skip("aiosqlite is required for async SQLite tests")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    settings = Settings(
        api_keys=["test-key"],
        internal_api_keys=["test-key"],
        document_storage_backend="local",
        document_storage_local_path=str(tmp_path / "docs"),
        medical_classifier_llm_provider="disabled",
        classification_batch_max_items=10,
    )
    monkeypatch.setattr(database_module, "SessionLocal", factory)

    storage = LocalDocumentStorage(settings.document_storage_local_path)
    enqueuer = InMemoryJobEnqueuer()
    classifier = ProcedureClassificationService(
        llm_runner=_StubRunner(),
        prompt_provider=build_generic_fallback_prompt_json,
    )
    pipeline = ClassificationPipeline(settings=settings, storage=storage, enqueuer=enqueuer)
    executor = ClassificationExecutor(settings=settings, storage=storage, classifier=classifier)

    app = FastAPI()
    register_error_handlers(app)
    app.include_router(classifications_router)
    app.state.classification_pipeline = pipeline

    async def _override_get_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = _override_get_db

    monkeypatch.setattr("app.core.security.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.routes_classification.get_settings", lambda: settings)

    yield app, factory, executor

    await engine.dispose()


@pytest.mark.asyncio
async def test_submit_batch_returns_per_item_acks_and_shared_batch_id(app_and_session):
    app, factory, _executor = app_and_session
    payload = {
        "items": [
            {"procedure_code": "PROC_X", "document_text": "doc one"},
            {"procedure_code": "PROC_X", "document_text": "doc two"},
            {"procedure_code": "PROC_Y", "document_text": "doc three"},
        ]
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/classifications/batch",
            headers={"X-API-Key": "test-key", "X-Tenant-Id": "tenant-a"},
            json=payload,
        )

    assert response.status_code == 202
    body = response.json()
    assert body["submitted"] == 3
    assert body["deduplicated"] == 0
    assert len(body["items"]) == 3
    batch_id = uuid.UUID(body["batch_id"])
    assert body["poll_url"].endswith(str(batch_id))

    # All runs should share the batch_id and tenant.
    async with factory() as session:
        repo = ClassificationRunRepository(session)
        runs = await repo.list_by_batch_id(batch_id, tenant_id="tenant-a")
    assert len(runs) == 3
    for run in runs:
        assert run.batch_id == batch_id
        assert run.tenant_id == "tenant-a"


@pytest.mark.asyncio
async def test_submit_batch_marks_deduplicated_repeats(app_and_session):
    app, _factory, _executor = app_and_session
    payload = {
        "items": [
            {"procedure_code": "PROC_X", "document_text": "same body"},
            {"procedure_code": "PROC_X", "document_text": "same body"},
        ]
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/classifications/batch",
            headers={"X-API-Key": "test-key"},
            json=payload,
        )
    assert response.status_code == 202
    body = response.json()
    assert body["submitted"] == 2
    assert body["deduplicated"] == 1
    assert sum(1 for item in body["items"] if item["deduplicated"]) == 1


@pytest.mark.asyncio
async def test_submit_batch_rejects_oversized_payload(app_and_session):
    app, _factory, _executor = app_and_session
    items = [{"procedure_code": "PROC_X", "document_text": f"doc-{i}"} for i in range(11)]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/classifications/batch",
            headers={"X-API-Key": "test-key"},
            json={"items": items},
        )
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_submit_batch_rejects_duplicate_document_id(app_and_session):
    app, _factory, _executor = app_and_session
    payload = {
        "items": [
            {"procedure_code": "PROC_X", "document_text": "doc1", "document_id": "dup"},
            {"procedure_code": "PROC_X", "document_text": "doc2", "document_id": "dup"},
        ]
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/classifications/batch",
            headers={"X-API-Key": "test-key"},
            json=payload,
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_batch_status_aggregates_counts_after_executor_runs(app_and_session):
    app, factory, executor = app_and_session
    payload = {
        "items": [
            {"procedure_code": "PROC_X", "document_text": "alpha"},
            {"procedure_code": "PROC_X", "document_text": "beta"},
        ]
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        submit = await client.post(
            "/v1/classifications/batch",
            headers={"X-API-Key": "test-key"},
            json=payload,
        )
        assert submit.status_code == 202
        batch_id = uuid.UUID(submit.json()["batch_id"])

        async with factory() as session:
            repo = ClassificationRunRepository(session)
            runs = await repo.list_by_batch_id(batch_id)
        async with factory() as session:
            await executor.execute(session, runs[0].id)

        status = await client.get(
            f"/v1/classifications/batch/{batch_id}",
            headers={"X-API-Key": "test-key"},
        )
    assert status.status_code == 200
    body = status.json()
    assert body["counts"]["total"] == 2
    assert body["counts"]["done"] == 1
    assert body["counts"]["pending"] == 1
    assert len(body["items"]) == 2


@pytest.mark.asyncio
async def test_get_unknown_batch_returns_404(app_and_session):
    app, _factory, _executor = app_and_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/v1/classifications/batch/{uuid.uuid4()}",
            headers={"X-API-Key": "test-key"},
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_batch_isolated_per_tenant(app_and_session):
    app, factory, _executor = app_and_session
    payload = {"items": [{"procedure_code": "PROC_X", "document_text": "abc"}]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        submit = await client.post(
            "/v1/classifications/batch",
            headers={"X-API-Key": "test-key", "X-Tenant-Id": "tenant-a"},
            json=payload,
        )
        batch_id = uuid.UUID(submit.json()["batch_id"])

        # Different tenant cannot see this batch.
        cross_tenant = await client.get(
            f"/v1/classifications/batch/{batch_id}",
            headers={"X-API-Key": "test-key", "X-Tenant-Id": "tenant-b"},
        )
    assert cross_tenant.status_code == 404
