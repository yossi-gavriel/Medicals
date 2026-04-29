from __future__ import annotations

from dataclasses import dataclass

from app.algorithms.drug_ranker import DrugRanker


@dataclass
class FakeDrug:
    id: int
    normalized_name: str
    atc_code: str | None
    is_in_israel_basket: bool
    popularity_score: int = 0


def test_ranker_prioritizes_lower_interaction_severity_profile() -> None:
    drugs = [
        FakeDrug(id=1, normalized_name="drug-a", atc_code="C10AA01", is_in_israel_basket=True),
        FakeDrug(id=2, normalized_name="drug-b", atc_code="C10AA05", is_in_israel_basket=True),
    ]
    ranked = DrugRanker.rank(
        drugs,  # type: ignore[arg-type]
        reference_atc="C10AA05",
        severity_profile={1: "B", 2: "A"},
        interaction_risk_counts={1: 0, 2: 1},
    )
    assert [item.id for item in ranked] == [2, 1]


def test_ranker_uses_subclass_then_basket_then_risk_then_popularity() -> None:
    drugs = [
        FakeDrug(id=1, normalized_name="drug-a", atc_code="C10AA01", is_in_israel_basket=False, popularity_score=10),
        FakeDrug(id=2, normalized_name="drug-b", atc_code="C10AA07", is_in_israel_basket=True, popularity_score=2),
        FakeDrug(id=3, normalized_name="drug-c", atc_code="C09AA03", is_in_israel_basket=True, popularity_score=100),
    ]
    ranked = DrugRanker.rank(
        drugs,  # type: ignore[arg-type]
        reference_atc="C10AA05",
        severity_profile={1: "A", 2: "A", 3: "A"},
        interaction_risk_counts={1: 1, 2: 0, 3: 0},
    )
    assert [item.id for item in ranked] == [2, 1, 3]
