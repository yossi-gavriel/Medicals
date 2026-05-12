from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.lambda_handlers import medical_classifier_handler as handler
from app.services.medical_classifier.cloud_store import _from_dynamodb_item

API_KEY_A = "tenant-a-key"
API_KEY_B = "tenant-b-key"


class FakeDynamoDB:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {}

    def put_item(self, *, TableName: str, Item: dict[str, Any]) -> None:  # noqa: N803
        table = self.tables.setdefault(TableName, [])
        item = _from_dynamodb_item(Item)
        key_names = ["api_key_hash_prefix"] if "api_key_hash_prefix" in item and "tenant_id" not in item else [
            "tenant_id",
            "sort_key",
        ]
        table[:] = [existing for existing in table if not all(existing.get(k) == item.get(k) for k in key_names)]
        table.append(item)

    def get_item(self, *, TableName: str, Key: dict[str, Any]) -> dict[str, Any]:  # noqa: N803
        key = _from_dynamodb_item(Key)
        for item in self.tables.get(TableName, []):
            if all(item.get(k) == v for k, v in key.items()):
                return {"Item": _to_ddb_item(item)}
        return {}

    def query(self, *, TableName: str, ExpressionAttributeValues: dict[str, Any], **kwargs: Any) -> dict[str, Any]:  # noqa: N803
        values = {key: _from_dynamodb_item({"v": value})["v"] for key, value in ExpressionAttributeValues.items()}
        items = self.tables.get(TableName, [])
        if ":gpk" in values:
            matched = [item for item in items if item.get("gsi1pk") == values[":gpk"]]
        else:
            matched = [
                item
                for item in items
                if item.get("tenant_id") == values[":tenant"]
                and str(item.get("sort_key", "")).startswith(values[":prefix"])
            ]
        if kwargs.get("ScanIndexForward") is False:
            matched = list(reversed(matched))
        return {"Items": [_to_ddb_item(item) for item in matched]}

    def update_item(self, **kwargs: Any) -> None:
        return None


class RecordingClassifierService:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    def classify_document(self, document: Any) -> Any:
        self.calls.append(document)
        return SimpleNamespace(
            result_code=1,
            idx_results={"IDX_MENISCUS_TEAR": 1},
            index_details={
                "IDX_MENISCUS_TEAR": {
                    "result_code": 1,
                    "found": True,
                    "matched_text": "private snippet",
                    "evidence": ["private evidence"],
                    "confidence": 0.9,
                    "explanation": "clear positive",
                }
            },
            error=None,
        )


@pytest.fixture
def fake_ddb(monkeypatch: pytest.MonkeyPatch) -> FakeDynamoDB:
    handler._reset_caches_for_tests()
    fake = FakeDynamoDB()
    for name in (
        "MEDICAL_CLASSIFIER_API_KEY_HASHES",
        "MEDICAL_CLASSIFIER_API_KEYS",
        "MEDICAL_CLASSIFIER_ALLOW_PLAINTEXT_API_KEYS",
        "MEDICAL_CLASSIFIER_AUDIT_TABLE",
    ):
        monkeypatch.delenv(name, raising=False)
    tables = {
        "MEDICAL_CLASSIFIER_TENANTS_TABLE": "tenants",
        "MEDICAL_CLASSIFIER_API_KEYS_TABLE": "api_keys",
        "MEDICAL_CLASSIFIER_PROJECTS_TABLE": "projects",
        "MEDICAL_CLASSIFIER_PROCEDURE_SPECS_TABLE": "procedure_specs",
        "MEDICAL_CLASSIFIER_PROCEDURE_SPEC_VERSIONS_TABLE": "procedure_spec_versions",
        "MEDICAL_CLASSIFIER_CLASSIFICATION_RUNS_TABLE": "classification_runs",
        "MEDICAL_CLASSIFIER_CLASSIFICATION_RESULTS_TABLE": "classification_results",
        "MEDICAL_CLASSIFIER_AUDIT_LOGS_TABLE": "audit_logs",
    }
    for key, value in tables.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(handler, "_get_dynamodb_client", lambda: fake)
    _seed_api_key(fake, API_KEY_A, "tenant-a")
    _seed_api_key(fake, API_KEY_B, "tenant-b")
    return fake


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _seed_api_key(fake: FakeDynamoDB, api_key: str, tenant_id: str) -> None:
    digest = _sha(api_key)
    fake.tables.setdefault("api_keys", []).append(
        {
            "api_key_hash_prefix": digest[:16],
            "api_key_hash": digest,
            "tenant_id": tenant_id,
            "key_id": f"key-{tenant_id}",
            "status": "active",
        }
    )


def _seed_tenant(fake: FakeDynamoDB, tenant_id: str, storage_mode: str | None = None) -> None:
    item = {
        "tenant_id": tenant_id,
        "customer_number": tenant_id,
        "customer_name": f"Customer {tenant_id}",
        "license_number": f"LIC-{tenant_id}",
        "status": "active",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    if storage_mode is not None:
        item["storage_mode"] = storage_mode
    fake.tables.setdefault("tenants", []).append(item)


def _event(method: str, path: str, body: dict[str, Any] | None = None, api_key: str = API_KEY_A) -> dict[str, Any]:
    return {
        "version": "2.0",
        "rawPath": path,
        "requestContext": {"http": {"method": method}},
        "headers": {"X-API-Key": api_key, handler.REQUEST_ID_HEADER: "req-1"},
        "body": json.dumps(body or {}),
        "isBase64Encoded": False,
    }


def _body(response: dict[str, Any]) -> dict[str, Any]:
    return json.loads(response["body"])


def _spec_payload() -> dict[str, Any]:
    return {
        "procedure_code": "MENISCUS",
        "procedure_name": "Meniscus repair",
        "description": "Knee meniscus tear classifier",
        "draft_spec": {
            "system_prompt": "Classify saved spec only.",
            "indexes": [
                {
                    "key": "IDX_MENISCUS_TEAR",
                    "label": "Meniscus tear",
                    "category": "diagnosis",
                    "positive_terms": ["meniscus"],
                    "negative_terms": ["no tear"],
                    "positive_phrases": ["partial meniscectomy"],
                    "negative_phrases": ["no meniscal tear"],
                    "rules": ["Return 1 only when clear"],
                    "examples": [{"text": "partial meniscectomy", "expected_result": 1}],
                    "output_type": "binary",
                    "required_evidence": False,
                }
            ],
        },
    }


def test_api_key_hash_resolves_tenant_from_dynamodb(fake_ddb: FakeDynamoDB) -> None:
    response = handler.lambda_handler(
        _event("POST", "/v1/projects", {"project_number": "1001", "name": "Tenant A"}),
        None,
    )

    assert response["statusCode"] == 201
    assert fake_ddb.tables["projects"][0]["tenant_id"] == "tenant-a"


def test_disabled_api_key_is_rejected(fake_ddb: FakeDynamoDB) -> None:
    fake_ddb.tables["api_keys"][0]["status"] = "disabled"

    response = handler.lambda_handler(
        _event("POST", "/v1/projects", {"project_number": "1001", "project_name": "Tenant A"}),
        None,
    )

    assert response["statusCode"] == 401
    assert _body(response)["error_code"] == "invalid_api_key"


def test_customer_me_defaults_missing_storage_mode_to_local_only(fake_ddb: FakeDynamoDB) -> None:
    _seed_tenant(fake_ddb, "tenant-a", storage_mode=None)

    response = handler.lambda_handler(_event("GET", "/v1/customer/me"), None)
    body = _body(response)

    assert response["statusCode"] == 200
    assert body["customer"]["tenant_id"] == "tenant-a"
    assert body["customer"]["storage_mode"] == "local_only"
    assert "api_key_hash" not in response["body"]


def test_customer_storage_policy_update_validates_storage_mode(fake_ddb: FakeDynamoDB) -> None:
    ok = handler.lambda_handler(
        _event("PUT", "/v1/customer/me/storage-policy", {"storage_mode": "hybrid"}),
        None,
    )
    bad = handler.lambda_handler(
        _event("PUT", "/v1/customer/me/storage-policy", {"storage_mode": "forever"}),
        None,
    )

    assert ok["statusCode"] == 200
    assert _body(ok)["customer"]["storage_mode"] == "hybrid"
    assert bad["statusCode"] == 422
    assert "storage_mode" in _body(bad)["message"]


def test_project_routes_are_tenant_isolated(fake_ddb: FakeDynamoDB) -> None:
    handler.lambda_handler(_event("POST", "/v1/projects", {"project_number": "1001", "name": "A"}), None)
    handler.lambda_handler(
        _event("POST", "/v1/projects", {"project_number": "1001", "name": "B"}, api_key=API_KEY_B),
        None,
    )

    a_projects = _body(handler.lambda_handler(_event("GET", "/v1/projects"), None))["projects"]
    b_projects = _body(handler.lambda_handler(_event("GET", "/v1/projects", api_key=API_KEY_B), None))[
        "projects"
    ]

    assert a_projects[0]["name"] == "A"
    assert b_projects[0]["name"] == "B"


def test_project_update_and_storage_policy_patch(fake_ddb: FakeDynamoDB) -> None:
    create = handler.lambda_handler(
        _event(
            "POST",
            "/v1/projects",
            {
                "project_number": "1001",
                "project_name": "Original",
                "description": "first",
                "default_storage_mode_override": "local_only",
            },
        ),
        None,
    )
    update = handler.lambda_handler(
        _event("PUT", "/v1/projects/1001", {"project_name": "Updated", "description": "second"}),
        None,
    )
    policy = handler.lambda_handler(
        _event("PATCH", "/v1/projects/1001/storage-policy", {"storage_mode": "hybrid"}),
        None,
    )

    assert create["statusCode"] == 201
    assert _body(update)["project"]["project_name"] == "Updated"
    assert _body(update)["project"]["description"] == "second"
    assert _body(policy)["project"]["default_storage_mode_override"] == "hybrid"


def test_procedure_spec_save_publish_and_current_lookup(fake_ddb: FakeDynamoDB) -> None:
    handler.lambda_handler(_event("POST", "/v1/projects", {"project_number": "1001", "name": "A"}), None)
    save_response = handler.lambda_handler(
        _event("POST", "/v1/projects/1001/procedure-specs", _spec_payload()),
        None,
    )
    publish_response = handler.lambda_handler(
        _event("POST", "/v1/projects/1001/procedure-specs/meniscus/publish", {}),
        None,
    )
    current_response = handler.lambda_handler(
        _event("GET", "/v1/projects/1001/procedure-specs/meniscus/current"),
        None,
    )

    assert save_response["statusCode"] == 201
    assert _body(publish_response)["procedure_spec"]["current_version"] == 1
    assert _body(current_response)["current"]["version"] == 1
    assert len(fake_ddb.tables["procedure_spec_versions"]) == 1


def test_editing_after_publish_does_not_mutate_old_version(fake_ddb: FakeDynamoDB) -> None:
    handler.lambda_handler(_event("POST", "/v1/projects", {"project_number": "1001", "name": "A"}), None)
    handler.lambda_handler(_event("POST", "/v1/projects/1001/procedure-specs", _spec_payload()), None)
    handler.lambda_handler(_event("POST", "/v1/projects/1001/procedure-specs/meniscus/publish", {}), None)
    first_hash = fake_ddb.tables["procedure_spec_versions"][0]["spec_hash"]
    payload = _spec_payload()
    payload["draft_spec"]["indexes"][0]["label"] = "Changed draft label"

    handler.lambda_handler(_event("PUT", "/v1/projects/1001/procedure-specs/meniscus", payload), None)
    handler.lambda_handler(_event("POST", "/v1/projects/1001/procedure-specs/meniscus/publish", {}), None)

    assert len(fake_ddb.tables["procedure_spec_versions"]) == 2
    assert fake_ddb.tables["procedure_spec_versions"][0]["version"] == 1
    assert fake_ddb.tables["procedure_spec_versions"][0]["spec_hash"] == first_hash
    assert fake_ddb.tables["procedure_spec_versions"][1]["version"] == 2
    assert fake_ddb.tables["procedure_spec_versions"][1]["spec"]["indexes"][0]["label"] == "Changed draft label"


def test_rejects_spec_without_procedure_name(fake_ddb: FakeDynamoDB) -> None:
    payload = _spec_payload()
    payload["procedure_name"] = ""

    response = handler.lambda_handler(
        _event("POST", "/v1/projects/1001/procedure-specs", payload),
        None,
    )

    assert response["statusCode"] == 422
    assert "procedure_name is required" in _body(response)["message"]


def test_rejects_duplicate_idx_keys(fake_ddb: FakeDynamoDB) -> None:
    payload = _spec_payload()
    payload["draft_spec"]["indexes"].append(dict(payload["draft_spec"]["indexes"][0]))

    response = handler.lambda_handler(
        _event("POST", "/v1/projects/1001/procedure-specs", payload),
        None,
    )
    body = _body(response)

    assert response["statusCode"] == 422
    assert body["error_code"] == "invalid_request"
    assert "duplicate IDX key" in body["message"]


def test_rejects_publish_without_idx_rows(fake_ddb: FakeDynamoDB) -> None:
    payload = _spec_payload()
    payload["draft_spec"]["indexes"] = []
    handler.lambda_handler(_event("POST", "/v1/projects/1001/procedure-specs", payload), None)

    response = handler.lambda_handler(
        _event("POST", "/v1/projects/1001/procedure-specs/meniscus/publish", {}),
        None,
    )
    body = _body(response)

    assert response["statusCode"] == 422
    assert body["error_code"] == "invalid_request"
    assert "at least one IDX row" in body["message"]


def test_classification_without_active_spec_fails_clearly(fake_ddb: FakeDynamoDB) -> None:
    response = handler.lambda_handler(
        _event(
            "POST",
            "/v1/classification-runs",
            {
                "project_number": "1001",
                "procedure_code": "meniscus",
                "file_name": "doc.pdf",
                "cleaned_full": "private text",
            },
        ),
        None,
    )

    assert response["statusCode"] == 404
    assert _body(response)["error_code"] == "current_procedure_spec_not_found"


def test_classification_uses_active_spec_and_stores_sanitized_records(
    fake_ddb: FakeDynamoDB,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = RecordingClassifierService()
    monkeypatch.setattr(handler, "_get_classifier_service", lambda: service)
    handler.lambda_handler(_event("POST", "/v1/projects", {"project_number": "1001", "name": "A"}), None)
    handler.lambda_handler(_event("POST", "/v1/projects/1001/procedure-specs", _spec_payload()), None)
    handler.lambda_handler(_event("POST", "/v1/projects/1001/procedure-specs/meniscus/publish", {}), None)

    response = handler.lambda_handler(
        _event(
            "POST",
            "/v1/classification-runs",
            {
                "project_number": "1001",
                "procedure_code": "meniscus",
                "file_name": "doc.pdf",
                "cleaned_full": "very private medical text",
                "external_document_id": "case-1",
            },
        ),
        None,
    )

    body = _body(response)
    stored_result = fake_ddb.tables["classification_results"][0]
    stored_audit = fake_ddb.tables["audit_logs"][0]
    serialized_storage = json.dumps(fake_ddb.tables, ensure_ascii=False)

    assert response["statusCode"] == 200
    assert body["spec_version"] == 1
    assert service.calls[0].prompt_json["IDX_MENISCUS_TEAR"][0]
    assert stored_result["indexes"] == {"IDX_MENISCUS_TEAR": 1}
    assert stored_result["document_hash"] == _sha("very private medical text")
    assert stored_result["storage_policy_used"] == "local_only"
    assert stored_result.get("document_storage_uri") is None
    assert fake_ddb.tables["classification_runs"][0]["file_name"] == "doc.pdf"
    assert "matched_text" not in json.dumps(stored_result, ensure_ascii=False)
    assert "evidence" not in json.dumps(stored_result, ensure_ascii=False)
    assert stored_audit["document_hash"] == _sha("very private medical text")
    assert stored_audit["storage_policy_used"] == "local_only"
    assert "very private medical text" not in serialized_storage
    assert "private snippet" not in serialized_storage


def test_cloud_and_hybrid_storage_policy_resolution_never_stores_raw_text_without_s3(
    fake_ddb: FakeDynamoDB,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_tenant(fake_ddb, "tenant-a", storage_mode="hybrid")
    monkeypatch.setattr(handler, "_get_classifier_service", lambda: RecordingClassifierService())
    handler.lambda_handler(
        _event(
            "POST",
            "/v1/projects",
            {
                "project_number": "1001",
                "project_name": "A",
                "default_storage_mode_override": "cloud",
            },
        ),
        None,
    )
    handler.lambda_handler(_event("POST", "/v1/projects/1001/procedure-specs", _spec_payload()), None)
    handler.lambda_handler(_event("POST", "/v1/projects/1001/procedure-specs/meniscus/publish", {}), None)

    response = handler.lambda_handler(
        _event(
            "POST",
            "/v1/classification-runs",
            {
                "project_number": "1001",
                "procedure_code": "meniscus",
                "file_name": "doc.pdf",
                "document_text": "raw private text",
                "storage_preference": "cloud",
                "metadata": {"external_trace_id": "trace-1", "raw_note": "private"},
            },
        ),
        None,
    )
    serialized_storage = json.dumps(fake_ddb.tables, ensure_ascii=False)

    assert response["statusCode"] == 200
    assert _body(response)["storage_policy_used"] == "cloud"
    assert _body(response)["document_storage_uri"] is None
    assert fake_ddb.tables["classification_runs"][0]["storage_policy_used"] == "cloud"
    assert fake_ddb.tables["classification_runs"][0]["metadata"] == {"external_trace_id": "trace-1"}
    assert "raw private text" not in serialized_storage
    assert "raw_note" not in serialized_storage


def test_get_classification_run_returns_sanitized_result_and_is_tenant_isolated(
    fake_ddb: FakeDynamoDB,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(handler, "_get_classifier_service", lambda: RecordingClassifierService())
    handler.lambda_handler(_event("POST", "/v1/projects", {"project_number": "1001", "name": "A"}), None)
    handler.lambda_handler(_event("POST", "/v1/projects/1001/procedure-specs", _spec_payload()), None)
    handler.lambda_handler(_event("POST", "/v1/projects/1001/procedure-specs/meniscus/publish", {}), None)
    classify_response = handler.lambda_handler(
        _event(
            "POST",
            "/v1/classification-runs",
            {
                "project_number": "1001",
                "procedure_code": "meniscus",
                "file_name": "doc.pdf",
                "cleaned_full": "private text",
            },
        ),
        None,
    )
    run_id = _body(classify_response)["run_id"]

    own_response = handler.lambda_handler(_event("GET", f"/v1/classification-runs/{run_id}"), None)
    other_response = handler.lambda_handler(
        _event("GET", f"/v1/classification-runs/{run_id}", api_key=API_KEY_B),
        None,
    )
    serialized = own_response["body"]

    assert own_response["statusCode"] == 200
    assert _body(own_response)["classification_result"]["indexes"] == {"IDX_MENISCUS_TEAR": 1}
    assert "matched_text" not in serialized
    assert "evidence" not in serialized
    assert other_response["statusCode"] == 404


def _to_ddb_item(item: dict[str, Any]) -> dict[str, Any]:
    return {key: _to_ddb_value(value) for key, value in item.items() if value is not None}


def _to_ddb_value(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"BOOL": value}
    if isinstance(value, int | float):
        return {"N": str(value)}
    if isinstance(value, dict):
        return {"M": _to_ddb_item(value)}
    if isinstance(value, list):
        return {"L": [_to_ddb_value(item) for item in value]}
    return {"S": str(value)}
