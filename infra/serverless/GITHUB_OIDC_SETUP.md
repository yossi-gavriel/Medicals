# GitHub OIDC Setup For MedicalClassifier Serverless

This runbook prepares GitHub Actions to deploy the MedicalClassifier
serverless stack into the company AWS account.

Do not paste plaintext API keys or LLM provider keys into GitHub variables,
Terraform variables, tickets, or logs.

## Fixed Values

```text
AWS account ID: 106300405464
AWS profile: company-medicals
AWS region: il-central-1
GitHub repo: yossi-gavriel/Medicals
GitHub environment: medicals-serverless-prod
Deploy role name: github-actions-medicals-deploy
Deploy role ARN: arn:aws:iam::106300405464:role/github-actions-medicals-deploy
State bucket: medical-classifier-tfstate-106300405464
State lock table: medical-classifier-terraform-locks
State key: medical-classifier/serverless/terraform.tfstate
```

Preflight:

```bash
aws sts get-caller-identity --profile company-medicals
```

The returned `Account` must be `106300405464`. Stop if any other account is
returned.

## Check Existing AWS OIDC Setup

```bash
aws iam list-open-id-connect-providers --profile company-medicals
aws iam get-role \
  --role-name github-actions-medicals-deploy \
  --profile company-medicals
```

If the provider list does not include
`arn:aws:iam::106300405464:oidc-provider/token.actions.githubusercontent.com`,
create it.

## Create The GitHub OIDC Provider

```bash
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --profile company-medicals
```

If AWS reports that the provider already exists, reuse it.

## Trust Policy

The validate/plan job runs from `main`, and the apply job runs through the
`medicals-serverless-prod` GitHub Environment. The trust policy therefore
allows only this repo's `main` ref and this repo's deployment environment.

Create `/tmp/github-actions-medicals-deploy-trust.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::106300405464:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": [
            "repo:yossi-gavriel/Medicals:ref:refs/heads/main",
            "repo:yossi-gavriel/Medicals:environment:medicals-serverless-prod"
          ]
        }
      }
    }
  ]
}
```

Create or update the role:

```bash
aws iam create-role \
  --role-name github-actions-medicals-deploy \
  --assume-role-policy-document file:///tmp/github-actions-medicals-deploy-trust.json \
  --profile company-medicals
```

If the role already exists, update the trust policy:

```bash
aws iam update-assume-role-policy \
  --role-name github-actions-medicals-deploy \
  --policy-document file:///tmp/github-actions-medicals-deploy-trust.json \
  --profile company-medicals
```

## Deploy Permissions Policy

Create `/tmp/github-actions-medicals-deploy-policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "TerraformStateBucketAccess",
      "Effect": "Allow",
      "Action": [
        "s3:GetBucketLocation",
        "s3:GetBucketVersioning",
        "s3:ListBucket"
      ],
      "Resource": "arn:aws:s3:::medical-classifier-tfstate-106300405464"
    },
    {
      "Sid": "TerraformStateObjectAccess",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject"
      ],
      "Resource": "arn:aws:s3:::medical-classifier-tfstate-106300405464/medical-classifier/serverless/terraform.tfstate"
    },
    {
      "Sid": "TerraformLockTableAccess",
      "Effect": "Allow",
      "Action": [
        "dynamodb:DescribeTable",
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:DeleteItem",
        "dynamodb:UpdateItem"
      ],
      "Resource": "arn:aws:dynamodb:il-central-1:106300405464:table/medical-classifier-terraform-locks"
    },
    {
      "Sid": "ManageMedicalClassifierDynamoTables",
      "Effect": "Allow",
      "Action": [
        "dynamodb:CreateTable",
        "dynamodb:DeleteTable",
        "dynamodb:DescribeContinuousBackups",
        "dynamodb:DescribeTable",
        "dynamodb:DescribeTimeToLive",
        "dynamodb:ListTagsOfResource",
        "dynamodb:TagResource",
        "dynamodb:UntagResource",
        "dynamodb:UpdateContinuousBackups",
        "dynamodb:UpdateTable",
        "dynamodb:UpdateTimeToLive"
      ],
      "Resource": [
        "arn:aws:dynamodb:il-central-1:106300405464:table/medicalclassifier-tenants",
        "arn:aws:dynamodb:il-central-1:106300405464:table/medicalclassifier-api-keys",
        "arn:aws:dynamodb:il-central-1:106300405464:table/medicalclassifier-projects",
        "arn:aws:dynamodb:il-central-1:106300405464:table/medicalclassifier-procedure-specs",
        "arn:aws:dynamodb:il-central-1:106300405464:table/medicalclassifier-procedure-spec-versions",
        "arn:aws:dynamodb:il-central-1:106300405464:table/medicalclassifier-classification-runs",
        "arn:aws:dynamodb:il-central-1:106300405464:table/medicalclassifier-classification-runs/index/*",
        "arn:aws:dynamodb:il-central-1:106300405464:table/medicalclassifier-classification-results",
        "arn:aws:dynamodb:il-central-1:106300405464:table/medicalclassifier-audit-logs"
      ]
    },
    {
      "Sid": "ListDynamoTablesForProvider",
      "Effect": "Allow",
      "Action": "dynamodb:ListTables",
      "Resource": "*"
    },
    {
      "Sid": "ManageMedicalClassifierLambda",
      "Effect": "Allow",
      "Action": [
        "lambda:AddPermission",
        "lambda:CreateFunction",
        "lambda:DeleteFunction",
        "lambda:GetFunction",
        "lambda:GetFunctionConfiguration",
        "lambda:GetPolicy",
        "lambda:ListTags",
        "lambda:RemovePermission",
        "lambda:TagResource",
        "lambda:UntagResource",
        "lambda:UpdateFunctionCode",
        "lambda:UpdateFunctionConfiguration"
      ],
      "Resource": "arn:aws:lambda:il-central-1:106300405464:function:medical-classifier-serverless"
    },
    {
      "Sid": "ManageMedicalClassifierApiGateway",
      "Effect": "Allow",
      "Action": [
        "apigateway:DELETE",
        "apigateway:GET",
        "apigateway:PATCH",
        "apigateway:POST",
        "apigateway:PUT",
        "apigateway:TagResource",
        "apigateway:UntagResource"
      ],
      "Resource": [
        "arn:aws:apigateway:il-central-1::/apis",
        "arn:aws:apigateway:il-central-1::/apis/*"
      ]
    },
    {
      "Sid": "ManageMedicalClassifierLambdaRole",
      "Effect": "Allow",
      "Action": [
        "iam:CreateRole",
        "iam:DeleteRole",
        "iam:DeleteRolePolicy",
        "iam:GetRole",
        "iam:GetRolePolicy",
        "iam:ListAttachedRolePolicies",
        "iam:ListInstanceProfilesForRole",
        "iam:ListRolePolicies",
        "iam:PutRolePolicy",
        "iam:TagRole",
        "iam:UntagRole",
        "iam:UpdateAssumeRolePolicy"
      ],
      "Resource": "arn:aws:iam::106300405464:role/medical-classifier-serverless-role"
    },
    {
      "Sid": "PassMedicalClassifierLambdaRole",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": "arn:aws:iam::106300405464:role/medical-classifier-serverless-role",
      "Condition": {
        "StringEquals": {
          "iam:PassedToService": "lambda.amazonaws.com"
        }
      }
    },
    {
      "Sid": "ManageMedicalClassifierLogGroup",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:DeleteLogGroup",
        "logs:ListTagsForResource",
        "logs:PutRetentionPolicy",
        "logs:TagResource",
        "logs:UntagResource"
      ],
      "Resource": [
        "arn:aws:logs:il-central-1:106300405464:log-group:/aws/lambda/medical-classifier-serverless",
        "arn:aws:logs:il-central-1:106300405464:log-group:/aws/lambda/medical-classifier-serverless:*"
      ]
    },
    {
      "Sid": "ReadCloudWatchLogsForProvider",
      "Effect": "Allow",
      "Action": "logs:DescribeLogGroups",
      "Resource": "*"
    },
    {
      "Sid": "ManageMedicalClassifierCloudWatchAlarm",
      "Effect": "Allow",
      "Action": [
        "cloudwatch:DeleteAlarms",
        "cloudwatch:DescribeAlarms",
        "cloudwatch:ListTagsForResource",
        "cloudwatch:PutMetricAlarm",
        "cloudwatch:TagResource",
        "cloudwatch:UntagResource"
      ],
      "Resource": "*"
    },
    {
      "Sid": "ManageMedicalClassifierApiKeyHashParameter",
      "Effect": "Allow",
      "Action": [
        "ssm:AddTagsToResource",
        "ssm:DeleteParameter",
        "ssm:GetParameter",
        "ssm:GetParameters",
        "ssm:ListTagsForResource",
        "ssm:PutParameter",
        "ssm:RemoveTagsFromResource"
      ],
      "Resource": "arn:aws:ssm:il-central-1:106300405464:parameter/medicals/medical-classifier/api-key-hashes"
    },
    {
      "Sid": "ReadSsmParametersForProvider",
      "Effect": "Allow",
      "Action": "ssm:DescribeParameters",
      "Resource": "*"
    }
  ]
}
```

Attach it as an inline role policy:

```bash
aws iam put-role-policy \
  --role-name github-actions-medicals-deploy \
  --policy-name medical-classifier-serverless-deploy \
  --policy-document file:///tmp/github-actions-medicals-deploy-policy.json \
  --profile company-medicals
```

If this constrained policy blocks the first Terraform plan because the AWS
provider needs an additional read action, add the specific missing action and
resource from the AccessDenied message. As a temporary break-glass alternative,
attach `AdministratorAccess` only for the initial deployment, require
environment approval, then replace it with a constrained policy immediately
after the missing actions are known.

## GitHub Repository Setup

Create the Environment:

```text
medicals-serverless-prod
```

Configure required reviewers on that environment.

Repository variables:

```text
AWS_REGION=il-central-1
TF_STATE_BUCKET=medical-classifier-tfstate-106300405464
TF_STATE_LOCK_TABLE=medical-classifier-terraform-locks
TF_STATE_KEY=medical-classifier/serverless/terraform.tfstate
TF_VAR_MEDICAL_CLASSIFIER_LLM_PROVIDER=disabled
TF_VAR_MEDICAL_CLASSIFIER_LLM_MODEL=
TF_VAR_MEDICAL_CLASSIFIER_LLM_API_KEY_SSM_PARAMETER_NAME=
```

Repository secrets:

```text
AWS_ROLE_TO_ASSUME=arn:aws:iam::106300405464:role/github-actions-medicals-deploy
TF_VAR_API_KEY_HASHES=["<sha256-api-key-hash>"]
```

`TF_VAR_API_KEY_HASHES` must contain only hashes, never plaintext API keys.

## API Key Hash Flow

Use `getpass` so the plaintext key is not echoed:

```bash
python - <<'PY'
import hashlib
from getpass import getpass

api_key = getpass("API key: ")
print(hashlib.sha256(api_key.encode()).hexdigest())
PY
```

Store the plaintext key only in the approved secret channel. Paste only the
hash into `TF_VAR_API_KEY_HASHES`, wrapped as a Terraform list string.

## LLM Configuration

`medical_classifier_llm_provider` defaults to `disabled`, and the Terraform
module supports deploying with the LLM disabled. Use
`TF_VAR_MEDICAL_CLASSIFIER_LLM_PROVIDER=disabled` for the first Constitution
import smoke deployment unless document classification with live LLM reasoning
is required immediately.

If enabling an LLM provider, set:

```text
TF_VAR_MEDICAL_CLASSIFIER_LLM_PROVIDER=<provider>
TF_VAR_MEDICAL_CLASSIFIER_LLM_MODEL=<model>
TF_VAR_MEDICAL_CLASSIFIER_LLM_API_KEY_SSM_PARAMETER_NAME=<existing-securestring-parameter-name>
```

Do not store the plaintext LLM API key in Terraform variables or GitHub Actions
variables.

## Next Step

After the role, environment, variables, and secrets are configured, run:

```text
Actions -> Deploy MedicalClassifier Serverless -> Run workflow
apply=false
```

Review the plan. Run `apply=true` only after the plan is accepted and the
`medicals-serverless-prod` environment approval is ready.
