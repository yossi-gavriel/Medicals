from app.integrations.base import BaseInteractionProvider, ExternalInteraction


class DynaMedAPI(BaseInteractionProvider):
    provider_key = "dynamed"
    provider_name = "DynaMed"

    async def get_drug_interactions(self, drug_a: str, drug_b: str) -> ExternalInteraction | None:
        # DynaMed does not provide a public drug-interaction API endpoint.
        return None
