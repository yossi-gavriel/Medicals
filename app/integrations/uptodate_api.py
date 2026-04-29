from app.integrations.base import BaseInteractionProvider, ExternalInteraction


class UpToDateAPI(BaseInteractionProvider):
    provider_key = "uptodate"
    provider_name = "UpToDate"

    async def get_drug_interactions(self, drug_a: str, drug_b: str) -> ExternalInteraction | None:
        # UpToDate does not provide a public drug-interaction API endpoint.
        return None
