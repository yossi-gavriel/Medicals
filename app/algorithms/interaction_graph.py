from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class InteractionEdge:
    severity: str
    risk: str
    recommendation: str
    source: str


class InteractionGraph:
    def __init__(self) -> None:
        self._adjacency: dict[str, dict[str, InteractionEdge]] = {}

    @staticmethod
    def _normalize(drug: str) -> str:
        return drug.strip().lower()

    def upsert_interaction(
        self,
        drug_a: str,
        drug_b: str,
        severity: str,
        risk: str,
        recommendation: str,
        source: str,
    ) -> None:
        a = self._normalize(drug_a)
        b = self._normalize(drug_b)

        edge = InteractionEdge(
            severity=severity,
            risk=risk,
            recommendation=recommendation,
            source=source,
        )

        self._adjacency.setdefault(a, {})[b] = edge
        self._adjacency.setdefault(b, {})[a] = edge

    def get_interaction(self, drug_a: str, drug_b: str) -> InteractionEdge | None:
        a = self._normalize(drug_a)
        b = self._normalize(drug_b)
        return self._adjacency.get(a, {}).get(b)

    def size(self) -> int:
        return sum(len(neighbors) for neighbors in self._adjacency.values()) // 2

    def clear(self) -> None:
        self._adjacency.clear()
