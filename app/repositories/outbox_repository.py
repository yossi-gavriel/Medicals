from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OutboxEvent, OutboxStatus


class OutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def enqueue(
        self,
        *,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        payload: dict[str, Any],
        destination_url: str | None,
        max_attempts: int = 6,
    ) -> OutboxEvent:
        event = OutboxEvent(
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type=event_type,
            payload=payload,
            destination_url=destination_url,
            max_attempts=max_attempts,
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def fetch_due(self, batch_size: int) -> list[OutboxEvent]:
        now = datetime.now(timezone.utc)
        stmt = (
            select(OutboxEvent)
            .where(
                OutboxEvent.status == OutboxStatus.PENDING.value,
                OutboxEvent.next_attempt_at <= now,
            )
            .order_by(OutboxEvent.next_attempt_at.asc())
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def mark_sent(self, event: OutboxEvent) -> None:
        event.status = OutboxStatus.SENT.value
        event.last_error = None
        await self.session.flush()

    async def mark_retry(self, event: OutboxEvent, error: str, backoff_seconds: float) -> None:
        event.attempts = event.attempts + 1
        event.last_error = error[:2048]
        if event.attempts >= event.max_attempts:
            event.status = OutboxStatus.DEAD.value
        else:
            event.status = OutboxStatus.PENDING.value
            event.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds)
        await self.session.flush()

    async def reset_stuck(self, older_than_seconds: int) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)
        stmt = (
            update(OutboxEvent)
            .where(OutboxEvent.status == OutboxStatus.PENDING.value, OutboxEvent.updated_at < cutoff)
            .values(next_attempt_at=datetime.now(timezone.utc))
        )
        result = await self.session.execute(stmt)
        return result.rowcount or 0
