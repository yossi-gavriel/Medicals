from __future__ import annotations

import asyncio

from app.core.cache import cache_client
from app.core.database import SessionLocal, create_all
from app.core.settings import get_settings
from app.integrations.israel_drug_basket_api import IsraelDrugBasketAPI
from app.repositories.drug_repository import DrugRepository
from app.services.drug_basket_service import DrugBasketService


async def main() -> None:
    settings = get_settings()
    await cache_client.connect()
    await create_all()

    service = DrugBasketService(settings, cache_client, IsraelDrugBasketAPI())

    async with SessionLocal() as session:
        repo = DrugRepository(session)
        updated = await service.sync_to_database(repo)
        await session.commit()
        print(f"Updated basket drugs: {updated}")

    await cache_client.close()


if __name__ == "__main__":
    asyncio.run(main())
