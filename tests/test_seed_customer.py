from __future__ import annotations

import json
import re
from typing import Any

from app.services.medical_classifier.cloud_store import _from_dynamodb_item
from scripts import seed_customer


class FakeDynamoDB:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {}

    def put_item(self, *, TableName: str, Item: dict[str, Any]) -> None:  # noqa: N803
        item = _from_dynamodb_item(Item)
        table = self.tables.setdefault(TableName, [])
        if "api_key_hash_prefix" in item:
            keys = ("api_key_hash_prefix",)
        elif "sort_key" in item:
            keys = ("tenant_id", "sort_key")
        else:
            keys = ("tenant_id",)
        table[:] = [existing for existing in table if not all(existing.get(key) == item.get(key) for key in keys)]
        table.append(item)

    def get_item(self, *, TableName: str, Key: dict[str, Any]) -> dict[str, Any]:  # noqa: N803
        key = _from_dynamodb_item(Key)
        for item in self.tables.get(TableName, []):
            if all(item.get(k) == v for k, v in key.items()):
                return {"Item": seed_customer._to_dynamodb_item(item)}
        return {}


def test_create_tenant_is_idempotent() -> None:
    client = FakeDynamoDB()
    tables = seed_customer.SeedTables("tenants", "api_keys", "projects", "specs")

    first = seed_customer.create_tenant(
        client,
        tables,
        tenant_name="Customer A",
        license_number="LIC-001",
        storage_mode="local_only",
    )
    second = seed_customer.create_tenant(client, tables, tenant_name="Customer A")

    assert first["tenant_id"] == "tenant-customer-a"
    assert first["customer_name"] == "Customer A"
    assert first["license_number"] == "LIC-001"
    assert first["storage_mode"] == "local_only"
    assert first["created"] is True
    assert second["created"] is False
    assert len(client.tables["tenants"]) == 1


def test_create_api_key_stores_hash_only() -> None:
    client = FakeDynamoDB()
    tables = seed_customer.SeedTables("tenants", "api_keys", "projects", "specs")

    record = seed_customer.create_api_key(
        client,
        tables,
        tenant_id="tenant-a",
        key_name="omniscan-poc",
        api_key="plain-secret-key",
    )

    serialized = json.dumps(client.tables, ensure_ascii=False)
    assert record["api_key_hash_prefix"]
    assert re.fullmatch(r"[a-f0-9]{64}", record["api_key_hash"])
    assert "plain-secret-key" not in serialized


def test_onboard_customer_creates_project_key_and_empty_draft(monkeypatch) -> None:
    client = FakeDynamoDB()
    tables = seed_customer.SeedTables("tenants", "api_keys", "projects", "specs")
    monkeypatch.setattr(seed_customer, "make_api_key", lambda: "generated-secret")

    args = seed_customer.build_parser().parse_args(
        [
            "--dry-run",
            "onboard-customer",
            "--tenant-name",
            "Customer A",
            "--license-number",
            "LIC-001",
            "--storage-mode",
            "local_only",
            "--project-number",
            "10023",
            "--project-name",
            "POC Project",
            "--generate-api-key",
            "--create-empty-spec",
            "--procedure-code",
            "arthroscopy_knee",
            "--procedure-name",
            "Arthroscopy Knee",
        ]
    )
    args.dry_run = False

    result = seed_customer.onboard_customer(client, tables, args)

    assert result["tenant"]["tenant_id"] == "tenant-customer-a"
    assert result["tenant"]["license_number"] == "LIC-001"
    assert result["tenant"]["storage_mode"] == "local_only"
    assert result["project"]["project_number"] == "10023"
    assert result["generated_api_key"] == "generated-secret"
    assert "api_key_hash" not in result["api_key_record"]
    assert result["procedure_spec"]["draft_spec"]["indexes"] == []
    assert "generated-secret" not in json.dumps(client.tables, ensure_ascii=False)


def test_dry_run_does_not_build_aws_client(monkeypatch, capsys) -> None:
    def fail_build_client() -> None:
        raise AssertionError("dry-run should not create a boto3 client")

    monkeypatch.setattr(seed_customer, "build_client", fail_build_client)

    rc = seed_customer.main(
        [
            "--dry-run",
            "onboard-customer",
            "--tenant-name",
            "Customer A",
            "--license-number",
            "LIC-001",
            "--project-number",
            "10023",
            "--project-name",
            "POC Project",
            "--generate-api-key",
        ]
    )

    output = capsys.readouterr().out
    assert rc == 0
    assert '"tenant_id": "tenant-customer-a"' in output
    assert '"generated_api_key"' in output


def test_update_storage_policy_and_disable_api_key() -> None:
    client = FakeDynamoDB()
    tables = seed_customer.SeedTables("tenants", "api_keys", "projects", "specs")
    seed_customer.create_tenant(client, tables, tenant_name="Customer A")
    api_key = seed_customer.create_api_key(
        client,
        tables,
        tenant_id="tenant-customer-a",
        key_name="omniscan-poc",
        api_key="plain-secret-key",
    )

    tenant = seed_customer.update_storage_policy(
        client,
        tables,
        tenant_id="tenant-customer-a",
        storage_mode="hybrid",
    )
    disabled = seed_customer.disable_api_key(
        client,
        tables,
        api_key_hash_prefix=api_key["api_key_hash_prefix"],
    )

    assert tenant["storage_mode"] == "hybrid"
    assert disabled["status"] == "disabled"
    assert disabled["disabled_at"]
    assert "api_key_hash" not in disabled
