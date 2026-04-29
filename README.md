# Medical Treatment Compliance & Reimbursement Audit Platform

Production-grade FastAPI backend for operational medical audit and reimbursement workflows:

1. **Drug Safety Engine** — real-time prescription safety checking against a patient's active medications.
2. **Medical Extraction Engine** — JSON-spec-driven extraction of typed values (boolean / enum / date / number / text) from medical documents, producing a flat treatment-code table and a separate audit trail.
3. **Compliance & Reimbursement Audit Layer** — compares extracted treatment facts against predefined treatment criteria, identifies non-compliant billed treatments, and creates evidence-backed reimbursement cases.

The platform reads hospitalization documents, extracts structured treatment-level facts, compares performed treatments against predefined specifications, detects mismatches, and gives management visibility by customer, treatment, document, rule, and reimbursement status. It is not a generic AI classifier and does not replace clinical judgment.

Hebrew concept: מערכת בקרת התאמה והחזרים על טיפולים רפואיים לפי מסמכי אשפוז.

The product layers share the FastAPI app, settings, and LLM configuration but preserve independent flows. See [PRODUCT_OVERVIEW.md](PRODUCT_OVERVIEW.md) for the long form.

## Stack
- Python 3.11
- FastAPI
- Pydantic v2
- SQLAlchemy 2.0
- PostgreSQL
- Redis
- Alembic
- pytest

## Features
- Real-time interaction checks with strategy:
  1. Redis cache
  2. Local in-memory interaction graph (O(1) adjacency lookup)
  3. Local DB interaction table
  4. External providers (configurable, queried in parallel)
  5. Persist + cache + graph update
- Severity classes `A/B/C/D/X`, returns physician-facing issues for `C/D/X`
- Provider aggregation selects the highest-severity result and breaks ties by configurable provider priority
- Multi-drug checks:
  - `new_drugs` vs current medications
  - `new_drugs` vs `new_drugs`
- Drug normalization layer (synonyms -> canonical drug)
- ATC resolution chain: local DB -> RxNorm -> DrugBank fallback -> local cache
- Deterministic clinical explanations
- Safer alternatives ranked by interaction profile, subclass match, Israeli basket status, and risk profile
- Daily Israeli basket sync loop + manual sync script
- Local Israeli basket dataset fallback when no external API is configured
- Structured JSON logging
- Retry logic for external APIs
- Compliance rules in the JSON specification with V1 operators: `equals`, `not_equals`, `in`, `not_in`, `gt`, `gte`, `lt`, `lte`, `exists`, `missing`
- Durable compliance results, rule-level evidence, and draft reimbursement cases
- Tenant-scoped customer dashboard APIs and internal admin dashboard APIs

## Project layout
Matches requested structure under `app/`, `scripts/`, and `tests/`.

## Installation
```bash
pip install -r requirements.txt
```

## Configuration
Use environment variables (optional):

- `DATABASE_URL` (default: `postgresql+asyncpg://postgres:postgres@localhost:5432/drug_safety`)
- `REDIS_URL` (default: `redis://localhost:6379/0`)
- `ENABLED_PROVIDERS` (comma-separated, default: `lexicomp,micromedex,drugbank`)
- `PROVIDER_PRIORITY` (comma-separated priority for tie-breaking, default: `lexicomp,micromedex,drugbank,first_databank,uptodate,dynamed`)
- `LEXICOMP_API_URL`, `LEXICOMP_API_KEY`
- `MICROMEDEX_API_URL`, `MICROMEDEX_API_KEY`
- `DRUGBANK_API_URL`, `DRUGBANK_API_KEY`
- `FIRST_DATABANK_API_URL`, `FIRST_DATABANK_API_KEY`
- `UPTODATE_API_URL`, `UPTODATE_API_KEY`
- `DYNAMED_API_URL`, `DYNAMED_API_KEY`
- `ISRAEL_BASKET_API_URL`, `ISRAEL_BASKET_API_KEY`
- `ISRAEL_BASKET_DATASET_PATH` (default: `data/israel_drug_basket.json`)
- `RXNORM_API_URL`

Notes:
- UpToDate and DynaMed adapters are placeholder future adapters and are disabled by default.
- Primary production providers are Lexicomp, Micromedex, and DrugBank. First Databank is an optional placeholder adapter.

## Database migration
```bash
alembic upgrade head
```

## Seed demo data
```bash
python -m scripts.seed_drugs
python -m scripts.seed_synonyms
```

## Warm interaction graph
```bash
python -m scripts.build_interaction_graph
```

## Run
```bash
uvicorn app.main:app --reload
```

## API
### `POST /check-prescription-safety`
Request:
```json
{
  "patient_id": "123",
  "new_drugs": ["asa"],
  "new_medications": [
    {
      "drug": "metformin",
      "dose": "500",
      "unit": "mg",
      "frequency": "bid"
    }
  ]
}
```

Response:
```json
{
  "safe": false,
  "issues": [
    {
      "drug": "aspirin",
      "conflicts_with": "warfarin",
      "severity": "D",
      "risk": "increased bleeding",
      "recommendation": "Avoid routine combination or use strict INR and bleeding monitoring",
      "source": "Lexicomp",
      "explanation": "Aspirin combined with Warfarin is generally discouraged because it can increase the risk of increased bleeding."
    }
  ],
  "suggested_alternatives": [
    {
      "drug": "clopidogrel",
      "reason": "same therapeutic class",
      "interaction_risk": "none detected"
    }
  ]
}
```

### `POST /v1/extractions/run`
Runs the Medical Extraction Engine against a single document. The request body carries the JSON specification — the engine never invents fields beyond what the spec declares.

Request:
```json
{
  "document_id": "doc_123",
  "document_text": "Patient diagnosed with cataract. Surgery date: 10/02/2024. Left eye operated.",
  "metadata": {
    "patient_id": "patient_1",
    "claim_id": "claim_1",
    "provider_name": "Example Hospital",
    "billed_amount": 1234.56,
    "currency": "ILS"
  },
  "spec": {
    "version": "1.0",
    "treatments": [
      {
        "treatment_code": "CATARACT_SURGERY",
        "rules": [
          {
            "field_name": "has_cataract_diagnosis",
            "type": "boolean",
            "positive_indicators": ["cataract", "קטרקט"],
            "negative_indicators": ["no cataract", "ללא קטרקט"],
            "default_when_missing": false
          },
          { "field_name": "surgery_date", "type": "date" },
          {
            "field_name": "operated_eye",
            "type": "enum",
            "allowed_values": ["left", "right", "both", "unknown"]
          }
        ],
        "compliance_rules": [
          {
            "rule_id": "requires_cataract_diagnosis",
            "description": "Treatment requires cataract diagnosis",
            "field": "has_cataract_diagnosis",
            "operator": "equals",
            "value": true,
            "severity": "high",
            "on_fail": {
              "status": "non_compliant",
              "reason": "Cataract diagnosis was not documented",
              "recommended_action": "request_reimbursement"
            }
          }
        ]
      }
    ]
  }
}
```

Response:
```json
{
  "document_id": "doc_123",
  "spec_version": "1.0",
  "rows": [
    {
      "document_id": "doc_123",
      "treatment_code": "CATARACT_SURGERY",
      "has_cataract_diagnosis": true,
      "surgery_date": "2024-02-10",
      "operated_eye": "left"
    }
  ],
  "audit": [
    {
      "document_id": "doc_123",
      "treatment_code": "CATARACT_SURGERY",
      "field_name": "has_cataract_diagnosis",
      "value": true,
      "confidence": 0.9,
      "evidence": ["Patient diagnosed with cataract."],
      "reason": "Matched positive indicator(s): cataract"
    }
  ],
  "compliance": [
    {
      "document_id": "doc_123",
      "treatment_code": "CATARACT_SURGERY",
      "status": "compliant",
      "recommended_action": "none",
      "failed_rules": [],
      "passed_rules": [
        {
          "rule_id": "requires_cataract_diagnosis",
          "description": "Treatment requires cataract diagnosis",
          "field": "has_cataract_diagnosis",
          "operator": "equals",
          "expected": true,
          "actual": true,
          "severity": "high",
          "reason": "Rule passed",
          "recommended_action": "none",
          "evidence": ["Patient diagnosed with cataract."]
        }
      ],
      "insufficient_data_rules": [],
      "manual_review_rules": []
    }
  ],
  "masked": false,
  "pii_masked_count": 0
}
```

Behavior contract:
- One output row per `(document_id, treatment_code)`. Each configured rule becomes a column.
- `audit` carries `value`, `confidence`, `evidence`, `reason` per `(treatment, field)` separately from the flat row.
- Deterministic indicator/regex matching runs first; the LLM resolver is a fallback (and is disabled unless configured).
- Missing values respect `default_when_missing` per rule, otherwise return `null`.
- Hebrew indicators work the same way as English (Unicode substring match, case-insensitive).
- Compliance rules may only reference fields declared in the same treatment's extraction rules; invalid references are rejected with `422`.
- Non-compliant results with `recommended_action=request_reimbursement` create an internal draft reimbursement case. No external email, SMS, or webhook is sent by this layer.
- An example specification is at `data/extraction_specs/cataract_surgery.json`.

### Dashboard APIs

Customer endpoints always filter by the tenant resolved from the authenticated API key and ignore client-supplied tenant IDs:

- `GET /v1/dashboard/summary`
- `GET /v1/dashboard/treatments`
- `GET /v1/dashboard/rules`
- `GET /v1/dashboard/documents/timeseries`
- `GET /v1/dashboard/reimbursement-cases`
- `GET /v1/dashboard/reimbursement-cases/{case_id}`
- `PATCH /v1/dashboard/reimbursement-cases/{case_id}`

Admin endpoints require the internal API key dependency and may filter by `tenant_id`:

- `GET /v1/admin/dashboard/summary`
- `GET /v1/admin/dashboard/tenants`
- `GET /v1/admin/dashboard/tenants/{tenant_id}/summary`
- `GET /v1/admin/dashboard/treatments`
- `GET /v1/admin/dashboard/reimbursement-cases`
- `GET /v1/admin/dashboard/reimbursement-cases/{case_id}`
- `PATCH /v1/admin/dashboard/reimbursement-cases/{case_id}`

Common filters: `date_from`, `date_to`, `tenant_id` for admin only, `treatment_code`, `status`, `recommended_action`, `limit`, `offset`.

Reimbursement case updates accept `status`, `note`, `estimated_amount`, and `currency`. Status changes are validated against the lifecycle matrix, and every creation/status/note/amount change is stored in `reimbursement_case_events`.

## Tests
```bash
pytest
```
