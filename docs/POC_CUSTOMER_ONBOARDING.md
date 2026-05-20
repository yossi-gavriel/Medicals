# MedicalClassifier + OmniScan POC Customer Onboarding

This runbook covers the Phase 1 AWS Serverless POC:

- API Gateway + Lambda
- DynamoDB on-demand tables
- SSM SecureString reference for the LLM key
- OmniScan installed on the customer Windows/IIS host

Do not put plaintext API keys or LLM provider keys in Terraform variables,
Terraform state, tickets, or logs.

## Internal Cloud Setup

1. Prepare AWS credentials for the company Medicals account/profile.

```bash
export AWS_PROFILE=company-medicals
export AWS_REGION=il-central-1
```

Preflight before any AWS or Terraform action:

```bash
aws sts get-caller-identity --profile company-medicals
```

The returned `Account` must be `106300405464`. Stop if any other account is
returned.

Use `il-central-1` because the workload and customer are in Israel. Before
apply, verify Terraform/provider support for Lambda, API Gateway HTTP API,
DynamoDB, CloudWatch Logs, IAM, SSM Parameter Store, S3 remote state, and
DynamoDB state locking in `il-central-1`. If a required service/resource has a
concrete blocker in `il-central-1`, stop and report the blocker, then use
`eu-central-1` as the fallback. Do not use `eu-west-1` unless a separate
documented reason is approved.

Read-only preflight checks:

```bash
aws lambda get-account-settings --profile company-medicals --region il-central-1
aws apigatewayv2 get-apis --profile company-medicals --region il-central-1 --max-items 1
aws dynamodb list-tables --profile company-medicals --region il-central-1 --max-items 1
aws logs describe-log-groups --profile company-medicals --region il-central-1 --limit 1
aws ssm describe-parameters --profile company-medicals --region il-central-1 --max-items 1
aws iam get-account-summary --profile company-medicals
```

If these fail with `AccessDenied`, fix deployer/OIDC permissions before
planning or applying. If they fail because a required service/resource is not
available in `il-central-1`, stop and use `eu-central-1` as the documented
fallback.

2. Validate Terraform.

```bash
cd infra/serverless
terraform init
terraform fmt -check
terraform validate
terraform plan -refresh=false -input=false
```

3. Apply only after explicit approval.

```bash
terraform apply
```

4. Store the LLM provider key in SSM SecureString outside Terraform state.

```bash
aws ssm put-parameter \
  --name /medicals/medical-classifier/llm-api-key/company-medicals \
  --type SecureString \
  --value '<paste-secret-securely>' \
  --overwrite
```

Then set Terraform variable `medical_classifier_llm_api_key_ssm_parameter_name`
to that parameter name and redeploy after approval.

## First Customer Provisioning

Use `scripts/seed_customer.py` after the DynamoDB tables exist. The script is
idempotent for tenants/projects and stores only API key hashes.

Dry-run first:

```bash
python scripts/seed_customer.py --dry-run onboard-customer \
  --customer-name "Customer A" \
  --license-number "LIC-001" \
  --storage-mode local_only \
  --project-number "10023" \
  --project-name "POC Project" \
  --generate-api-key \
  --create-empty-spec \
  --procedure-code "poc_procedure" \
  --procedure-name "POC Procedure"
```

Provision for real in the approved POC AWS account:

```bash
python scripts/seed_customer.py onboard-customer \
  --customer-name "Customer A" \
  --license-number "LIC-001" \
  --storage-mode local_only \
  --project-number "10023" \
  --project-name "POC Project" \
  --generate-api-key
```

The generated API key is printed once. Store it immediately in the approved
secret-sharing channel. It cannot be recovered from DynamoDB.

Useful individual commands:

```bash
python scripts/seed_customer.py create-tenant \
  --customer-name "Customer A" \
  --license-number "LIC-001" \
  --storage-mode local_only

python scripts/seed_customer.py create-api-key \
  --tenant-id "tenant-customer-a" \
  --key-name "omniscan-poc" \
  --generate-api-key

python scripts/seed_customer.py create-project \
  --tenant-id "tenant-customer-a" \
  --project-number "10023" \
  --project-name "POC Project"

python scripts/seed_customer.py update-storage-policy \
  --tenant-id "tenant-customer-a" \
  --storage-mode hybrid
```

## Customer Handoff

Give the customer:

- OmniScan installer
- API base URL from Terraform output `api_invoke_url`
- API key, shown once during provisioning
- Project number
- Any procedure-code naming guidance

## Customer Install

1. Run the OmniScan installer as Administrator.
2. Open the local OmniScan IIS URL.
3. Go to `System > Onboarding`.
4. Enter API URL and API key.
5. Test backend connection.
6. Load projects and select the provided project.
7. Configure SQL Server/Azure SQL and test connection.
8. Configure PDF/network folder and test access.
9. Open Procedure Specs.
10. Create a structured procedure spec.
11. Save draft.
12. Publish version.
13. Return to Onboarding and submit a non-production test classification.
14. Review result/status.
15. Enable SQL writeback only after customer approval.

## Security Notes

Stored locally in OmniScan:

- API URL
- API key
- SQL connection settings
- PDF folder path
- Selected cloud project number

Stored in our cloud backend:

- Tenant/customer metadata
- API key hash and prefix only
- Projects
- Draft procedure specs
- Immutable published spec versions
- Classification runs
- Sanitized result indexes
- Sanitized audit logs with `document_hash`
- Customer storage policy: `local_only`, `cloud`, or `hybrid`

Not stored by default in cloud:

- Raw document text
- Raw PDF files
- Raw matched text/evidence snippets
- Plaintext API keys
- SQL passwords
- LLM provider plaintext key in Terraform state

`local_only` is the Phase 1 default and is also assumed when older tenant rows
do not have `storage_mode`. `cloud` means the customer allows cloud document
storage. `hybrid` means cloud storage is allowed only when the project/request
opts in. Encrypted S3 document persistence is not enabled in this stack yet, so
the backend currently enforces and records policy but still does not persist raw
document text or PDFs.

## Customer And Project APIs

Clients authenticate with `X-API-Key`; Medicals resolves the tenant from the
API key and never trusts `tenant_id` from the request body.

- `GET /v1/customer/me`
- `PUT /v1/customer/me/storage-policy`
- `GET /v1/projects`
- `POST /v1/projects`
- `GET /v1/projects/{project_number}`
- `PUT /v1/projects/{project_number}`
- `PATCH /v1/projects/{project_number}/storage-policy`

## Procedure Spec APIs

Clients save and fetch procedure specs through Medicals. Customer-specific
procedure specs are not sourced from local JSON files.

- `GET /v1/projects/{project_number}/procedure-specs`
- `POST /v1/projects/{project_number}/procedure-specs`
- `GET /v1/projects/{project_number}/procedure-specs/{procedure_code}`
- `PUT /v1/projects/{project_number}/procedure-specs/{procedure_code}`
- `POST /v1/projects/{project_number}/procedure-specs/{procedure_code}/publish`
- `GET /v1/projects/{project_number}/procedure-specs/{procedure_code}/versions`
- `GET /v1/projects/{project_number}/procedure-specs/{procedure_code}/current`

Classification loads the current active spec version from DynamoDB and stores
the `spec_version` and `spec_hash` on the run/result.

## Rotate Or Disable API Key

To rotate:

1. Generate a new key with `create-api-key`.
2. Give the customer the new key through the approved channel.
3. Update OmniScan.
4. Disable the old key:

```bash
python scripts/seed_customer.py disable-api-key \
  --api-key-hash-prefix "<old-prefix>"
```

To disable customer access, mark all API key rows for that tenant
`status=disabled`.

## Troubleshooting

`invalid_api_key`: verify the customer pasted the full API key and that the
DynamoDB API key row has `status=active`.

`project_not_available_for_api_key`: the selected project is not scoped to the
tenant resolved from the API key.

`current_procedure_spec_not_found`: save and publish a spec for the exact
project number and procedure code.

SQL connection failed: verify server name, auth mode, database name, firewall,
ODBC driver, and IIS app pool identity permissions.

PDF path inaccessible: verify the Windows account running the IIS app pool has
read access to the network share.

Classification failed: check Lambda logs for sanitized error type, confirm the
LLM SSM parameter exists, and confirm Lambda IAM can read it.

LLM secret missing: set the SSM SecureString and configure
`medical_classifier_llm_api_key_ssm_parameter_name`.

API Gateway/Lambda timeout: reduce test document size for POC or raise Lambda
timeout through Terraform within approved limits.

IIS app not starting: check HttpPlatformHandler installation, generated
`web.config`, app-local venv, and `logs\stdout.log`.
