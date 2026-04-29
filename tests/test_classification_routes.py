from __future__ import annotations

import asyncio
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

    yield app, factory, executor

    await engine.dispose()


@pytest.mark.asyncio
async def test_submit_classification_returns_202_and_creates_pending_run(app_and_session):
    app, factory, _executor = app_and_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/classifications",
            headers={"X-API-Key": "test-key", "X-Tenant-Id": "tenant-a"},
            json={
                "procedure_code": "PROC_X",
                "document_text": "בוצעה פעולה",
                "document_id": "ext-1",
                "source_system": "EHR",
            },
        )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert body["deduplicated"] is False
    job_id = uuid.UUID(body["job_id"])

    async with factory() as session:
        repo = ClassificationRunRepository(session)
        run = await repo.get_by_job_id(job_id)
        assert run is not None
        assert run.tenant_id == "tenant-a"
        assert run.procedure_code == "proc_x"


@pytest.mark.asyncio
async def test_get_job_returns_404_for_unknown_id(app_and_session):
    app, _factory, _ = app_and_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/v1/classifications/{uuid.uuid4()}",
            headers={"X-API-Key": "test-key"},
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_job_returns_done_after_executor_runs(app_and_session):
    app, factory, executor = app_and_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        submit = await client.post(
            "/v1/classifications",
            headers={"X-API-Key": "test-key"},
            json={"procedure_code": "PROC_X", "document_text": "content"},
        )
        assert submit.status_code == 202
        job_id = uuid.UUID(submit.json()["job_id"])

        async with factory() as session:
            repo = ClassificationRunRepository(session)
            run = await repo.get_by_job_id(job_id)
            assert run is not None
            run_id = run.id

        async with factory() as session:
            await executor.execute(session, run_id)

        view = await client.get(
            f"/v1/classifications/{job_id}",
            headers={"X-API-Key": "test-key"},
        )
    assert view.status_code == 200
    body = view.json()
    assert body["status"] == "done"
    assert body["result_code"] == 1
    assert body["idx_results"] == {"IDX_PROCEDURE_PERFORMED": 1}


@pytest.mark.asyncio
async def test_submit_requires_api_key(app_and_session):
    app, _factory, _ = app_and_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/classifications",
            json={"procedure_code": "PROC_X", "document_text": "content"},
        )
    assert response.status_code == 401
