from __future__ import annotations

import logging

import httpx

from app.core.settings import get_settings

logger = logging.getLogger(__name__)


class RxNormAPI:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def get_atc_code(self, drug_name: str) -> str | None:
        # Primary strategy: external RXNorm + RxClass chain when available.
        base_url = self.settings.rxnorm_api_url.rstrip("/")
        if not base_url:
            return None

        try:
            async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds) as client:
                rxcui_resp = await client.get(f"{base_url}/rxcui.json", params={"name": drug_name})
                rxcui_resp.raise_for_status()
                rxcui_data = rxcui_resp.json()
                ids = rxcui_data.get("idGroup", {}).get("rxnormId", [])
                if not ids:
                    return None
                rxcui = ids[0]

                prop_resp = await client.get(
                    f"{base_url}/rxcui/{rxcui}/allProperties.json",
                    params={"prop": "ATC", "tty": "IN"},
                )
                prop_resp.raise_for_status()
                props = prop_resp.json().get("propConceptGroup", {}).get("propConcept", [])
                if not props:
                    return None
                code = props[0].get("propValue")
                return str(code) if code else None
        except Exception as exc:  # pragma: no cover
            logger.warning("rxnorm_lookup_failed", extra={"extra": {"drug": drug_name, "error": str(exc)}})
            return None
