#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import secrets
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from getpass import getpass
from typing import Any

from app.services.medical_classifier.cloud_store import (
    _from_dynamodb_item,
    _to_dynamodb_item,
    _to_dynamodb_value,
    normalize_storage_mode,
    sha256_text,
    spec_hash,
    validate_procedure_spec_body,
)

DEFAULT_TABLES = {
    "tenants": "medicalclassifier-tenants",
    "api_keys": "medicalclassifier-api-keys",
    "projects": "medicalclassifier-projects",
    "procedure_specs": "medicalclassifier-procedure-specs",
}


@dataclass(frozen=True)
class SeedTables:
    tenants: str = DEFAULT_TABLES["tenants"]
    api_keys: str = DEFAULT_TABLES["api_keys"]
    projects: str = DEFAULT_TABLES["projects"]
    procedure_specs: str = DEFAULT_TABLES["procedure_specs"]


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def tenant_id_from_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    if not slug:
        raise ValueError("tenant name must contain at least one letter or number")
    return f"tenant-{slug}"


def make_api_key() -> str:
    return f"mc_live_{secrets.token_urlsafe(32)}"


def get_item(client: Any, table_name: str, key: dict[str, Any]) -> dict[str, Any] | None:
    response = client.get_item(
        TableName=table_name,
        Key={name: _to_dynamodb_value(value) for name, value in key.items()},
    )
    item = response.get("Item")
    return _from_dynamodb_item(item) if item else None


def put_item(client: Any, table_name: str, item: dict[str, Any], *, dry_run: bool) -> None:
    if dry_run:
        return
    client.put_item(TableName=table_name, Item=_to_dynamodb_item(item))


def create_tenant(
    client: Any,
    tables: SeedTables,
    *,
    tenant_name: str | None = None,
    customer_name: str | None = None,
    tenant_id: str | None = None,
    license_number: str = "",
    storage_mode: str = "local_only",
    dry_run: bool = False,
) -> dict[str, Any]:
    resolved_name = (customer_name or tenant_name or "").strip()
    if not resolved_name:
        raise ValueError("--customer-name is required")
    resolved_tenant_id = tenant_id or tenant_id_from_name(resolved_name)
    now = utc_now_iso()
    item = {
        "tenant_id": resolved_tenant_id,
        "tenant_name": resolved_name,
        "customer_name": resolved_name,
        "customer_number": resolved_tenant_id,
        "customer_id": resolved_tenant_id,
        "license_number": license_number.strip(),
        "storage_mode": normalize_storage_mode(storage_mode),
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }
    if dry_run:
        return {**item, "created": True}

    existing = get_item(client, tables.tenants, {"tenant_id": resolved_tenant_id})
    if existing:
        return {
            **existing,
            "customer_name": existing.get("customer_name") or resolved_name,
            "tenant_name": existing.get("tenant_name") or resolved_name,
            "customer_number": existing.get("customer_number") or resolved_tenant_id,
            "customer_id": existing.get("customer_id") or resolved_tenant_id,
            "license_number": existing.get("license_number") or license_number.strip(),
            "storage_mode": normalize_storage_mode(existing.get("storage_mode")),
            "created": False,
        }

    put_item(client, tables.tenants, item, dry_run=dry_run)
    return {**item, "created": True}


def update_storage_policy(
    client: Any,
    tables: SeedTables,
    *,
    tenant_id: str,
    storage_mode: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    now = utc_now_iso()
    existing = get_item(client, tables.tenants, {"tenant_id": tenant_id})
    if not existing:
        raise ValueError(f"tenant not found: {tenant_id}")
    item = {
        **existing,
        "storage_mode": normalize_storage_mode(storage_mode),
        "updated_at": now,
    }
    put_item(client, tables.tenants, item, dry_run=dry_run)
    return {**item, "updated": True}


def create_api_key(
    client: Any,
    tables: SeedTables,
    *,
    tenant_id: str,
    key_name: str,
    api_key: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    api_key_hash = sha256_text(api_key)
    prefix = api_key_hash[:16]
    now = utc_now_iso()
    item = {
        "api_key_hash_prefix": prefix,
        "api_key_hash": api_key_hash,
        "tenant_id": tenant_id,
        "key_id": f"{tenant_id}#{key_name}#{prefix}",
        "key_name": key_name,
        "name": key_name,
        "status": "active",
        "scopes": ["omniscan:poc"],
        "created_at": now,
        "last_used_at": None,
        "disabled_at": None,
    }
    if dry_run:
        return {**item, "created": True}

    existing = get_item(client, tables.api_keys, {"api_key_hash_prefix": prefix})
    if existing:
        return {**existing, "created": False}

    put_item(client, tables.api_keys, item, dry_run=dry_run)
    return {**item, "created": True}


def disable_api_key(
    client: Any,
    tables: SeedTables,
    *,
    api_key_hash_prefix: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    existing = get_item(client, tables.api_keys, {"api_key_hash_prefix": api_key_hash_prefix})
    if not existing:
        raise ValueError(f"api key not found for prefix: {api_key_hash_prefix}")
    item = {
        **existing,
        "status": "disabled",
        "disabled_at": existing.get("disabled_at") or utc_now_iso(),
    }
    put_item(client, tables.api_keys, item, dry_run=dry_run)
    return {**redact_api_key_record(item), "updated": True}


def create_project(
    client: Any,
    tables: SeedTables,
    *,
    tenant_id: str,
    project_number: str,
    project_name: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    sort_key = f"PROJECT#{project_number.strip()}"
    now = utc_now_iso()
    item = {
        "tenant_id": tenant_id,
        "sort_key": sort_key,
        "project_id": str(uuid.uuid4()),
        "project_number": project_number.strip(),
        "project_name": project_name.strip() or project_number.strip(),
        "name": project_name.strip() or project_number.strip(),
        "description": "",
        "default_storage_mode_override": None,
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }
    if dry_run:
        return {**item, "created": True}

    existing = get_item(client, tables.projects, {"tenant_id": tenant_id, "sort_key": sort_key})
    if existing:
        return {**existing, "created": False}

    put_item(client, tables.projects, item, dry_run=dry_run)
    return {**item, "created": True}


def create_empty_procedure_spec(
    client: Any,
    tables: SeedTables,
    *,
    tenant_id: str,
    project_number: str,
    procedure_code: str,
    procedure_name: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    normalized_code = procedure_code.strip().lower()
    sort_key = f"PROJECT#{project_number.strip()}#PROC#{normalized_code}"
    draft_spec = {
        "system_prompt": "Classify only clear evidence from the current document.",
        "indexes": [],
    }
    validate_procedure_spec_body(draft_spec, require_publishable=False)
    now = utc_now_iso()
    item = {
        "tenant_id": tenant_id,
        "sort_key": sort_key,
        "project_number": project_number.strip(),
        "procedure_code": normalized_code,
        "procedure_name": procedure_name.strip(),
        "description": "",
        "status": "draft",
        "current_version": 0,
        "draft_spec": draft_spec,
        "current_spec_hash": spec_hash(draft_spec),
        "created_at": now,
        "updated_at": now,
    }
    if dry_run:
        return {**item, "created": True}

    existing = get_item(client, tables.procedure_specs, {"tenant_id": tenant_id, "sort_key": sort_key})
    if existing:
        return {**existing, "created": False}

    put_item(client, tables.procedure_specs, item, dry_run=dry_run)
    return {**item, "created": True}


def onboard_customer(client: Any, tables: SeedTables, args: argparse.Namespace) -> dict[str, Any]:
    tenant = create_tenant(
        client,
        tables,
        tenant_name=args.tenant_name,
        tenant_id=args.tenant_id,
        license_number=args.license_number,
        storage_mode=args.storage_mode,
        dry_run=args.dry_run,
    )
    project = create_project(
        client,
        tables,
        tenant_id=tenant["tenant_id"],
        project_number=args.project_number,
        project_name=args.project_name,
        dry_run=args.dry_run,
    )
    result: dict[str, Any] = {"tenant": tenant, "project": project}
    if args.generate_api_key or args.prompt_api_key or args.api_key:
        generated = args.generate_api_key
        api_key = make_api_key() if generated else args.api_key
        if args.prompt_api_key:
            api_key = getpass("API key (input hidden): ")
        if not api_key:
            raise ValueError("API key is required")
        api_key_record = create_api_key(
            client,
            tables,
            tenant_id=tenant["tenant_id"],
            key_name=args.key_name,
            api_key=api_key,
            dry_run=args.dry_run,
        )
        result["api_key_record"] = redact_api_key_record(api_key_record)
        if generated:
            result["generated_api_key"] = api_key
            result["generated_api_key_notice"] = "Store this now. It will not be recoverable from DynamoDB."
    if args.create_empty_spec:
        result["procedure_spec"] = create_empty_procedure_spec(
            client,
            tables,
            tenant_id=tenant["tenant_id"],
            project_number=args.project_number,
            procedure_code=args.procedure_code,
            procedure_name=args.procedure_name,
            dry_run=args.dry_run,
        )
    return result


def redact_api_key_record(record: dict[str, Any]) -> dict[str, Any]:
    safe = dict(record)
    safe.pop("api_key_hash", None)
    return safe


def build_client() -> Any:
    import boto3

    return boto3.client("dynamodb")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed first-customer MedicalClassifier POC data.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print intended writes without saving.")
    parser.add_argument("--tenants-table", default=DEFAULT_TABLES["tenants"])
    parser.add_argument("--api-keys-table", default=DEFAULT_TABLES["api_keys"])
    parser.add_argument("--projects-table", default=DEFAULT_TABLES["projects"])
    parser.add_argument("--procedure-specs-table", default=DEFAULT_TABLES["procedure_specs"])

    sub = parser.add_subparsers(dest="command", required=True)

    tenant = sub.add_parser("create-tenant")
    tenant.add_argument("--customer-name", "--tenant-name", dest="tenant_name", required=True)
    tenant.add_argument("--tenant-id")
    tenant.add_argument("--license-number", default="")
    tenant.add_argument("--storage-mode", default="local_only", choices=["local_only", "cloud", "hybrid"])

    storage = sub.add_parser("update-storage-policy")
    storage.add_argument("--tenant-id", required=True)
    storage.add_argument("--storage-mode", required=True, choices=["local_only", "cloud", "hybrid"])

    api_key = sub.add_parser("create-api-key")
    api_key.add_argument("--tenant-id", required=True)
    api_key.add_argument("--key-name", default="omniscan-poc")
    api_key.add_argument("--api-key")
    api_key.add_argument("--prompt-api-key", action="store_true")
    api_key.add_argument("--generate-api-key", action="store_true")

    disable_key = sub.add_parser("disable-api-key")
    disable_key.add_argument("--api-key-hash-prefix", required=True)

    project = sub.add_parser("create-project")
    project.add_argument("--tenant-id", required=True)
    project.add_argument("--project-number", required=True)
    project.add_argument("--project-name", required=True)

    onboard = sub.add_parser("onboard-customer")
    onboard.add_argument("--customer-name", "--tenant-name", dest="tenant_name", required=True)
    onboard.add_argument("--tenant-id")
    onboard.add_argument("--license-number", required=True)
    onboard.add_argument("--storage-mode", default="local_only", choices=["local_only", "cloud", "hybrid"])
    onboard.add_argument("--project-number", required=True)
    onboard.add_argument("--project-name", required=True)
    onboard.add_argument("--key-name", default="omniscan-poc")
    onboard.add_argument("--api-key")
    onboard.add_argument("--prompt-api-key", action="store_true")
    onboard.add_argument("--generate-api-key", action="store_true")
    onboard.add_argument("--create-empty-spec", action="store_true")
    onboard.add_argument("--procedure-code", default="poc_procedure")
    onboard.add_argument("--procedure-name", default="POC Procedure")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    tables = SeedTables(
        tenants=args.tenants_table,
        api_keys=args.api_keys_table,
        projects=args.projects_table,
        procedure_specs=args.procedure_specs_table,
    )
    client = None if args.dry_run else build_client()

    if args.command == "create-tenant":
        result = create_tenant(
            client,
            tables,
            tenant_name=args.tenant_name,
            tenant_id=args.tenant_id,
            license_number=args.license_number,
            storage_mode=args.storage_mode,
            dry_run=args.dry_run,
        )
    elif args.command == "update-storage-policy":
        result = update_storage_policy(
            client,
            tables,
            tenant_id=args.tenant_id,
            storage_mode=args.storage_mode,
            dry_run=args.dry_run,
        )
    elif args.command == "create-api-key":
        generated = args.generate_api_key
        api_key = make_api_key() if generated else args.api_key
        if args.prompt_api_key:
            api_key = getpass("API key (input hidden): ")
        if not api_key:
            raise ValueError("Use --generate-api-key, --prompt-api-key, or --api-key")
        record = create_api_key(
            client,
            tables,
            tenant_id=args.tenant_id,
            key_name=args.key_name,
            api_key=api_key,
            dry_run=args.dry_run,
        )
        result = {"api_key_record": redact_api_key_record(record)}
        if generated:
            result["generated_api_key"] = api_key
            result["generated_api_key_notice"] = "Store this now. It will not be recoverable from DynamoDB."
    elif args.command == "disable-api-key":
        result = disable_api_key(
            client,
            tables,
            api_key_hash_prefix=args.api_key_hash_prefix,
            dry_run=args.dry_run,
        )
    elif args.command == "create-project":
        result = create_project(
            client,
            tables,
            tenant_id=args.tenant_id,
            project_number=args.project_number,
            project_name=args.project_name,
            dry_run=args.dry_run,
        )
    elif args.command == "onboard-customer":
        result = onboard_customer(client, tables, args)
    else:  # pragma: no cover
        raise ValueError(f"unknown command {args.command}")

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
