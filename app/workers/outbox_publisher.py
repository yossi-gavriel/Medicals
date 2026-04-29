from __future__ import annotations

import asyncio
import json
import logging
import signal

import httpx

from app.core.database import SessionLocal
from app.core.logging import configure_logging
from app.core.security import sign_payload
from app.core.settings import Settings, get_settings
from app.models import OutboxEvent
from app.repositories.outbox_repository import OutboxRepository

logger = logging.getLogger(__name__)


def _backoff_seconds(attempts: int) -> float:
    return min(60.0 * (2 ** max(attempts - 1, 0)), 3600.0)


async def _send_event(client: httpx.AsyncClient, event: OutboxEvent, settings: Settings) -> None:
    if not event.destination_url:
        async with SessionLocal() as session:
            repo = OutboxRepository(session)
            event_in_session = await session.merge(event)
            await repo.mark_sent(event_in_session)
            await session.commit()
        return

    payload_bytes = json.dumps(event.payload, default=str, separators=(",", ":")).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-Event-Type": event.event_type,
        "X-Event-Id": str(event.id),
        "X-Aggregate-Id": event.aggregate_id,
    }
    if settings.webhook_signing_secret:
        headers["X-Signature"] = sign_payload(settings.webhook_signing_secret, payload_bytes)

    try:
        response = await client.post(event.destination_url, content=payload_bytes, headers=headers)
        response.raise_for_status()
    except Exception as exc:
        logger.warning(
            "outbox_send_failed",
            extra={"extra": {"event_id": str(event.id), "error": str(exc)}},
        )
        async with SessionLocal() as session:
            repo = OutboxRepository(session)
            event_in_session = await session.merge(event)
            await repo.mark_retry(
                event_in_session,
                error=str(exc),
                backoff_seconds=_backoff_seconds(event_in_session.attempts + 1),
            )
            await session.commit()
        return

    async with SessionLocal() as session:
        repo = OutboxRepository(session)
        event_in_session = await session.merge(event)
        await repo.mark_sent(event_in_session)
        await session.commit()


async def _process_batch(client: httpx.AsyncClient, settings: Settings) -> int:
    async with SessionLocal() as session:
        repo = OutboxRepository(session)
        events = await repo.fetch_due(settings.outbox_batch_size)
        for event in events:
            session.expunge(event)
        await session.commit()

    if not events:
        return 0

    await asyncio.gather(*[_send_event(client, event, settings) for event in events])
    return len(events)


async def run_loop() -> None:
    configure_logging()
    settings = get_settings()
    stop_event = asyncio.Event()

    def _request_stop(*_: object) -> None:
        logger.info("outbox_publisher_stopping")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:  # pragma: no cover - platform dependent
            signal.signal(sig, lambda *_: _request_stop())

    logger.info("outbox_publisher_started")
    async with httpx.AsyncClient(timeout=10.0) as client:
        while not stop_event.is_set():
            try:
                processed = await _process_batch(client, settings)
            except Exception:
                logger.exception("outbox_loop_error")
                processed = 0

            if processed == 0:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=settings.outbox_poll_interval_seconds)
                except asyncio.TimeoutError:
                    pass


def main() -> None:
    asyncio.run(run_loop())


if __name__ == "__main__":
    main()
