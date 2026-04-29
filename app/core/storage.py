from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Protocol

from app.core.settings import Settings

logger = logging.getLogger(__name__)


class DocumentStorage(Protocol):
    async def put(self, key: str, body: bytes, content_type: str = "text/plain") -> str:
        ...

    async def get(self, key: str) -> bytes:
        ...

    @property
    def backend(self) -> str:
        ...


class LocalDocumentStorage:
    backend = "local"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        safe = key.lstrip("/").replace("..", "_")
        path = self.root / safe
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    async def put(self, key: str, body: bytes, content_type: str = "text/plain") -> str:
        path = self._path(key)
        await asyncio.to_thread(path.write_bytes, body)
        return f"file://{path}"

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        return await asyncio.to_thread(path.read_bytes)


class S3DocumentStorage:
    backend = "s3"

    def __init__(self, bucket: str, prefix: str, region: str) -> None:
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("boto3 is required for S3 storage") from exc

        self.bucket = bucket
        self.prefix = prefix.rstrip("/")
        self._client = boto3.client("s3", region_name=region or None)

    def _full_key(self, key: str) -> str:
        return f"{self.prefix}/{key.lstrip('/')}" if self.prefix else key.lstrip("/")

    async def put(self, key: str, body: bytes, content_type: str = "text/plain") -> str:
        full_key = self._full_key(key)
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self.bucket,
            Key=full_key,
            Body=body,
            ContentType=content_type,
            ServerSideEncryption="AES256",
        )
        return f"s3://{self.bucket}/{full_key}"

    async def get(self, key: str) -> bytes:
        full_key = self._full_key(key)
        response = await asyncio.to_thread(
            self._client.get_object,
            Bucket=self.bucket,
            Key=full_key,
        )
        return response["Body"].read()


def build_document_storage(settings: Settings) -> DocumentStorage:
    backend = settings.document_storage_backend.strip().lower()
    if backend == "s3":
        if not settings.document_storage_s3_bucket:
            raise RuntimeError("DOCUMENT_STORAGE_S3_BUCKET must be set when backend=s3")
        return S3DocumentStorage(
            bucket=settings.document_storage_s3_bucket,
            prefix=settings.document_storage_s3_prefix,
            region=settings.document_storage_s3_region,
        )
    return LocalDocumentStorage(settings.document_storage_local_path)
