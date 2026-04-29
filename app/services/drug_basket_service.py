from __future__ import annotations

from app.core.cache import CacheClient
from app.core.settings import Settings
from app.integrations.israel_drug_basket_api import IsraelDrugBasketAPI
from app.repositories.drug_repository import DrugRepository


class DrugBasketService:
    CACHE_KEY = "israel:basket:drugs"

    def __init__(self, settings: Settings, cache_client: CacheClient, basket_api: IsraelDrugBasketAPI) -> None:
        self.settings = settings
        self.cache = cache_client
        self.basket_api = basket_api

    async def get_basket_drugs(self) -> list[str]:
        cached = await self.cache.get_json(self.CACHE_KEY)
        if cached and isinstance(cached.get("drugs"), list):
            return [str(item).strip().lower() for item in cached["drugs"] if str(item).strip()]

        drugs = await self.basket_api.fetch_drug_basket()
        await self.cache.set_json(
            self.CACHE_KEY,
            {"drugs": drugs},
            self.settings.basket_cache_ttl_seconds,
        )
        return drugs

    async def sync_to_database(self, drug_repo: DrugRepository) -> int:
        basket_drugs = await self.get_basket_drugs()

        for drug_name in basket_drugs:
            await drug_repo.get_or_create(drug_name)

        await drug_repo.set_israel_basket_flags(basket_drugs)
        return len(basket_drugs)
