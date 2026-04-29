from __future__ import annotations

from app.integrations.drugbank_api import DrugBankAPI
from app.integrations.rxnorm_api import RxNormAPI
from app.repositories.drug_repository import DrugRepository


class DrugClassService:
    def __init__(self, rxnorm_api: RxNormAPI, drugbank_api: DrugBankAPI | None = None) -> None:
        self.rxnorm_api = rxnorm_api
        self.drugbank_api = drugbank_api
        self._atc_cache: dict[str, str] = {}

    async def ensure_atc_code(self, drug_name: str, drug_repo: DrugRepository) -> str | None:
        drug = await drug_repo.get_or_create(drug_name)
        if drug.atc_code:
            self._atc_cache[drug.normalized_name] = drug.atc_code
            return drug.atc_code

        cached = self._atc_cache.get(drug.normalized_name)
        if cached:
            drug.atc_code = cached
            await drug_repo.session.flush()
            return cached

        atc_code = await self.rxnorm_api.get_atc_code(drug.normalized_name)
        if atc_code is None and self.drugbank_api is not None:
            atc_code = await self.drugbank_api.get_atc_code(drug.normalized_name)

        if atc_code:
            drug.atc_code = atc_code
            self._atc_cache[drug.normalized_name] = atc_code
            await drug_repo.session.flush()
        return atc_code
