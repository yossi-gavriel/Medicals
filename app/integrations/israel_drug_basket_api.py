from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx

from app.core.settings import get_settings

logger = logging.getLogger(__name__)


class IsraelDrugBasketAPI:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._dataset_path = Path(self.settings.israel_basket_dataset_path)

    @staticmethod
    def _normalize(items: list[str]) -> list[str]:
        return [str(item).strip().lower() for item in items if str(item).strip()]

    def _load_dataset_fallback(self) -> list[str]:
        path = self._dataset_path
        if not path.is_absolute():
            path = Path.cwd() / path
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("drugs"), list):
                return self._normalize(data["drugs"])
            if isinstance(data, list):
                return self._normalize(data)
        except Exception as exc:  # pragma: no cover
            logger.warning("israel_basket_dataset_load_failed", extra={"extra": {"error": str(exc), "path": str(path)}})
        return []

    async def fetch_drug_basket(self) -> list[str]:
        if not self.settings.israel_basket_api_url:
            return self._load_dataset_fallback()

        headers = {"Authorization": f"Bearer {self.settings.israel_basket_api_key}"} if self.settings.israel_basket_api_key else {}
        try:
            async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds) as client:
                response = await client.get(self.settings.israel_basket_api_url, headers=headers)
                response.raise_for_status()
                data = response.json()
                if isinstance(data, dict) and isinstance(data.get("drugs"), list):
                    return self._normalize(data["drugs"])
                if isinstance(data, list):
                    return self._normalize(data)
        except Exception as exc:  # pragma: no cover
            logger.warning("israel_basket_fetch_failed", extra={"extra": {"error": str(exc)}})
        return self._load_dataset_fallback()
