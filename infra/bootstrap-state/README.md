# MedicalClassifier Terraform State Bootstrap

This optional module creates the remote state foundation for the
MedicalClassifier serverless Terraform stack:

- S3 bucket for Terraform state
- S3 bucket versioning
- S3 server-side encryption
- S3 public access blocking
- DynamoDB table for S3 backend locking

Run this only from an approved AWS account/profile. Do not commit tfvars files,
state files, bucket names, lock table names, or credentials.

## Usage

Choose a globally unique bucket name outside the repo:

```bash
export AWS_PROFILE=customer-poc
export AWS_REGION=eu-central-1
export TF_STATE_BUCKET='<approved-unique-state-bucket-name>'
export TF_STATE_LOCK_TABLE='medical-classifier-terraform-locks'
```

Initialize and review:

```bash
terraform -chdir=infra/bootstrap-state init -backend=false
terraform -chdir=infra/bootstrap-state fmt -check
terraform -chdir=infra/bootstrap-state validate
terraform -chdir=infra/bootstrap-state plan \
  -input=false \
  -var="aws_region=${AWS_REGION}" \
  -var="state_bucket_name=${TF_STATE_BUCKET}" \
  -var="lock_table_name=${TF_STATE_LOCK_TABLE}"
```

Apply only after approval:

```bash
terraform -chdir=infra/bootstrap-state apply \
  -input=false \
  -var="aws_region=${AWS_REGION}" \
  -var="state_bucket_name=${TF_STATE_BUCKET}" \
  -var="lock_table_name=${TF_STATE_LOCK_TABLE}"
```

After this succeeds, configure GitHub:

```text
Variable: TF_STATE_BUCKET     = output state_bucket_name
Variable: TF_STATE_LOCK_TABLE = output lock_table_name
Variable: TF_STATE_KEY        = medical-classifier/serverless/terraform.tfstate
```

The bootstrap module itself intentionally uses local state because it creates
the remote backend. Store any local bootstrap state securely according to the
team's cloud operations process.
