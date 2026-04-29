from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(slots=True)
class PatientClinicalProfile:
    age: int | None = None
    egfr: float | None = None
    pregnant: bool | None = None
    has_liver_impairment: bool | None = None


@dataclass(slots=True)
class ContraindicationWarning:
    drug: str
    warning_type: str
    recommendation: str
    source: str = "rule-engine-placeholder"


class ContraindicationChecker:
    """Framework for patient-specific contraindication rules.

    Rules are intentionally conservative placeholders and can be replaced by
    guideline-backed logic in future iterations.
    """

    def check(
        self,
        medications: Sequence[str],
        profile: PatientClinicalProfile | None = None,
    ) -> list[ContraindicationWarning]:
        if profile is None:
            return []

        normalized = [item.strip().lower() for item in medications if item.strip()]
        warnings: list[ContraindicationWarning] = []

        if profile.age is not None and profile.age >= 75:
            for med in normalized:
                if med in {"ibuprofen", "naproxen", "diclofenac"}:
                    warnings.append(
                        ContraindicationWarning(
                            drug=med,
                            warning_type="age",
                            recommendation="Use lowest effective dose and monitor for GI and renal toxicity.",
                        )
                    )

        if profile.egfr is not None and profile.egfr < 30 and "metformin" in normalized:
            warnings.append(
                ContraindicationWarning(
                    drug="metformin",
                    warning_type="renal",
                    recommendation="Avoid or reassess due to severe renal impairment.",
                )
            )

        if profile.pregnant and "warfarin" in normalized:
            warnings.append(
                ContraindicationWarning(
                    drug="warfarin",
                    warning_type="pregnancy",
                    recommendation="Contraindicated in pregnancy; use pregnancy-safe anticoagulation alternative.",
                )
            )

        if profile.has_liver_impairment and "valproic acid" in normalized:
            warnings.append(
                ContraindicationWarning(
                    drug="valproic acid",
                    warning_type="liver",
                    recommendation="Avoid in significant liver impairment unless specialist-supervised.",
                )
            )

        return warnings
