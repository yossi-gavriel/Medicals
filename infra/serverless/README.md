# MedicalClassifier Serverless Deployment

This Terraform module deploys the lightweight MedicalClassifier Lambda handler:

```text
API Gateway HTTP API
-> Lambda dedicated handler
-> DynamoDB customer/project/spec/run/result/audit tables
-> env config / optional SSM SecureString
-> CloudWatch Logs
```

It uses the existing handler:

```text
app.lambda_handlers.medical_classifier_handler.lambda_handler
```

## What This Does

- Exposes the backward-compatible `POST /v1/medical-classifier/classify-document`.
- Exposes customer, project, procedure spec, spec version, and classification
  run routes under `/v1`.
- Keeps compatibility with OmniScan's `X-API-Key` contract.
- Runs the dedicated Lambda handler without importing `app.main` or FastAPI routes.
- Stores tenant/customer metadata, hashed API keys, projects, procedure specs,
  immutable spec versions, sanitized classification runs/results, and sanitized
  audit logs in DynamoDB.
- Creates a Lambda CloudWatch log group with retention.
- Stores API key hashes in Lambda env vars and can mirror them to SSM SecureString.

## What This Does Not Do

- No ECS.
- No RDS.
- No Redis or ElastiCache.
- No ALB.
- No VPC or NAT Gateway.
- No S3.
- No FastAPI deployment.
- No medical text persistence.

Cloud document persistence is not active in this module. `storage_mode` and
`storage_policy_used` are modeled and enforced, but raw document text/PDFs are
not persisted even when policy is `cloud` until an encrypted private S3 bucket,
tenant-scoped keys, lifecycle policy, and least-privilege IAM are added in an
approved change.

The sanitized audit item is intentionally limited to:

```json
{
  "request_id": "...",
  "api_key_hash_prefix": "...",
  "project_number": "...",
  "procedure_code": "...",
  "document_hash": "...",
  "action": "classify_document",
  "status": "success",
  "duration_ms": 42,
  "storage_policy_used": "local_only",
  "created_at": "..."
}
```

Do not add raw document text, `cleaned_full`, `cleaned_desc`, `matched_text`,
`evidence`, raw request bodies, or API keys to logs or DynamoDB.

## Generate an API Key Hash

Use a strong random API key and pass only its SHA-256 hash to Terraform:

```bash
python - <<'PY'
import hashlib
print(hashlib.sha256("YOUR_API_KEY".encode()).hexdigest())
PY
```

Example `terraform.tfvars`:

```hcl
aws_region = "eu-central-1"

api_key_hashes = [
  "REPLACE_WITH_64_CHAR_SHA256_HEX_DIGEST"
]

medical_classifier_llm_provider = "openai"
medical_classifier_llm_model    = "gpt-4o-mini"

# Prefer setting this through your secret workflow.
medical_classifier_llm_api_key = "REPLACE_OUTSIDE_GIT"
```

Do not commit `terraform.tfvars` or any file containing secrets.

Note: Terraform stores managed values in state. The API key values here are
hashes, not plaintext keys, but still treat Terraform state as sensitive. The
LLM API key variable is plaintext if you set it directly; use an encrypted
remote state and your normal secret workflow before production apply.

## Package Lambda

Build the zip before running `terraform plan`:

```bash
./scripts/package_lambda.sh
```

The script installs `requirements.txt` into a clean build directory and copies:

- `app/`
- `data/procedure_definitions/`

The output zip is:

```text
infra/serverless/build/medical-classifier-lambda.zip
```

Build artifacts are ignored by the repo-wide `build/` ignore rule.

The current package uses `requirements.txt` for minimum implementation speed.
That includes dependencies not used by this Lambda path. A later hardening step
can split a smaller Lambda-only requirements file. If package size or native
wheel compatibility becomes painful, consider a Lambda container image, but do
not switch to that without an explicit architecture decision.

## Terraform Commands

Initialize:

```bash
terraform -chdir=infra/serverless init -backend=false
```

Review:

```bash
terraform -chdir=infra/serverless validate
terraform -chdir=infra/serverless plan -refresh=false -input=false
```

Apply only after approval:

```bash
terraform -chdir=infra/serverless apply
```

This task does not run `apply`.

## Find the API URL

After apply, Terraform outputs:

```text
classify_document_url
```

Use that URL as the OmniScan classifier API base/endpoint target depending on
how OmniScan settings are wired.

## OmniScan Settings

Set:

```text
classifier_api_url = <classify_document_url or API base URL>
classifier_api_key = <the plaintext API key whose hash was deployed>
```

The Lambda validates the plaintext `X-API-Key` by hashing it and comparing it
with the configured SHA-256 hashes using constant-time comparison.

## Local Validation

```bash
terraform -chdir=infra/serverless fmt
terraform -chdir=infra/serverless init -backend=false
terraform -chdir=infra/serverless validate
```

No deploy is performed by these commands.
