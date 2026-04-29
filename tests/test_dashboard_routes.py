from __future__ import annotations

import hashlib
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.routes_dashboard import router as dashboard_router
from app.api.routes_extractions import router as extractions_router
from app.core.database import Base, get_db_session
from app.core.settings import get_settings
from app.services.extraction_engine import ExtractionEngine


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    db_url = f"sqlite+aiosqlite:///{tmp_path/'test.db'}"
    engine = create_async_engine(db_url, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture
def api_keys(monkeypatch):
    from app.core import security as security_module
    from app.core import settings as settings_module

    test_settings = settings_module.Settings(
        api_keys=["tenant-a-key", "tenant-b-key"],
        internal_api_keys=["admin-key"],
    )
    monkeypatch.setattr(security_module, "get_settings", lambda: test_settings)
    monkeypatch.setattr(settings_module, "get_settings", lambda: test_settings)
    get_settings.cache_clear()
    yield test_settings
    get_settings.cache_clear()


def _build_client(session_factory: async_sessionmaker[AsyncSession]) -> TestClient:
    app = FastAPI()
    app.state.extraction_engine = ExtractionEngine()
    app.include_router(extractions_router)
    app.include_router(dashboard_router)

    async def _override_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = _override_session
    return TestClient(app)


def _spec() -> dict:
    return {
        "version": "1.0",
        "treatments": [
            {
                "treatment_code": "SURGERY_12345",
                "display_name": "Example Surgery",
                "rules": [
                    {
                        "field_name": "procedure_performed",
                        "type": "boolean",
                        "positive_indicators": ["performed"],
                    },
                    {
                        "field_name": "hospitalization_hours",
                        "type": "number",
                        "positive_indicators": ["hospitalization duration"],
                    },
                ],
                "compliance_rules": [
                    {
                        "rule_id": "procedure_required",
                        "description": "Procedure must be performed",
                        "field": "procedure_performed",
                        "operator": "equals",
                        "value": True,
                        "severity": "high",
                        "on_fail": {
                            "status": "non_compliant",
                            "reason": "Procedure was not performed",
                            "recommended_action": "reject_case",
                        },
                    },
                    {
                        "rule_id": "minimum_24_hours",
                        "description": "Hospitalization must be at least 24 hours",
                        "field": "hospitalization_hours",
                        "operator": "gte",
                        "value": 24,
                        "severity": "medium",
                        "on_fail": {
                            "status": "non_compliant",
                            "reason": "Hospitalization duration is below threshold",
                            "recommended_action": "request_reimbursement",
                        },
                    },
                ],
            }
        ],
    }


def _seed(client: TestClient) -> None:
    response_a = _create_extraction(client, api_key="tenant-a-key", document_id="doc_a", hours=6)
    response_b = _create_extraction(client, api_key="tenant-b-key", document_id="doc_b", hours=30)
    assert response_a.status_code == 200
    assert response_b.status_code == 200


def _create_extraction(
    client: TestClient,
    *,
    api_key: str,
    document_id: str,
    hours: int,
    billed_amount: int = 1000,
):
    return client.post(
        "/v1/extractions/run",
        headers={"X-API-Key": api_key, "X-Tenant-Id": "spoofed"},
        json={
            "document_id": document_id,
            "document_text": f"Procedure performed. hospitalization duration {hours} hours.",
            "metadata": {
                "patient_id": f"patient-{document_id}",
                "billed_amount": billed_amount,
                "currency": "ILS",
            },
            "spec": _spec(),
        },
    )


def _case_id_for(client: TestClient, api_key: str) -> str:
    response = client.get("/v1/dashboard/reimbursement-cases", headers={"X-API-Key": api_key})
    assert response.status_code == 200
    items = response.json()["items"]
    assert items
    for item in items:
        if item["status"] == "draft":
            return item["id"]
    return items[0]["id"]


def _patch_case(client: TestClient, case_id: str, payload: dict, api_key: str = "tenant-a-key"):
    return client.patch(
        f"/v1/dashboard/reimbursement-cases/{case_id}",
        headers={"X-API-Key": api_key, "X-Tenant-Id": "spoofed"},
        json=payload,
    )


def _admin_patch_case(client: TestClient, case_id: str, payload: dict):
    return client.patch(
        f"/v1/admin/dashboard/reimbursement-cases/{case_id}",
        headers={"X-API-Key": "admin-key"},
        json=payload,
    )


def test_customer_dashboard_filters_to_resolved_tenant_and_ignores_spoofed_tenant(
    api_keys,
    session_factory,
) -> None:
    client = _build_client(session_factory)
    _seed(client)

    response = client.get(
        "/v1/dashboard/summary?tenant_id=not-tenant-a",
        headers={"X-API-Key": "tenant-a-key", "X-Tenant-Id": "not-tenant-a"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_documents"] == 1
    assert body["non_compliant_count"] == 1
    assert body["compliant_count"] == 0
    assert body["reimbursement_cases_draft"] == 1
    assert body["estimated_reimbursement_amount_total"] == 1000.0


def test_admin_dashboard_can_see_all_tenants_and_filter_by_tenant(api_keys, session_factory) -> None:
    client = _build_client(session_factory)
    _seed(client)

    all_response = client.get("/v1/admin/dashboard/summary", headers={"X-API-Key": "admin-key"})
    tenant_a = hashlib.sha256(b"tenant-a-key").hexdigest()[:12]
    filtered_response = client.get(
        f"/v1/admin/dashboard/summary?tenant_id={tenant_a}",
        headers={"X-API-Key": "admin-key"},
    )

    assert all_response.status_code == 200
    assert filtered_response.status_code == 200
    assert all_response.json()["total_documents"] == 2
    assert all_response.json()["non_compliant_count"] == 1
    assert filtered_response.json()["total_documents"] == 1
    assert filtered_response.json()["non_compliant_count"] == 1


def test_dashboard_treatments_rules_timeseries_filters_and_pagination(api_keys, session_factory) -> None:
    client = _build_client(session_factory)
    _seed(client)

    treatments = client.get(
        "/v1/admin/dashboard/treatments?treatment_code=SURGERY_12345",
        headers={"X-API-Key": "admin-key"},
    )
    rules = client.get("/v1/dashboard/rules", headers={"X-API-Key": "tenant-a-key"})
    timeseries = client.get(
        "/v1/dashboard/documents/timeseries",
        headers={"X-API-Key": "tenant-a-key"},
    )
    cases = client.get(
        "/v1/dashboard/reimbursement-cases?limit=1&offset=0",
        headers={"X-API-Key": "tenant-a-key"},
    )

    assert treatments.status_code == 200
    assert treatments.json()[0]["documents"] == 2
    assert treatments.json()[0]["non_compliance_rate"] == 50.0
    assert rules.status_code == 200
    assert rules.json()["failed_rules_by_rule_id"][0] == {
        "rule_id": "minimum_24_hours",
        "failed_count": 1,
    }
    assert timeseries.status_code == 200
    assert timeseries.json()[0]["documents"] == 1
    assert cases.status_code == 200
    assert cases.json()["total"] == 1
    assert cases.json()["limit"] == 1
    assert cases.json()["items"][0]["status"] == "draft"


def test_reimbursement_case_allowed_status_transitions(api_keys, session_factory) -> None:
    client = _build_client(session_factory)
    _create_extraction(client, api_key="tenant-a-key", document_id="allowed_a", hours=6)
    case_id = _case_id_for(client, "tenant-a-key")

    for status in ["ready", "sent", "accepted", "closed"]:
        response = _patch_case(client, case_id, {"status": status})
        assert response.status_code == 200
        assert response.json()["status"] == status

    _create_extraction(client, api_key="tenant-a-key", document_id="allowed_b", hours=6)
    case_id = _case_id_for(client, "tenant-a-key")
    for status in ["ready", "sent", "rejected", "closed"]:
        response = _patch_case(client, case_id, {"status": status})
        assert response.status_code == 200
        assert response.json()["status"] == status


def test_reimbursement_case_invalid_status_transitions_return_400(api_keys, session_factory) -> None:
    client = _build_client(session_factory)
    _create_extraction(client, api_key="tenant-a-key", document_id="invalid_a", hours=6)
    case_id = _case_id_for(client, "tenant-a-key")

    draft_to_accepted = _patch_case(client, case_id, {"status": "accepted"})
    assert draft_to_accepted.status_code == 400
    assert "draft -> accepted" in draft_to_accepted.json()["detail"]

    for status in ["ready", "sent", "accepted", "closed"]:
        assert _patch_case(client, case_id, {"status": status}).status_code == 200

    closed_to_ready = _patch_case(client, case_id, {"status": "ready"})
    assert closed_to_ready.status_code == 400
    assert "closed -> ready" in closed_to_ready.json()["detail"]


def test_case_events_for_creation_status_note_and_amount(api_keys, session_factory) -> None:
    client = _build_client(session_factory)
    _create_extraction(client, api_key="tenant-a-key", document_id="events_a", hours=6)
    case_id = _case_id_for(client, "tenant-a-key")

    detail = client.get(
        f"/v1/dashboard/reimbursement-cases/{case_id}",
        headers={"X-API-Key": "tenant-a-key"},
    )
    assert detail.status_code == 200
    assert [event["event_type"] for event in detail.json()["events"]] == ["case_created"]

    status_change = _patch_case(
        client,
        case_id,
        {"status": "ready", "note": "Reviewed and ready to send"},
    )
    assert status_change.status_code == 200
    status_events = status_change.json()["events"]
    assert status_events[-1]["event_type"] == "status_changed"
    assert status_events[-1]["note"] == "Reviewed and ready to send"

    note_only = _patch_case(client, case_id, {"note": "Additional payer note"})
    assert note_only.status_code == 200
    assert note_only.json()["events"][-1]["event_type"] == "note_added"

    amount_update = _patch_case(
        client,
        case_id,
        {"estimated_amount": 1500, "currency": "usd"},
    )
    assert amount_update.status_code == 200
    event = amount_update.json()["events"][-1]
    assert event["event_type"] == "amount_updated"
    assert event["metadata"]["previous_estimated_amount"] == 1000.0
    assert event["metadata"]["new_estimated_amount"] == 1500.0
    assert amount_update.json()["currency"] == "USD"


def test_customer_update_security_and_admin_override(api_keys, session_factory) -> None:
    client = _build_client(session_factory)
    _create_extraction(client, api_key="tenant-a-key", document_id="secure_a", hours=6)
    _create_extraction(client, api_key="tenant-b-key", document_id="secure_b", hours=6, billed_amount=2000)
    tenant_a_case = _case_id_for(client, "tenant-a-key")
    tenant_b_case = _case_id_for(client, "tenant-b-key")

    own_update = _patch_case(client, tenant_a_case, {"status": "ready"}, api_key="tenant-a-key")
    assert own_update.status_code == 200
    assert own_update.json()["status"] == "ready"

    cross_tenant = _patch_case(client, tenant_b_case, {"status": "ready"}, api_key="tenant-a-key")
    assert cross_tenant.status_code == 404

    spoofed_header = client.patch(
        f"/v1/dashboard/reimbursement-cases/{tenant_b_case}",
        headers={"X-API-Key": "tenant-a-key", "X-Tenant-Id": "tenant-b"},
        json={"status": "ready"},
    )
    assert spoofed_header.status_code == 404

    admin_update = _admin_patch_case(client, tenant_b_case, {"status": "ready"})
    assert admin_update.status_code == 200
    assert admin_update.json()["status"] == "ready"


def test_admin_detail_missing_case_and_dashboard_counts_after_transition(
    api_keys,
    session_factory,
) -> None:
    client = _build_client(session_factory)
    _create_extraction(client, api_key="tenant-a-key", document_id="counts_a", hours=6)
    case_id = _case_id_for(client, "tenant-a-key")

    assert _patch_case(client, case_id, {"status": "ready"}).status_code == 200
    assert _patch_case(client, case_id, {"status": "sent"}).status_code == 200

    summary = client.get("/v1/dashboard/summary", headers={"X-API-Key": "tenant-a-key"})
    assert summary.status_code == 200
    assert summary.json()["reimbursement_cases_draft"] == 0
    assert summary.json()["reimbursement_cases_sent"] == 1

    detail = client.get(
        f"/v1/admin/dashboard/reimbursement-cases/{case_id}",
        headers={"X-API-Key": "admin-key"},
    )
    assert detail.status_code == 200
    event_types = [event["event_type"] for event in detail.json()["events"]]
    assert event_types == ["case_created", "status_changed", "status_changed"]
    assert detail.json()["compliance_summary"]["status"] == "non_compliant"

    missing = client.get(
        "/v1/admin/dashboard/reimbursement-cases/00000000-0000-0000-0000-000000000000",
        headers={"X-API-Key": "admin-key"},
    )
    assert missing.status_code == 404
