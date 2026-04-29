from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.models import Drug


UnsafeCheck = Callable[[str, str], Awaitable[tuple[bool, str]]]
SEVERITY_ORDER: dict[str, int] = {"A": 0, "B": 1, "C": 2, "D": 3, "X": 4}


@dataclass(slots=True)
class CandidateInteractionProfile:
    worst_severity: str
    interaction_risk_count: int


class AlternativeFinder:
    def __init__(self, unsafe_check: UnsafeCheck) -> None:
        self.unsafe_check = unsafe_check

    async def filter_safe_candidates(
        self,
        candidates: list[Drug],
        against_current: list[str],
        against_new: list[str],
        excluded: set[str],
    ) -> list[Drug]:
        safe, _profiles = await self.filter_safe_candidates_with_profiles(
            candidates=candidates,
            against_current=against_current,
            against_new=against_new,
            excluded=excluded,
        )
        return safe

    async def filter_safe_candidates_with_profiles(
        self,
        candidates: list[Drug],
        against_current: list[str],
        against_new: list[str],
        excluded: set[str],
    ) -> tuple[list[Drug], dict[int, CandidateInteractionProfile]]:
        safe_candidates: list[Drug] = []
        profiles: dict[int, CandidateInteractionProfile] = {}

        for candidate in candidates:
            candidate_name = candidate.normalized_name
            if candidate_name in excluded:
                continue

            unsafe = False
            worst_severity = "A"
            interaction_risk_count = 0
            for other in against_current + against_new:
                is_unsafe, severity = await self.unsafe_check(candidate_name, other)
                if SEVERITY_ORDER.get(severity, 0) > SEVERITY_ORDER.get(worst_severity, 0):
                    worst_severity = severity
                if severity != "A":
                    interaction_risk_count += 1
                if is_unsafe:
                    unsafe = True
                    break

            if not unsafe:
                safe_candidates.append(candidate)
                profiles[candidate.id] = CandidateInteractionProfile(
                    worst_severity=worst_severity,
                    interaction_risk_count=interaction_risk_count,
                )

        return safe_candidates, profiles
