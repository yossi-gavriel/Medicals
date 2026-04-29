from __future__ import annotations

from app.algorithms.alternative_finder import AlternativeFinder
from app.algorithms.alternative_finder import CandidateInteractionProfile
from app.algorithms.drug_ranker import DrugRanker
from app.algorithms.interaction_checker import InteractionChecker
from app.repositories.drug_repository import DrugRepository
from app.repositories.interaction_repository import InteractionRepository
from app.schemas import SuggestedAlternative
from app.services.drug_class_service import DrugClassService


class AlternativeService:
    def __init__(self, checker: InteractionChecker, class_service: DrugClassService) -> None:
        self.checker = checker
        self.class_service = class_service

    async def suggest_alternatives(
        self,
        unsafe_drug: str,
        current_drugs: list[str],
        pending_new_drugs: list[str],
        drug_repo: DrugRepository,
        interaction_repo: InteractionRepository,
    ) -> list[SuggestedAlternative]:
        atc_code = await self.class_service.ensure_atc_code(unsafe_drug, drug_repo)
        candidates = await drug_repo.find_by_atc_class(atc_code, limit=100)

        async def unsafe_check(candidate: str, other: str) -> tuple[bool, str]:
            result = await self.checker.check_pair(candidate, other, drug_repo, interaction_repo)
            return result.is_unsafe, result.severity

        finder = AlternativeFinder(unsafe_check)
        safe_candidates, profiles = await finder.filter_safe_candidates_with_profiles(
            candidates=candidates,
            against_current=current_drugs,
            against_new=pending_new_drugs,
            excluded={unsafe_drug.lower()},
        )

        severity_profile = {drug_id: profile.worst_severity for drug_id, profile in profiles.items()}
        risk_counts = {drug_id: profile.interaction_risk_count for drug_id, profile in profiles.items()}
        ranked = DrugRanker.rank(safe_candidates, atc_code, severity_profile, risk_counts)
        top = ranked[:3]

        suggestions: list[SuggestedAlternative] = []
        for item in top:
            profile: CandidateInteractionProfile | None = profiles.get(item.id)
            has_same_subclass = bool(atc_code and item.atc_code and item.atc_code[:5] == atc_code[:5])
            reason = "same pharmacologic subclass" if has_same_subclass else "same therapeutic class"
            interaction_risk = "none detected"
            if profile is not None:
                if profile.interaction_risk_count > 0:
                    interaction_risk = f"low residual profile (max severity {profile.worst_severity})"
                else:
                    interaction_risk = f"none detected (max severity {profile.worst_severity})"

            suggestions.append(
                SuggestedAlternative(
                    drug=item.normalized_name,
                    reason=reason,
                    interaction_risk=interaction_risk,
                )
            )
        return suggestions
