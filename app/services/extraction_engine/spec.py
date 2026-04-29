from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RuleType = Literal["boolean", "enum", "date", "number", "text"]
ComplianceOperator = Literal[
    "equals",
    "not_equals",
    "in",
    "not_in",
    "gt",
    "gte",
    "lt",
    "lte",
    "exists",
    "missing",
]
ComplianceVerdict = Literal["compliant", "non_compliant", "insufficient_data", "manual_review"]
RecommendedAction = Literal[
    "none",
    "request_reimbursement",
    "request_clarification",
    "manual_review",
    "reject_case",
]
Severity = Literal["low", "medium", "high", "critical"]

ALLOWED_RULE_TYPES: tuple[str, ...] = ("boolean", "enum", "date", "number", "text")
OPERATORS_REQUIRING_VALUE = {
    "equals",
    "not_equals",
    "in",
    "not_in",
    "gt",
    "gte",
    "lt",
    "lte",
}


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_name: str = Field(min_length=1, max_length=128)
    type: RuleType
    description: str = ""
    positive_indicators: list[str] = Field(default_factory=list)
    negative_indicators: list[str] = Field(default_factory=list)
    planning_indicators: list[str] = Field(default_factory=list)
    historical_indicators: list[str] = Field(default_factory=list)
    allow_planned_mentions: bool = False
    allow_historical_mentions: bool = False
    allowed_values: list[str] | None = None
    pattern: str | None = None
    evidence_required: bool = False
    default_when_missing: Any = None

    @model_validator(mode="after")
    def _validate(self) -> Rule:
        self.field_name = self.field_name.strip()
        if not self.field_name:
            raise ValueError("field_name must not be blank")
        self.positive_indicators = [s.strip() for s in self.positive_indicators if s and s.strip()]
        self.negative_indicators = [s.strip() for s in self.negative_indicators if s and s.strip()]
        self.planning_indicators = [s.strip() for s in self.planning_indicators if s and s.strip()]
        self.historical_indicators = [s.strip() for s in self.historical_indicators if s and s.strip()]

        if self.type == "enum":
            if not self.allowed_values:
                raise ValueError(
                    f"Rule '{self.field_name}' has type 'enum' and must declare allowed_values"
                )
            cleaned: list[str] = []
            for value in self.allowed_values:
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(
                        f"Rule '{self.field_name}' has an empty value in allowed_values"
                    )
                cleaned.append(value.strip())
            if len(cleaned) != len(set(cleaned)):
                raise ValueError(
                    f"Rule '{self.field_name}' has duplicate values in allowed_values"
                )
            self.allowed_values = cleaned
        elif self.allowed_values is not None:
            raise ValueError(
                f"Rule '{self.field_name}' has type '{self.type}' and must not declare allowed_values"
            )

        self._validate_default()
        return self

    def _validate_default(self) -> None:
        default = self.default_when_missing
        if default is None:
            return
        if self.type == "boolean":
            if not isinstance(default, bool):
                raise ValueError(
                    f"Rule '{self.field_name}' default_when_missing must be a boolean for type 'boolean'"
                )
        elif self.type == "enum":
            allowed = self.allowed_values or []
            if not isinstance(default, str) or default not in allowed:
                raise ValueError(
                    f"Rule '{self.field_name}' default_when_missing must be one of allowed_values"
                )
        elif self.type == "number":
            if not isinstance(default, (int, float)) or isinstance(default, bool):
                raise ValueError(
                    f"Rule '{self.field_name}' default_when_missing must be a number for type 'number'"
                )
        elif self.type == "date" and not isinstance(default, str):
            raise ValueError(
                f"Rule '{self.field_name}' default_when_missing must be an ISO date string for type 'date'"
            )
        elif self.type == "text" and not isinstance(default, str):
            raise ValueError(
                f"Rule '{self.field_name}' default_when_missing must be a string for type 'text'"
            )


class ComplianceRuleOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ComplianceVerdict = "non_compliant"
    reason: str = ""
    recommended_action: RecommendedAction = "none"

    @model_validator(mode="after")
    def _normalize(self) -> ComplianceRuleOutcome:
        self.reason = self.reason.strip()
        return self


class ComplianceRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(min_length=1, max_length=128)
    description: str = ""
    field: str = Field(min_length=1, max_length=128)
    operator: ComplianceOperator
    value: Any = None
    severity: Severity = "medium"
    required: bool = True
    on_fail: ComplianceRuleOutcome = Field(default_factory=ComplianceRuleOutcome)
    on_missing: ComplianceRuleOutcome | None = None

    @model_validator(mode="after")
    def _validate(self) -> ComplianceRule:
        self.rule_id = self.rule_id.strip()
        self.field = self.field.strip()
        self.description = self.description.strip()
        if not self.rule_id:
            raise ValueError("compliance rule_id must not be blank")
        if not self.field:
            raise ValueError(f"Compliance rule '{self.rule_id}' field must not be blank")
        if self.operator in OPERATORS_REQUIRING_VALUE and self.value is None:
            raise ValueError(
                f"Compliance rule '{self.rule_id}' operator '{self.operator}' requires value"
            )
        if self.operator in {"in", "not_in"} and not isinstance(self.value, list):
            raise ValueError(
                f"Compliance rule '{self.rule_id}' operator '{self.operator}' requires list value"
            )
        if self.operator in {"exists", "missing"} and self.value is not None:
            raise ValueError(
                f"Compliance rule '{self.rule_id}' operator '{self.operator}' must not declare value"
            )
        return self


class Treatment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    treatment_code: str = Field(min_length=1, max_length=128)
    display_name: str = ""
    rules: list[Rule]
    compliance_rules: list[ComplianceRule] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate(self) -> Treatment:
        self.treatment_code = self.treatment_code.strip()
        if not self.treatment_code:
            raise ValueError("treatment_code must not be blank")
        if not self.rules:
            raise ValueError(f"Treatment '{self.treatment_code}' has no rules")

        seen_fields: set[str] = set()
        for rule in self.rules:
            if rule.field_name in seen_fields:
                raise ValueError(
                    f"Duplicate field_name '{rule.field_name}' in treatment '{self.treatment_code}'"
                )
            seen_fields.add(rule.field_name)

        seen_compliance_rules: set[str] = set()
        for compliance_rule in self.compliance_rules:
            if compliance_rule.rule_id in seen_compliance_rules:
                raise ValueError(
                    f"Duplicate compliance rule_id '{compliance_rule.rule_id}' "
                    f"in treatment '{self.treatment_code}'"
                )
            seen_compliance_rules.add(compliance_rule.rule_id)
            if compliance_rule.field not in seen_fields:
                raise ValueError(
                    f"Compliance rule '{compliance_rule.rule_id}' references undefined field "
                    f"'{compliance_rule.field}' in treatment '{self.treatment_code}'"
                )
        return self


class Specification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = "1.0"
    treatments: list[Treatment]

    @model_validator(mode="after")
    def _validate(self) -> Specification:
        if not self.treatments:
            raise ValueError("Specification must contain at least one treatment")

        seen_codes: set[str] = set()
        for treatment in self.treatments:
            if treatment.treatment_code in seen_codes:
                raise ValueError(f"Duplicate treatment_code '{treatment.treatment_code}'")
            seen_codes.add(treatment.treatment_code)
        return self


def load_specification(payload: dict[str, Any]) -> Specification:
    """Validate a raw dict against the spec schema and return a typed Specification.

    Raises pydantic.ValidationError on invalid input.
    """
    return Specification.model_validate(payload)
