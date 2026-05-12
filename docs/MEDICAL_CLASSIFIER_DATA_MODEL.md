# MedicalClassifier Cloud Data Model

Phase 1 uses the existing serverless stack: API Gateway, Lambda, DynamoDB
PAY_PER_REQUEST tables, CloudWatch, and SSM references. The cloud backend is
the source of truth for customers, API keys, projects, procedure specs, spec
versions, classification runs/results, and sanitized audit logs.

## Storage Policy

Customer `storage_mode` controls whether Medicals may store document text or
files:

- `local_only`: default. Do not persist raw document text, extracted text, or
  PDFs in the cloud.
- `cloud`: customer permits cloud document/text storage.
- `hybrid`: customer permits optional cloud storage, but each project/request
  must opt in.

If `storage_mode` is missing on an existing tenant, the backend treats it as
`local_only`.

This implementation records policy decisions and enforces the safe default.
Encrypted S3 document persistence is not active yet, so even `cloud` requests
store only `document_hash`, sanitized metadata, run/result summaries, spec
version/hash, and sanitized audit records. Do not fake document storage by
placing raw text in DynamoDB.

## Tables

`tenants`

- Hash key: `tenant_id`
- Fields: `tenant_id`, `customer_number`, `customer_id`, `license_number`,
  `product_license_id`, `customer_name`, `contact_name`, `address`, `email`,
  `phone`, `storage_mode`, `status`, timestamps, optional limits/notes.

`api_keys`

- Hash key: `api_key_hash_prefix`
- Fields: `key_id`, `tenant_id`, `api_key_hash`, `api_key_hash_prefix`,
  `name`, `status`, `scopes`, `created_at`, `last_used_at`, `disabled_at`.
- Plaintext API keys are never stored. Prefix lookup is only an optimization;
  full hash comparison uses constant-time comparison.

`projects`

- Hash key: `tenant_id`, range key: `sort_key = PROJECT#{project_number}`
- Fields: `project_id`, `project_number`, `project_name`, `description`,
  `status`, `default_storage_mode_override`, timestamps.

`procedure_specs`

- Hash key: `tenant_id`, range key:
  `PROJECT#{project_number}#PROC#{procedure_code}`
- Fields: `procedure_name`, `description`, `status`, `draft_spec`,
  `current_version`, `current_spec_hash`, timestamps.

`procedure_spec_versions`

- Hash key: `tenant_id`, range key:
  `PROJECT#{project_number}#PROC#{procedure_code}#VERSION#{version}`
- Immutable published spec body plus `spec_hash`, `published_at`, and
  `published_by`.

`classification_runs`

- Hash key: `tenant_id`, range key: `RUN#{run_id}`
- Project listing GSI: `project_created_at_index`
- Fields include `project_number`, `procedure_code`, `external_document_id`,
  `file_name`, `document_hash`, `document_storage_uri`, `storage_policy_used`,
  status/result summary, `spec_version`, `spec_hash`, sanitized metadata, and
  timestamps.

`classification_results`

- Hash key: `tenant_id`, range key: `RUN#{run_id}#RESULT`
- Stores sanitized index summaries only. Raw matched text and evidence are not
  stored by default.

`audit_logs`

- Hash key: `tenant_id`, range key: `AUDIT#{created_at}#{request_id}`
- Stores `request_id`, `api_key_id` or hash prefix, project/procedure,
  `document_hash`, action/status, duration, storage policy, error code, and
  timestamp. It must not contain request bodies, raw document text, PDFs,
  evidence, API keys, SQL passwords, or LLM keys.

## Procedure Spec Body

Published specs require a non-empty `indexes` list. Each IDX row needs a unique
`key`, a `label`, supported `output_type`, and array fields must be arrays.
Publishing creates a new immutable version and updates the current pointer on
the spec. Editing an active spec updates only `draft_spec`; old versions remain
retrievable and classification stores the exact `spec_version` and `spec_hash`.

## Tenant Isolation

Every customer route resolves `tenant_id` from the API key. Request bodies are
not trusted for tenancy. Project, spec, run, result, and audit reads/writes are
scoped by `tenant_id`, so one customer cannot load another customer’s project by
guessing `project_number`.
