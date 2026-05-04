from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.lambda_handlers import medical_classifier_handler as handler


API_KEY = "test-api-key"


class FakeClassifierService:
    def __init__(self, result: Any | None = None, exc: Exception | None = None) -> None:
        self.result = result or _classification_result()
        self.exc = exc
        self.calls: list[Any] = []

    def classify_document(self, document: Any) -> Any:
        self.calls.append(document)
        if self.exc is not None:
            raise self.exc
        return self.result


@pytest.fixture(autouse=True)
def reset_handler_state(monkeypatch: pytest.MonkeyPatch) -> None:
    handler._reset_caches_for_tests()
    for name in (
        "MEDICAL_CLASSIFIER_API_KEY_HASHES",
        "MEDICAL_CLASSIFIER_API_KEYS",
        "MEDICAL_CLASSIFIER_ALLOW_PLAINTEXT_API_KEYS",
        "MEDICAL_CLASSIFIER_AUDIT_TABLE",
    ):
        monkeypatch.delenv(name, raising=False)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _set_hashed_key(monkeypatch: pytest.MonkeyPatch, key: str = API_KEY) -> None:
    monkeypatch.setenv("MEDICAL_CLASSIFIER_API_KEY_HASHES", _sha256(key))


def _classification_result(
    *,
    result_code: int = 1,
    indexes: dict[str, int] | None = None,
    index_details: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        result_code=result_code,
        idx_results=indexes or {"IDX_KEY": 1},
        index_details=index_details
        or {
            "IDX_KEY": {
                "result_code": result_code,
                "found": result_code == 1,
                "matched_text": "matched snippet",
                "evidence": ["evidence snippet"],
                "confidence": 0.93,
                "explanation": "clear finding",
            }
        },
        error=error,
    )


def _valid_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "file_name": "doc-1.pdf",
        "doc_type": 3,
        "treatment_code": "arthroscopy_knee",
        "subject_ind": 2,
        "cleaned_desc": "short text",
        "cleaned_full": "sensitive medical text",
        "metadata": {"source": "unit"},
    }
    payload.update(overrides)
    return payload


def _event(
    *,
    body: Any,
    api_key: str | None = API_KEY,
    path: str = handler.CLASSIFY_PATH,
    method: str = "POST",
    request_id: str = "req-test",
) -> dict[str, Any]:
    headers = {handler.REQUEST_ID_HEADER: request_id}
    if api_key is not None:
        headers["X-API-Key"] = api_key
    raw_body = body if isinstance(body, str) else json.dumps(body)
    return {
        "version": "2.0",
        "rawPath": path,
        "requestContext": {"http": {"method": method}},
        "headers": headers,
        "body": raw_body,
        "isBase64Encoded": False,
    }


def _body(response: dict[str, Any]) -> dict[str, Any]:
    return json.loads(response["body"])


def test_happy_path_returns_omniscanner_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_hashed_key(monkeypatch)
    service = FakeClassifierService()
    monkeypatch.setattr(handler, "_get_classifier_service", lambda: service)

    response = handler.lambda_handler(_event(body=_valid_payload()), None)

    assert response["statusCode"] == 200
    body = _body(response)
    assert body["result_code"] == 1
    assert body["request_id"] == "req-test"
    assert body["indexes"] == {"IDX_KEY": 1}
    assert body["index_details"]["IDX_KEY"]["matched_text"] == "matched snippet"
    assert "error_code" not in body
    assert service.calls[0].treatment_code == "arthroscopy_knee"
    assert service.calls[0].file_full_text == "sensitive medical text"


def test_missing_api_key_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_hashed_key(monkeypatch)

    response = handler.lambda_handler(_event(body=_valid_payload(), api_key=None), None)

    assert response["statusCode"] == 401
    assert _body(response)["error_code"] == "invalid_api_key"


def test_invalid_api_key_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_hashed_key(monkeypatch, key="expected-key")

    response = handler.lambda_handler(_event(body=_valid_payload(), api_key="wrong-key"), None)

    assert response["statusCode"] == 401
    assert _body(response)["error_code"] == "invalid_api_key"


def test_plaintext_key_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEDICAL_CLASSIFIER_API_KEYS", API_KEY)

    response = handler.lambda_handler(_event(body=_valid_payload()), None)

    assert response["statusCode"] == 401
    assert _body(response)["error_code"] == "invalid_api_key"


def test_plaintext_key_is_allowed_only_with_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEDICAL_CLASSIFIER_API_KEYS", API_KEY)
    monkeypatch.setenv("MEDICAL_CLASSIFIER_ALLOW_PLAINTEXT_API_KEYS", "true")
    service = FakeClassifierService()
    monkeypatch.setattr(handler, "_get_classifier_service", lambda: service)

    response = handler.lambda_handler(_event(body=_valid_payload()), None)

    assert response["statusCode"] == 200
    assert _body(response)["result_code"] == 1


def test_invalid_json_returns_422(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_hashed_key(monkeypatch)

    response = handler.lambda_handler(_event(body="{not-json"), None)

    assert response["statusCode"] == 422
    assert _body(response)["error_code"] == "invalid_request"


def test_invalid_schema_returns_422(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_hashed_key(monkeypatch)

    response = handler.lambda_handler(_event(body={"file_name": "doc.pdf"}), None)

    assert response["statusCode"] == 422
    assert _body(response)["error_code"] == "invalid_request"


def test_wrong_route_or_method_returns_404_or_405(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_hashed_key(monkeypatch)

    wrong_route = handler.lambda_handler(_event(body=_valid_payload(), path="/wrong"), None)
    wrong_method = handler.lambda_handler(_event(body=_valid_payload(), method="GET"), None)

    assert wrong_route["statusCode"] == 404
    assert _body(wrong_route)["error_code"] == "not_found"
    assert wrong_method["statusCode"] == 405
    assert _body(wrong_method)["error_code"] == "method_not_allowed"


def test_classifier_exception_returns_controlled_500(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_hashed_key(monkeypatch)
    service = FakeClassifierService(exc=RuntimeError("internal sensitive failure"))
    monkeypatch.setattr(handler, "_get_classifier_service", lambda: service)

    response = handler.lambda_handler(_event(body=_valid_payload()), None)
    body = _body(response)

    assert response["statusCode"] == 500
    assert body["result_code"] == 9
    assert body["request_id"] == "req-test"
    assert body["indexes"] == {}
    assert body["index_details"] == {}
    assert body["error_code"] == "classifier_exception"
    assert "internal sensitive failure" not in response["body"]


def test_dynamodb_write_success_uses_only_allowed_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_hashed_key(monkeypatch)
    monkeypatch.setenv("MEDICAL_CLASSIFIER_AUDIT_TABLE", "audit-table")
    service = FakeClassifierService()
    monkeypatch.setattr(handler, "_get_classifier_service", lambda: service)
    captured: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(handler, "_put_audit_item", lambda table, item: captured.append((table, item)))

    response = handler.lambda_handler(_event(body=_valid_payload()), None)

    assert response["statusCode"] == 200
    assert len(captured) == 1
    table, item = captured[0]
    assert table == "audit-table"
    assert set(item) == {
        "request_id",
        "api_key_id_hash",
        "treatment_code",
        "document_hash",
        "result_code",
        "indexes",
        "created_at",
    }
    assert item["request_id"] == "req-test"
    assert item["api_key_id_hash"] == _sha256(API_KEY)
    assert item["document_hash"] == _sha256("sensitive medical text")
    assert item["result_code"] == 1
    assert item["indexes"] == {"IDX_KEY": 1}
    serialized = json.dumps(item, ensure_ascii=False)
    assert "cleaned_full" not in serialized
    assert "cleaned_desc" not in serialized
    assert "matched snippet" not in serialized
    assert "evidence snippet" not in serialized
    assert API_KEY not in serialized


def test_dynamodb_write_failure_does_not_fail_request(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _set_hashed_key(monkeypatch)
    monkeypatch.setenv("MEDICAL_CLASSIFIER_AUDIT_TABLE", "audit-table")
    service = FakeClassifierService()
    monkeypatch.setattr(handler, "_get_classifier_service", lambda: service)

    def fail_write(table: str, item: dict[str, Any]) -> None:
        raise RuntimeError("ddb failure containing sensitive medical text")

    monkeypatch.setattr(handler, "_put_audit_item", fail_write)
    caplog.set_level("WARNING")

    response = handler.lambda_handler(_event(body=_valid_payload()), None)

    assert response["statusCode"] == 200
    assert "medical_classifier_audit_write_failed" in caplog.text
    assert "sensitive medical text" not in caplog.text
    assert API_KEY not in caplog.text


def test_privacy_audit_and_logs_do_not_include_text_snippets_or_api_key(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    api_key = "super-secret-api-key"
    medical_text = "very private medical document"
    matched_text = "private matched text"
    evidence = "private evidence text"
    _set_hashed_key(monkeypatch, key=api_key)
    monkeypatch.setenv("MEDICAL_CLASSIFIER_AUDIT_TABLE", "audit-table")
    service = FakeClassifierService(
        result=_classification_result(
            index_details={
                "IDX_KEY": {
                    "result_code": 1,
                    "found": True,
                    "matched_text": matched_text,
                    "evidence": [evidence],
                }
            }
        )
    )
    monkeypatch.setattr(handler, "_get_classifier_service", lambda: service)
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(handler, "_put_audit_item", lambda table, item: captured.append(item))
    caplog.set_level("WARNING")

    response = handler.lambda_handler(
        _event(body=_valid_payload(cleaned_full=medical_text), api_key=api_key),
        None,
    )

    assert response["statusCode"] == 200
    audit_and_logs = json.dumps(captured, ensure_ascii=False) + caplog.text
    assert medical_text not in audit_and_logs
    assert matched_text not in audit_and_logs
    assert evidence not in audit_and_logs
    assert api_key not in audit_and_logs
    assert _body(response)["index_details"]["IDX_KEY"]["matched_text"] == matched_text

