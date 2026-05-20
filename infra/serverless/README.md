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

## Account And Region

Use the company AWS account:

```text
AWS account ID: 106300405464
AWS profile: company-medicals
Preferred AWS region: il-central-1
Fallback AWS region: eu-central-1
```

Preflight before any AWS or Terraform action:

```bash
aws sts get-caller-identity --profile company-medicals
```

The returned `Account` must be `106300405464`. Stop if any other account is
returned.

Use `il-central-1` because the workload and customer are in Israel. Before
apply, verify Terraform/provider support for the required stack services in
`il-central-1`: Lambda, API Gateway HTTP API, DynamoDB, CloudWatch Logs, IAM,
SSM Parameter Store, S3 remote state, and DynamoDB state locking. If a required
service/resource has a concrete blocker in `il-central-1`, stop and report the
blocker, then use `eu-central-1` as the fallback. Do not use `eu-west-1` unless
there is a separate documented reason.

Read-only regional preflight checks, run before any apply:

```bash
aws lambda get-account-settings --profile company-medicals --region il-central-1
aws apigatewayv2 get-apis --profile company-medicals --region il-central-1 --max-items 1
aws dynamodb list-tables --profile company-medicals --region il-central-1 --max-items 1
aws logs describe-log-groups --profile company-medicals --region il-central-1 --limit 1
aws ssm describe-parameters --profile company-medicals --region il-central-1 --max-items 1
aws iam get-account-summary --profile company-medicals
```

These checks must succeed or fail only because resources do not exist yet. If
they fail with `AccessDenied`, fix the deployer/OIDC role permissions before
planning or applying. If they fail because a service or Terraform provider
resource is unavailable in `il-central-1`, stop and use `eu-central-1` as the
documented fallback.

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
aws_region = "il-central-1"

api_key_hashes = [
  "REPLACE_WITH_64_CHAR_SHA256_HEX_DIGEST"
]

medical_classifier_llm_provider = "openai"
medical_classifier_llm_model    = "gpt-4o-mini"

# Prefer an SSM SecureString created outside Terraform state.
medical_classifier_llm_api_key_ssm_parameter_name = "/medicals/medical-classifier/llm-api-key/company-medicals"
```

Do not commit `terraform.tfvars` or any file containing secrets.

Note: Terraform stores managed values in state. The API key values here are
hashes, not plaintext keys, but still treat Terraform state as sensitive. The
LLM API key should live in SSM SecureString and be referenced by parameter name;
use an encrypted remote state and your normal secret workflow before production
apply.

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

## GitHub Actions Deployment

The workflow
`.github/workflows/deploy-medical-classifier-serverless.yml` automates the
safe parts of this flow:

- On pushes to `main` that touch MedicalClassifier/serverless files, it runs
  focused tests, focused Ruff checks, packages the Lambda, runs Terraform
  `fmt`, remote-backend `init`, `validate`, and `plan`. Pushes never apply.
- On `workflow_dispatch`, it runs the same validation and planning. If the
  `apply` input is `true`, the apply job waits for the GitHub Environment
  `medicals-serverless-prod` before running a fresh `terraform plan -out=tfplan`
  and `terraform apply`.
- The apply job prints Terraform outputs `api_invoke_url` and
  `classify_document_url`. It does not print API keys or plaintext secrets.
- Binary Terraform plan files are not uploaded as artifacts because plan files
  can contain sensitive values. The apply job re-plans after environment
  approval.

Create the GitHub Environment `medicals-serverless-prod` and configure required
reviewers before enabling production applies.

Required GitHub repository configuration:

```text
Variable: AWS_REGION                                # il-central-1 preferred; eu-central-1 approved fallback
Variable: TF_STATE_BUCKET
Variable: TF_STATE_LOCK_TABLE
Variable: TF_STATE_KEY                                # optional; defaults to medical-classifier/serverless/terraform.tfstate
Secret:   AWS_ROLE_TO_ASSUME
Secret:   MEDICAL_CLASSIFIER_API_KEY_HASHES
Variable: MEDICAL_CLASSIFIER_LLM_PROVIDER
Variable: MEDICAL_CLASSIFIER_LLM_MODEL                # required when provider is not disabled
Variable: MEDICAL_CLASSIFIER_LLM_API_KEY_SSM_PARAMETER_NAME
```

`MEDICAL_CLASSIFIER_API_KEY_HASHES` must be a Terraform-compatible list value,
for example `["<64-char-sha256-hex>"]`. Store only hashes there, never
plaintext API keys. The workflow maps these GitHub names to the corresponding
`TF_VAR_*` environment variables internally before running Terraform. The
plaintext API key is generated during customer provisioning and shared only
through the approved secret channel.

The workflow uses GitHub OIDC through `aws-actions/configure-aws-credentials`.
The assumed IAM role must be allowed to manage the resources in this module and
to read/write the Terraform state bucket and lock table. The workflow pins the
allowed AWS account to `106300405464` and rejects `eu-west-1`; set
`AWS_REGION=il-central-1` unless a documented service blocker requires
`eu-central-1`.

See `GITHUB_OIDC_SETUP.md` for the exact OIDC provider, deploy role trust
policy, deploy permissions policy, and GitHub repository setup steps.

## Remote State

The serverless module uses an S3 backend configured at init time. The backend
block intentionally has no hardcoded private bucket names:

```hcl
terraform {
  backend "s3" {}
}
```

Production init requires backend config:

```bash
terraform -chdir=infra/serverless init \
  -backend-config="bucket=${TF_STATE_BUCKET}" \
  -backend-config="key=${TF_STATE_KEY:-medical-classifier/serverless/terraform.tfstate}" \
  -backend-config="region=${AWS_REGION}" \
  -backend-config="dynamodb_table=${TF_STATE_LOCK_TABLE}" \
  -backend-config="encrypt=true"
```

Expected backend settings:

```text
TF_STATE_BUCKET      = approved existing S3 state bucket
TF_STATE_LOCK_TABLE  = approved existing DynamoDB lock table
TF_STATE_KEY         = medical-classifier/serverless/terraform.tfstate
```

The S3 bucket must have versioning enabled, server-side encryption enabled, and
public access blocked. The DynamoDB lock table must have a string hash key named
`LockID`.

If these resources do not exist yet, bootstrap them first using
`infra/bootstrap-state`. Do not run production applies from GitHub Actions until
remote state exists and the GitHub variables above are configured.

Bootstrap review:

```bash
terraform -chdir=infra/bootstrap-state init -backend=false
terraform -chdir=infra/bootstrap-state plan \
  -input=false \
  -var="aws_region=${AWS_REGION}" \
  -var="state_bucket_name=${TF_STATE_BUCKET}" \
  -var="lock_table_name=${TF_STATE_LOCK_TABLE}"
```

Bootstrap apply only after cloud approval:

```bash
terraform -chdir=infra/bootstrap-state apply \
  -input=false \
  -var="aws_region=${AWS_REGION}" \
  -var="state_bucket_name=${TF_STATE_BUCKET}" \
  -var="lock_table_name=${TF_STATE_LOCK_TABLE}"
```

The bootstrap module itself uses local state because it creates the remote state
foundation. Store that one-time bootstrap state according to the team's cloud
operations process.

## Terraform Commands

For local syntax validation without cloud state:

```bash
terraform -chdir=infra/serverless init -backend=false
terraform -chdir=infra/serverless validate
```

For deployment review with remote state:

```bash
terraform -chdir=infra/serverless init \
  -backend-config="bucket=${TF_STATE_BUCKET}" \
  -backend-config="key=${TF_STATE_KEY:-medical-classifier/serverless/terraform.tfstate}" \
  -backend-config="region=${AWS_REGION}" \
  -backend-config="dynamodb_table=${TF_STATE_LOCK_TABLE}" \
  -backend-config="encrypt=true"
terraform -chdir=infra/serverless validate
terraform -chdir=infra/serverless plan -refresh=false -input=false
```

Apply only after explicit approval:

```bash
terraform -chdir=infra/serverless apply
```

## Find the API URL

After apply, Terraform outputs:

```text
api_invoke_url
classify_document_url
```

Use `api_invoke_url` as the OmniScan classifier API base URL, meaning the value
before `/v1`. `classify_document_url` is the full classification endpoint and is
not the Constitution import base URL.

## OmniScan Settings

Set:

```text
classifier_api_url = <api_invoke_url, before /v1>
classifier_api_key = <the plaintext API key whose hash was deployed>
```

The Lambda validates the plaintext `X-API-Key` by hashing it and comparing it
with the configured SHA-256 hashes using constant-time comparison.

For an OmniScan smoke test, give Ofir:

```text
base URL: api_invoke_url, before /v1
API key: plaintext customer key through the approved secret channel, redacted in tickets/logs
project_number: the exact project_number provisioned for the customer project
```

OmniScan should then set:

```text
Settings -> Classifier API -> Constitution API URL = base URL
Settings -> Classifier API -> API key = plaintext API key
Projects -> Edit target project -> ExternalProjectCode = project_number
```

The subject must have a `SubjectManagement.TreatmentCode` row, or the operator
must enter `procedure_code` manually in the Run Constitution prompt.

## Customer Provisioning

Generate the customer API key once before deployment, hash it for Terraform, and
store the plaintext only in the approved secret channel:

```bash
python - <<'PY'
import hashlib
from getpass import getpass

api_key = getpass("Paste generated customer API key: ")
print(hashlib.sha256(api_key.encode()).hexdigest())
PY
```

Set the hash in GitHub as `MEDICAL_CLASSIFIER_API_KEY_HASHES`, formatted as a
Terraform list such as `["<64-char-sha256-hex>"]`. Do not put the plaintext key
in GitHub Actions variables, Terraform variables, tickets, or logs.

After the serverless stack exists, use `scripts/seed_customer.py` to create or
confirm the tenant, DynamoDB API key hash record, and project. Prefer
`--prompt-api-key` so the plaintext key is not stored in shell history.

Dry-run first:

```bash
python scripts/seed_customer.py --dry-run onboard-customer \
  --customer-name "Customer A" \
  --license-number "LIC-001" \
  --storage-mode local_only \
  --project-number "10023" \
  --project-name "POC Project" \
  --prompt-api-key
```

Provision after approval:

```bash
python scripts/seed_customer.py onboard-customer \
  --customer-name "Customer A" \
  --license-number "LIC-001" \
  --storage-mode local_only \
  --project-number "10023" \
  --project-name "POC Project" \
  --prompt-api-key
```

The `project_number` argument is the exact value that OmniScan should store as
`ExternalProjectCode`. The prompted plaintext API key is what OmniScan sends as
`X-API-Key`; DynamoDB stores only its hash and prefix.

## Local Validation

```bash
terraform -chdir=infra/serverless fmt
terraform -chdir=infra/serverless init -backend=false
terraform -chdir=infra/serverless validate
```

No deploy is performed by these commands.
