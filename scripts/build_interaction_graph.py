from __future__ import annotations

import asyncio
from itertools import combinations

from app.algorithms.interaction_graph import InteractionGraph
from app.core.cache import cache_client
from app.core.database import SessionLocal, create_all
from app.core.settings import get_settings
from app.integrations.drugbank_api import DrugBankAPI
from app.integrations.rxnorm_api import RxNormAPI
from app.repositories.drug_repository import DrugRepository
from app.repositories.interaction_repository import InteractionRepository
from app.services.drug_class_service import DrugClassService
from app.services.interaction_service import InteractionService


async def main() -> None:
    settings = get_settings()
    await cache_client.connect()
    await create_all()

    graph = InteractionGraph()
    class_service = DrugClassService(
        RxNormAPI(),
        DrugBankAPI(settings, settings.drugbank_api_url, settings.drugbank_api_key),
    )
    interaction_service = InteractionService(settings, cache_client, graph, class_service)

    async with SessionLocal() as session:
        drug_repo = DrugRepository(session)
        interaction_repo = InteractionRepository(session)
        common_drugs = await drug_repo.list_common_drugs(limit=2000)
        names = [drug.normalized_name for drug in common_drugs]

        if len(names) < 2:
            print("Not enough drugs to build interaction graph.")
            return

        semaphore = asyncio.Semaphore(25)
        processed = 0
        batch: list[asyncio.Task[None]] = []

        async def compute_pair(drug_a: str, drug_b: str) -> None:
            async with semaphore:
                await interaction_service.checker.check_pair(drug_a, drug_b, drug_repo, interaction_repo)

        for drug_a, drug_b in combinations(names, 2):
            batch.append(asyncio.create_task(compute_pair(drug_a, drug_b)))
            if len(batch) >= 500:
                await asyncio.gather(*batch)
                processed += len(batch)
                batch.clear()
                await session.commit()
                print(f"Processed pairs: {processed}")

        if batch:
            await asyncio.gather(*batch)
            processed += len(batch)
            await session.commit()

        await interaction_service.load_graph(session)
        print(f"Interaction graph warmed. Pairs processed: {processed}, graph edges: {graph.size()}")

    await cache_client.close()


if __name__ == "__main__":
    asyncio.run(main())
