from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document


def compute_document_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_hash(self, tenant_id: str, document_hash: str) -> Document | None:
        result = await self.session.execute(
            select(Document).where(
                Document.tenant_id == tenant_id,
                Document.document_hash == document_hash,
            )
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        *,
        tenant_id: str,
        document_hash: str,
        procedure_code: str,
        storage_uri: str,
        size_bytes: int,
        source_system: str | None,
        external_document_id: str | None,
        metadata: dict[str, Any] | None,
    ) -> Document:
        existing = await self.get_by_hash(tenant_id, document_hash)
        if existing is not None:
            return existing

        document = Document(
            tenant_id=tenant_id,
            document_hash=document_hash,
            procedure_code=procedure_code,
            storage_uri=storage_uri,
            size_bytes=size_bytes,
            source_system=source_system,
            external_document_id=external_document_id,
            metadata_json=metadata or {},
        )
        self.session.add(document)
        await self.session.flush()
        return document
