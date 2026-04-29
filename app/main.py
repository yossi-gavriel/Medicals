from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.algorithms.interaction_graph import InteractionGraph
from app.api.routes_classification import router as classifications_router
from app.api.routes_dashboard import router as dashboard_router
from app.api.routes_extractions import router as extractions_router
from app.api.routes_health import router as health_router
from app.api.routes_interactions import router as interactions_router
from app.api.routes_medical_classifier import router as medical_classifier_router
from app.core.cache import cache_client
from app.core.database import SessionLocal
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import RateLimitMiddleware, RequestContextMiddleware
from app.core.queue import ArqJobEnqueuer
from app.core.rate_limit import RateLimiter
from app.core.settings import get_settings
from app.core.storage import build_document_storage
from app.integrations.drugbank_api import DrugBankAPI
from app.integrations.israel_drug_basket_api import IsraelDrugBasketAPI
from app.integrations.rxnorm_api import RxNormAPI
from app.repositories.drug_repository import DrugRepository
from app.services.classification_pipeline import ClassificationPipeline
from app.services.drug_basket_service import DrugBasketService
from app.services.drug_class_service import DrugClassService
from app.services.extraction_engine import (
    build_extraction_engine_from_settings,
    build_llm_rule_resolver,
)
from app.services.interaction_service import InteractionService
from app.services.medical_classifier import (
    ProcedureClassificationService,
    build_generic_fallback_prompt_json,
    build_medical_classifier_llm_runner,
)

logger = logging.getLogger(__name__)


async def _basket_refresh_loop(app: FastAPI) -> None:
    while True:
        try:
            async with SessionLocal() as session:
                repo = DrugRepository(session)
                updated = await app.state.drug_basket_service.sync_to_database(repo)
                await session.commit()
                logger.info("basket_sync_completed", extra={"extra": {"count": updated}})
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover
            logger.warning("basket_sync_failed", extra={"extra": {"error": str(exc)}})

        await asyncio.sleep(60 * 60 * 24)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(level=getattr(logging, settings.app_log_level.upper(), logging.INFO))

    await cache_client.connect()

    graph = InteractionGraph()
    class_service = DrugClassService(
        RxNormAPI(),
        DrugBankAPI(settings, settings.drugbank_api_url, settings.drugbank_api_key),
    )
    interaction_service = InteractionService(settings, cache_client, graph, class_service)
    drug_basket_service = DrugBasketService(settings, cache_client, IsraelDrugBasketAPI())
    medical_classifier_service = ProcedureClassificationService.from_settings(
        llm_runner=build_medical_classifier_llm_runner(settings),
        settings=settings,
        prompt_provider=build_generic_fallback_prompt_json,
    )
    extraction_llm_resolver = build_llm_rule_resolver(settings)
    extraction_engine = build_extraction_engine_from_settings(
        settings,
        llm_resolver=extraction_llm_resolver if extraction_llm_resolver.is_available() else None,
    )
    storage = build_document_storage(settings)
    enqueuer = await ArqJobEnqueuer.connect(settings)
    classification_pipeline = ClassificationPipeline(
        settings=settings,
        storage=storage,
        enqueuer=enqueuer,
    )

    app.state.settings = settings
    app.state.interaction_service = interaction_service
    app.state.drug_basket_service = drug_basket_service
    app.state.medical_classifier_service = medical_classifier_service
    app.state.extraction_engine = extraction_engine
    app.state.document_storage = storage
    app.state.job_enqueuer = enqueuer
    app.state.classification_pipeline = classification_pipeline

    async with SessionLocal() as session:
        repo = DrugRepository(session)
        await drug_basket_service.sync_to_database(repo)
        await interaction_service.load_graph(session)
        await session.commit()

    app.state.basket_refresh_task = asyncio.create_task(_basket_refresh_loop(app))

    try:
        yield
    finally:
        task = app.state.basket_refresh_task
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await enqueuer.close()
        await cache_client.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Drug Safety Engine",
        version="1.1.0",
        description="Clinical decision support API: drug-drug interactions + medical document classification.",
        lifespan=lifespan,
    )

    rate_limiter = RateLimiter(cache_client)
    app.state.rate_limiter = rate_limiter
    if settings.rate_limit_enabled:
        # The limiter resolves Redis through cache_client at request time, so
        # it picks up the connection once lifespan finishes connecting.
        app.add_middleware(
            RateLimitMiddleware,
            limiter=rate_limiter,
            limit_per_window=settings.rate_limit_per_minute,
            window_seconds=settings.rate_limit_window_seconds,
            excluded_paths=tuple(settings.rate_limit_excluded_paths),
            anonymous_limit=settings.rate_limit_anonymous_per_minute,
        )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins or ["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)

    app.include_router(health_router)
    app.include_router(interactions_router)
    app.include_router(medical_classifier_router)
    app.include_router(classifications_router)
    app.include_router(extractions_router)
    app.include_router(dashboard_router)
    return app


app = create_app()
