from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base, get_db_session
from app.core.settings import get_settings
from app.core.settings import Settings
from app.api.routes_medical_classifier import router
from app.models import MedicalClassifierAuditLog
from app.services.medical_classifier import ConfigurableLLMJsonPromptRunner
from app.services.medical_classifier import ProcedureClassificationService
from app.services.medical_classifier import build_generic_fallback_prompt_json


def _write_definition(path: Path, treatment_code: str) -> None:
    payload = {
        "treatment_code": treatment_code,
        "procedure_name": "Procedure Example",
        "categories": [
            {
                "key": "IDX_PROCEDURE_PERFORMED",
                "title": "Performed",
                "description": "Was the procedure actually performed in the current encounter.",
                "scope": "full",
                "negative_signals": ["התקבל לצורך ניתוח"],
                "examples_negative": ["התקבל לצורך ניתוח"],
            }
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class RecordingRunner:
    def __init__(self, result_code: str = "1") -> None:
        self.result_code = result_code
        self.calls: list[dict[str, str]] = []

    def run_idx(self, *, text: str, prompt: str, key: str, system_message: str) -> dict[str, str]:
        self.calls.append(
            {
                "text": text,
                "prompt": prompt,
                "key": key,
                "system_message": system_message,
            }
        )
        return {"result_code": self.result_code}


def _build_test_client(service: ProcedureClassificationService) -> TestClient:
    app = FastAPI()
    app.state.medical_classifier_service = service
    app.include_router(router)
    return TestClient(app)


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


def _build_test_client_with_db(
    service: ProcedureClassificationService,
    session_factory: async_sessionmaker[AsyncSession],
) -> TestClient:
    app = FastAPI()
    app.state.medical_classifier_service = service
    app.include_router(router)

    async def _override_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = _override_session
    return TestClient(app)


def _audit_rows(session_factory: async_sessionmaker[AsyncSession]) -> list[MedicalClassifierAuditLog]:
    async def _load():
        async with session_factory() as session:
            rows = (
                await session.execute(
                    select(MedicalClassifierAuditLog).order_by(MedicalClassifierAuditLog.created_at)
                )
            ).scalars().all()
            return rows

    return asyncio.get_event_loop().run_until_complete(_load())


def test_internal_medical_classifier_route_happy_path(tmp_path: Path) -> None:
    definitions_dir = tmp_path / "definitions"
    definitions_dir.mkdir()
    _write_definition(definitions_dir / "arthroscopy_knee.json", "arthroscopy_knee")
    runner = RecordingRunner(result_code="1")
    service = ProcedureClassificationService(llm_runner=runner, definitions_path=definitions_dir)
    client = _build_test_client(service)

    response = client.post(
        "/internal/medical-classifier/classify",
        json={
            "procedure_code": "arthroscopy_knee",
            "document_text": "בוצע ניתוח ארתרוסקופיה במהלך האשפוז",
            "document_id": "doc-1",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "document_id": "doc-1",
        "procedure_code": "arthroscopy_knee",
        "result_code": 1,
        "masked": True,
        "model_output": {
            "prompt_source": "definition",
            "used_definition": True,
            "idx_results": {"IDX_PROCEDURE_PERFORMED": 1},
            "raw": {"IDX_PROCEDURE_PERFORMED": {"result_code": "1"}},
        },
        "error": None,
    }


def test_internal_medical_classifier_route_falls_back_without_definition(tmp_path: Path) -> None:
    runner = RecordingRunner(result_code="0")

    def fallback_prompt_provider(procedure_code: str) -> dict[str, object]:
        return {
            "system_message": f"Fallback for {procedure_code}",
            "to_summarize": False,
            "IDX_FALLBACK": ["Return 0 for this fake test", "full"],
        }

    service = ProcedureClassificationService(
        llm_runner=runner,
        definitions_path=tmp_path / "missing",
        prompt_provider=fallback_prompt_provider,
    )
    client = _build_test_client(service)

    response = client.post(
        "/internal/medical-classifier/classify",
        json={
            "procedure_code": "missing_code",
            "document_text": "admitted for procedure only",
        },
    )

    assert response.status_code == 200
    assert response.json()["model_output"]["prompt_source"] == "fallback"
    assert response.json()["model_output"]["used_definition"] is False
    assert response.json()["result_code"] == 0


def test_internal_medical_classifier_route_masks_pii(tmp_path: Path) -> None:
    definitions_dir = tmp_path / "definitions"
    definitions_dir.mkdir()
    _write_definition(definitions_dir / "arthroscopy_knee.json", "arthroscopy_knee")
    runner = RecordingRunner(result_code="1")
    service = ProcedureClassificationService(llm_runner=runner, definitions_path=definitions_dir)
    client = _build_test_client(service)

    response = client.post(
        "/internal/medical-classifier/classify",
        json={
            "procedure_code": "arthroscopy_knee",
            "document_text": "patient id 123456789 underwent procedure",
        },
    )

    assert response.status_code == 200
    assert response.json()["masked"] is True
    assert runner.calls[0]["text"] == "patient id [ID_REMOVED] underwent procedure"


def test_internal_medical_classifier_route_invalid_input_returns_422(tmp_path: Path) -> None:
    service = ProcedureClassificationService(
        llm_runner=RecordingRunner(),
        definitions_path=tmp_path / "missing",
    )
    client = _build_test_client(service)

    response = client.post(
        "/internal/medical-classifier/classify",
        json={
            "procedure_code": "   ",
            "document_text": "   ",
        },
    )

    assert response.status_code == 422


def test_internal_medical_classifier_route_returns_structured_error_when_llm_not_configured(
    tmp_path: Path,
) -> None:
    definitions_dir = tmp_path / "definitions"
    definitions_dir.mkdir()
    _write_definition(definitions_dir / "arthroscopy_knee.json", "arthroscopy_knee")
    settings = Settings(
        medical_classifier_procedure_definitions_path=str(definitions_dir),
        medical_classifier_llm_provider="disabled",
        medical_classifier_llm_model="",
        medical_classifier_llm_api_key="",
    )
    service = ProcedureClassificationService.from_settings(
        llm_runner=ConfigurableLLMJsonPromptRunner.from_settings(settings),
        settings=settings,
        prompt_provider=build_generic_fallback_prompt_json,
    )
    client = _build_test_client(service)

    response = client.post(
        "/internal/medical-classifier/classify",
        json={
            "procedure_code": "arthroscopy_knee",
            "document_text": "בוצע ניתוח ארתרוסקופיה במהלך האשפוז",
        },
    )

    assert response.status_code == 200
    assert response.json()["result_code"] == 0
    assert response.json()["error"] == {
        "code": "llm_not_configured",
        "message": "Medical classifier LLM provider is not configured.",
    }


def test_internal_medical_classifier_route_normalizes_invalid_model_output_to_error(tmp_path: Path) -> None:
    definitions_dir = tmp_path / "definitions"
    definitions_dir.mkdir()
    _write_definition(definitions_dir / "arthroscopy_knee.json", "arthroscopy_knee")

    def invalid_output_sender(
        url: str,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_seconds: float,
    ) -> dict[str, object]:
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"result_code": "maybe"}',
                    }
                }
            ]
        }

    settings = Settings(
        medical_classifier_procedure_definitions_path=str(definitions_dir),
        medical_classifier_llm_provider="openai",
        medical_classifier_llm_model="gpt-4o-mini",
        medical_classifier_llm_api_key="test-key",
    )
    runner = ConfigurableLLMJsonPromptRunner.from_settings(settings, request_sender=invalid_output_sender)
    service = ProcedureClassificationService.from_settings(
        llm_runner=runner,
        settings=settings,
        prompt_provider=build_generic_fallback_prompt_json,
    )
    client = _build_test_client(service)

    response = client.post(
        "/internal/medical-classifier/classify",
        json={
            "procedure_code": "arthroscopy_knee",
            "document_text": "בוצע ניתוח ארתרוסקופיה במהלך האשפוז",
        },
    )

    assert response.status_code == 200
    assert response.json()["result_code"] == 0
    assert response.json()["error"] == {
        "code": "invalid_model_output",
        "message": "Medical classifier model returned an invalid result_code for IDX_PROCEDURE_PERFORMED.",
    }


def test_public_medical_classifier_document_route_happy_path(
    tmp_path: Path,
    session_factory,
) -> None:
    definitions_dir = tmp_path / "definitions"
    definitions_dir.mkdir()
    _write_definition(definitions_dir / "arthroscopy_knee.json", "arthroscopy_knee")
    runner = RecordingRunner(result_code="1")
    service = ProcedureClassificationService(llm_runner=runner, definitions_path=definitions_dir)
    client = _build_test_client_with_db(service, session_factory)

    response = client.post(
        "/v1/medical-classifier/classify-document",
        json={
            "file_name": "doc-1.pdf",
            "doc_type": 3,
            "treatment_code": "arthroscopy_knee",
            "subject_ind": 2,
            "cleaned_desc": "short text",
            "cleaned_full": "בוצע ניתוח ארתרוסקופיה במהלך האשפוז",
            "metadata": {"source_system": "connector"},
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "result_code": 1,
        "indexes": {"IDX_PROCEDURE_PERFORMED": 1},
        "message": None,
        "error_code": None,
        "retryable": False,
        "model_version": None,
        "request_id": response.json()["request_id"],
    }
    assert response.json()["request_id"]


def test_public_medical_classifier_document_route_maps_cleaned_full_to_service(
    tmp_path: Path,
    session_factory,
) -> None:
    definitions_dir = tmp_path / "definitions"
    definitions_dir.mkdir()
    _write_definition(definitions_dir / "arthroscopy_knee.json", "arthroscopy_knee")
    runner = RecordingRunner(result_code="1")
    service = ProcedureClassificationService(llm_runner=runner, definitions_path=definitions_dir)
    client = _build_test_client_with_db(service, session_factory)

    response = client.post(
        "/v1/medical-classifier/classify-document",
        json={
            "file_name": "doc-1.pdf",
            "doc_type": 3,
            "treatment_code": "arthroscopy_knee",
            "subject_ind": 2,
            "cleaned_desc": "desc should not be used for full scope",
            "cleaned_full": "full scope text",
            "metadata": {},
        },
    )

    assert response.status_code == 200
    assert runner.calls[0]["text"] == "full scope text"


def test_public_medical_classifier_document_route_falls_back_to_cleaned_desc(
    tmp_path: Path,
    session_factory,
) -> None:
    runner = RecordingRunner(result_code="1")

    def fallback_prompt_provider(procedure_code: str) -> dict[str, object]:
        return {
            "system_message": f"Fallback for {procedure_code}",
            "to_summarize": False,
            "IDX_FALLBACK": ["Return 1 for this fake test", "full"],
        }

    service = ProcedureClassificationService(
        llm_runner=runner,
        definitions_path=tmp_path / "missing",
        prompt_provider=fallback_prompt_provider,
    )
    client = _build_test_client_with_db(service, session_factory)

    response = client.post(
        "/v1/medical-classifier/classify-document",
        json={
            "file_name": "doc-1.pdf",
            "doc_type": 3,
            "treatment_code": "missing_code",
            "subject_ind": 2,
            "cleaned_desc": "desc fallback text",
            "metadata": {},
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert runner.calls[0]["text"] == "desc fallback text"


def test_public_medical_classifier_document_route_requires_document_text(
    tmp_path: Path,
    session_factory,
) -> None:
    service = ProcedureClassificationService(
        llm_runner=RecordingRunner(),
        definitions_path=tmp_path / "missing",
    )
    client = _build_test_client_with_db(service, session_factory)

    response = client.post(
        "/v1/medical-classifier/classify-document",
        json={
            "file_name": "doc-1.pdf",
            "doc_type": 3,
            "treatment_code": "missing_code",
            "subject_ind": 2,
            "metadata": {},
        },
    )

    assert response.status_code == 422


def test_public_medical_classifier_document_route_does_not_log_document_text(
    tmp_path: Path,
    session_factory,
    caplog,
) -> None:
    definitions_dir = tmp_path / "definitions"
    definitions_dir.mkdir()
    _write_definition(definitions_dir / "arthroscopy_knee.json", "arthroscopy_knee")
    service = ProcedureClassificationService(
        llm_runner=RecordingRunner(result_code="1"),
        definitions_path=definitions_dir,
    )
    client = _build_test_client_with_db(service, session_factory)
    sensitive_text = "sensitive patient text 123456789"

    response = client.post(
        "/v1/medical-classifier/classify-document",
        json={
            "file_name": "doc-1.pdf",
            "doc_type": 3,
            "treatment_code": "arthroscopy_knee",
            "cleaned_full": sensitive_text,
        },
    )

    assert response.status_code == 200
    assert sensitive_text not in caplog.text


def test_public_medical_classifier_document_route_uses_public_api_key_auth(
    tmp_path: Path,
    session_factory,
    monkeypatch,
) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("API_KEYS", '["dev-key"]')
    service = ProcedureClassificationService(
        llm_runner=RecordingRunner(),
        definitions_path=tmp_path / "missing",
    )
    client = _build_test_client_with_db(service, session_factory)

    response = client.post(
        "/v1/medical-classifier/classify-document",
        json={
            "file_name": "doc-1.pdf",
            "doc_type": 3,
            "treatment_code": "missing_code",
            "cleaned_full": "safe smoke text",
        },
    )

    assert response.status_code == 401
    get_settings.cache_clear()


def test_public_medical_classifier_document_route_creates_audit_row_on_success(
    tmp_path: Path,
    session_factory,
) -> None:
    definitions_dir = tmp_path / "definitions"
    definitions_dir.mkdir()
    _write_definition(definitions_dir / "arthroscopy_knee.json", "arthroscopy_knee")
    service = ProcedureClassificationService(
        llm_runner=RecordingRunner(result_code="1"),
        definitions_path=definitions_dir,
    )
    client = _build_test_client_with_db(service, session_factory)
    cleaned_full = "בוצע ניתוח ארתרוסקופיה במהלך האשפוז"
    cleaned_desc = "short text"

    response = client.post(
        "/v1/medical-classifier/classify-document",
        json={
            "file_name": "doc-1.pdf",
            "doc_type": 3,
            "treatment_code": "arthroscopy_knee",
            "subject_ind": 2,
            "cleaned_desc": cleaned_desc,
            "cleaned_full": cleaned_full,
            "metadata": {"source_system": "connector", "batch_id": "batch-001"},
        },
    )

    assert response.status_code == 200
    audit = _audit_rows(session_factory)
    assert len(audit) == 1
    row = audit[0]
    assert row.request_id == response.json()["request_id"]
    assert row.file_name == "doc-1.pdf"
    assert row.doc_type == 3
    assert row.treatment_code == "arthroscopy_knee"
    assert row.subject_ind == "2"
    assert row.status == "success"
    assert row.result_code == 1
    assert row.indexes_json == {"IDX_PROCEDURE_PERFORMED": 1}
    assert row.error_code is None
    assert row.retryable is False
    assert row.duration_ms >= 0
    assert row.text_length == len(cleaned_full)
    assert row.document_text_hash == hashlib.sha256(cleaned_full.encode("utf-8")).hexdigest()
    assert row.cleaned_desc_hash == hashlib.sha256(cleaned_desc.encode("utf-8")).hexdigest()
    assert row.cleaned_full_hash == hashlib.sha256(cleaned_full.encode("utf-8")).hexdigest()
    assert row.metadata_json == {"source_system": "connector", "batch_id": "batch-001"}


def test_public_medical_classifier_document_route_creates_audit_row_on_service_error(
    tmp_path: Path,
    session_factory,
) -> None:
    settings = Settings(
        medical_classifier_procedure_definitions_path=str(tmp_path / "missing"),
        medical_classifier_llm_provider="disabled",
        medical_classifier_llm_model="",
        medical_classifier_llm_api_key="",
    )
    service = ProcedureClassificationService.from_settings(
        llm_runner=ConfigurableLLMJsonPromptRunner.from_settings(settings),
        settings=settings,
        prompt_provider=build_generic_fallback_prompt_json,
    )
    client = _build_test_client_with_db(service, session_factory)

    response = client.post(
        "/v1/medical-classifier/classify-document",
        json={
            "file_name": "doc-error.pdf",
            "doc_type": 3,
            "treatment_code": "arthroscopy_knee",
            "cleaned_full": "safe text for error path",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "error"
    audit = _audit_rows(session_factory)
    assert len(audit) == 1
    assert audit[0].request_id == response.json()["request_id"]
    assert audit[0].status == "error"
    assert audit[0].error_code == "llm_not_configured"
    assert audit[0].result_code == 0


def test_public_medical_classifier_audit_does_not_store_full_text(
    tmp_path: Path,
    session_factory,
) -> None:
    definitions_dir = tmp_path / "definitions"
    definitions_dir.mkdir()
    _write_definition(definitions_dir / "arthroscopy_knee.json", "arthroscopy_knee")
    service = ProcedureClassificationService(
        llm_runner=RecordingRunner(result_code="1"),
        definitions_path=definitions_dir,
    )
    client = _build_test_client_with_db(service, session_factory)
    sensitive_full = "very sensitive medical text"
    sensitive_desc = "very sensitive desc"

    response = client.post(
        "/v1/medical-classifier/classify-document",
        json={
            "file_name": "doc-sensitive.pdf",
            "treatment_code": "arthroscopy_knee",
            "cleaned_desc": sensitive_desc,
            "cleaned_full": sensitive_full,
        },
    )

    assert response.status_code == 200
    row = _audit_rows(session_factory)[0]
    values = vars(row)
    assert sensitive_full not in str(values)
    assert sensitive_desc not in str(values)


def test_public_medical_classifier_audit_hashes_are_deterministic(
    tmp_path: Path,
    session_factory,
) -> None:
    definitions_dir = tmp_path / "definitions"
    definitions_dir.mkdir()
    _write_definition(definitions_dir / "arthroscopy_knee.json", "arthroscopy_knee")
    service = ProcedureClassificationService(
        llm_runner=RecordingRunner(result_code="1"),
        definitions_path=definitions_dir,
    )
    client = _build_test_client_with_db(service, session_factory)
    payload = {
        "file_name": "doc-hash.pdf",
        "treatment_code": "arthroscopy_knee",
        "cleaned_desc": "same desc",
        "cleaned_full": "same full",
    }

    assert client.post("/v1/medical-classifier/classify-document", json=payload).status_code == 200
    assert client.post("/v1/medical-classifier/classify-document", json=payload).status_code == 200

    rows = _audit_rows(session_factory)
    assert len(rows) == 2
    assert rows[0].document_text_hash == rows[1].document_text_hash
    assert rows[0].cleaned_desc_hash == rows[1].cleaned_desc_hash
    assert rows[0].cleaned_full_hash == rows[1].cleaned_full_hash
