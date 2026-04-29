from __future__ import annotations

from app.models import Drug

SEVERITY_ORDER: dict[str, int] = {"A": 0, "B": 1, "C": 2, "D": 3, "X": 4}


class DrugRanker:
    @staticmethod
    def rank(
        drugs: list[Drug],
        reference_atc: str | None,
        severity_profile: dict[int, str] | None = None,
        interaction_risk_counts: dict[int, int] | None = None,
    ) -> list[Drug]:
        if not drugs:
            return []

        severity_profile = severity_profile or {}
        interaction_risk_counts = interaction_risk_counts or {}

        def score(drug: Drug) -> tuple[int, int, int, int, int, str]:
            subclass_match = 0
            if reference_atc and drug.atc_code:
                if drug.atc_code[:5] == reference_atc[:5]:
                    subclass_match = 2
                elif drug.atc_code[:4] == reference_atc[:4]:
                    subclass_match = 1

            worst_severity = severity_profile.get(drug.id, "A")
            severity_score = SEVERITY_ORDER.get(worst_severity, 0)
            basket_bonus = 1 if drug.is_in_israel_basket else 0
            interaction_risk_count = interaction_risk_counts.get(drug.id, 0)
            popularity_score = int(getattr(drug, "popularity_score", 0) or 0)
            return (
                severity_score,
                -subclass_match,
                -basket_bonus,
                interaction_risk_count,
                -popularity_score,
                drug.normalized_name,
            )

        return sorted(drugs, key=score)
