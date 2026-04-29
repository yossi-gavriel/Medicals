from __future__ import annotations


class ClinicalExplanationService:
    @staticmethod
    def explain(drug: str, conflicts_with: str, risk: str, severity: str) -> str:
        severity_phrase = {
            "C": "may require close monitoring",
            "D": "is generally discouraged",
            "X": "is contraindicated",
        }.get(severity, "has a notable interaction")

        return (
            f"{drug.title()} combined with {conflicts_with.title()} {severity_phrase} "
            f"because it can increase the risk of {risk}."
        )
